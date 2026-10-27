"""Resolve small gaps between asphalt banks before deriving land and curbs.

A source draw fragment is not a physical road boundary. Repairs require two
opposing asphalt banks on the same level and exclude explicit land/islands.
Widths are reconstruction tolerances, not surveyed road measurements.
"""
import numpy as np
import shapely as sh
from shapely.geometry import Polygon, Point, LineString, mapping
from spatial_mask import SpatialMask

MAX_SEAM_WIDTH = .05


def interior_probe(polygon, distance):
    # A fixed-precision negative buffer can collapse a rotated, millimetre-wide
    # strip even when its true interior is much wider than this probe. Measure
    # in floating precision; keep the original overlay grid for emitted repair
    # geometry. This is a width test, not an alteration of the source contour.
    return sh.set_precision(polygon, 0).buffer(-distance)


def parts(g):
    if g.is_empty:
        return []
    if g.geom_type == 'Polygon':
        return [g]
    return [p for sub in getattr(g, 'geoms', []) for p in parts(sub)]


def protected_geometry(candidates, records, road, precision):
    # Administrative/background cover is a fallback, not evidence of a path
    # or traffic island. Specific land cover and other road levels are evidence.
    properties = {f['id']: f['properties'] for f in records}
    mask=SpatialMask(road)
    protected, remnants = [], []
    for r in candidates:
        # An open descent removes ground. A buried tunnel does not: its XY
        # footprint must not punch a slit through an unrelated surface road.
        if r['kind'] == 'road' and r['part'] == 'roadbed_tunnel_descent':
            protected.append(r['poly'])
        elif r['kind'] == 'land' and (r.get('material') in [2, 7] or
              (r.get('rank', 0) > 0 and properties.get(r['id'], {}).get('db_layer') not in [49, 56])):
            # Coarse cover polygons can extend under the asphalt. Subtracting
            # raw draw fragments may sever a millimetre-wide remnant from the
            # real lawn/path. It is not an independent source island. Preserve
            # originally separate source polygons and detailed physical cover.
            coarse = properties.get(r['id'], {}).get('db_layer') in [49, 56]
            for original in parts(r['poly']):
                pieces = parts(original.difference(mask.near(original))) if coarse else [original]
                largest = max((p.area for p in pieces), default=0.)
                for p in pieces:
                    detached = len(pieces) > 1 and largest > p.area*100
                    if coarse and detached and interior_probe(p,MAX_SEAM_WIDTH/2).is_empty:
                        remnants.append(dict(sourceObject=r['id'],layer=r['layer'],areaM2=p.area,
                                             geometry=mapping(p),evidence='detached narrow remnant of a coarse cover polygon after raw asphalt subtraction'))
                    else:
                        protected.append(p)
    for f in records:
        # Painted safety hatching remains asphalt. Only an actual ground curb
        # outline supplies evidence of a physical separation here; a closed
        # outline surrounds a road too, so never fill its whole ring as land.
        if not f['layer'].startswith('Roadbed_outline') or f['properties'].get('db_road_part') != 'border_flat' or len(f['coordinates']) < 2:
            continue
        xy = np.asarray(f['coordinates'])[:, :2]
        line = LineString(xy)
        protected.append(line.buffer(MAX_SEAM_WIDTH/2))
    return (sh.union_all(protected, grid_size=precision) if protected else Polygon()), remnants


def reconcile(road, candidates, records, extent, precision, max_width=MAX_SEAM_WIDTH):
    """Return only repairs supported along their whole width, including open slits.

    Closing proposes gaps; it never decides alone. Each constrained triangle's
    interior and the polygon interior must see source asphalt in both opposite
    directions, with matching physical tiers. This rejects one-sided exterior
    corner smoothing and crossings of unrelated road levels. Area is not capped:
    a long narrow source seam must obey the same rule as a short one.
    """
    rows = [r for r in candidates if r['kind'] == 'road' and r['part'] == 'roadbed_flat']
    if not rows:
        return road, [], dict(candidateCount=0, repairs=0, rejected=[], maxWidthM=max_width)
    tree = sh.STRtree([r['poly'] for r in rows])
    properties = {f['id']: f['properties'] for f in records}
    # The proposal envelope is a function of immutable source banks. Closing
    # the already repaired contour again advances some acute exterior tips by
    # a fraction of a millimetre on every pass and can never be idempotent.
    source_road=sh.union_all([r['poly'] for r in rows],grid_size=precision)
    protected, remnants = protected_geometry(candidates, records, source_road, precision)
    radius = max_width/2
    closed = source_road.buffer(radius, join_style='mitre').buffer(-radius, join_style='mitre')
    proposal = sh.set_precision(sh.make_valid(closed.difference(road).intersection(extent)), precision)
    protected_area = proposal.intersection(protected).area
    proposal = sh.set_precision(proposal.difference(protected.buffer(precision*3)), precision)
    repairs, rejected = [], []
    candidates_count = 0
    enclosed=[Polygon(ring) for poly in parts(road) for ring in poly.interiors]
    enclosure_tree=sh.STRtree(enclosed)
    for p in parts(proposal):
        if p.area < precision**2*10 or interior_probe(p,precision*5).is_empty:
            continue
        is_enclosed=any(enclosed[int(i)].buffer(precision*3).covers(p) for i in enclosure_tree.query(p))
        candidates_count += 1
        triangles = sh.get_parts(sh.constrained_delaunay_triangles(p))
        samples = [t.centroid for t in triangles] + [p.representative_point()]
        parents, pairs, max_radius, reason, level = set(), set(), 0., None, None
        if not interior_probe(p,radius).is_empty:
            reason = 'gap contains a region wider than the tolerance'
        for point in samples:
            if reason:
                break
            xy = np.asarray(point.coords)[0]
            nearest = sh.shortest_line(point, road)
            if nearest.is_empty or nearest.length <= precision/10:
                # A numerical tip has no measurable gap. Other interior
                # samples still have to establish two physical banks.
                if is_enclosed:continue
                reason = 'ambiguous nearest bank';break
            delta = np.asarray(nearest.coords)[-1] - xy
            distance = float(np.linalg.norm(delta))
            max_radius = max(max_radius, distance)
            if distance > radius + precision*3:
                reason = 'sample exceeds half-width tolerance'
                break
            normal = delta/distance
            # Stay far enough beyond the gap to avoid overlay-grid drift while
            # remaining within a small, local pair of asphalt banks.
            a = Point(xy + normal*(max_width+precision*10))
            b = Point(xy - normal*(max_width+precision*10))
            aa = [int(i) for i in tree.query(a, predicate='covered_by')]
            bb = [int(i) for i in tree.query(b, predicate='covered_by')]
            if is_enclosed and (not aa or not bb):
                # A fixed-distance probe can overshoot a short asphalt wedge
                # at the tip of an enclosed crack. Require an interior road
                # interval on each ray instead. Exterior notches retain the
                # stricter probes and cannot become rounded road corners.
                def bank(direction):
                    ray=LineString([xy+direction*precision*3,xy+direction*(max_width+precision*10)])
                    return [int(i) for i in tree.query(ray,predicate='intersects')
                            if rows[int(i)]['poly'].intersection(ray).length>precision*5]
                # At a concave tip the nearest point can be a corner, whose
                # diagonal is not the normal of either bank. Test deterministic
                # transverse directions as well, retaining the same distance
                # limit and two-sided same-tier evidence.
                matched=[]
                for direction in [normal,*[np.array([np.cos(a),np.sin(a)]) for a in np.linspace(0,np.pi,16,endpoint=False)]]:
                    aa,bb=bank(direction),bank(-direction)
                    matched.extend((i,j) for i in aa for j in bb if tuple(rows[i]['tiers'])==tuple(rows[j]['tiers']))
            else:
                matched = [(i, j) for i in aa for j in bb if tuple(rows[i]['tiers']) == tuple(rows[j]['tiers'])]
            if not matched:
                reason = 'no opposing asphalt banks on the same level'
                break
            sample_levels = {tuple(rows[i]['tiers']) for i, j in matched}
            if len(sample_levels) != 1 or (level is not None and level not in sample_levels):
                reason = 'ambiguous or changing physical level along the seam'
                break
            level = next(iter(sample_levels))
            for i, j in matched:
                parents.update([rows[i]['id'], rows[j]['id']])
                pairs.add(tuple(sorted([rows[i]['id'], rows[j]['id']])))
        if reason or not parents:
            reason=reason or 'no measurable two-sided interior samples'
            rejected.append(dict(areaM2=p.area, bounds=list(p.bounds), reason=reason,enclosed=is_enclosed,
                                 witness=list(point.coords)[0] if samples else None))
            continue
        source_ids = sorted({str(properties.get(owner, {}).get('id')) for owner in parents
                             if properties.get(owner, {}).get('id') is not None})
        repairs.append(dict(type='two-sided-road-seam', geometry=mapping(p), areaM2=p.area,
                            maxSampledHalfWidthM=max_radius, widthLimitM=max_width,
                            sourceParents=sorted(parents), sourceRoadObjectIds=source_ids,
                            bankPairs=[list(pair) for pair in sorted(pairs)], tiers=list(level), samples=len(samples),
                            evidence='opposing source asphalt banks with matching tiers; explicit land and islands excluded; inferred contour repair'))
    result = sh.union_all([road]+[sh.geometry.shape(r['geometry']) for r in repairs], grid_size=precision)
    report = dict(candidateCount=candidates_count, repairs=len(repairs),
                  repairedAreaM2=sum(r['areaM2'] for r in repairs), maxWidthM=max_width,
                  protectedAreaM2=protected_area, rejected=rejected,
                  coverRemnants=remnants,
                  policy='repair source draw seams before land/curbs; two-sided same-level asphalt evidence, protected semantic cover; never close gaps by area alone')
    return result, repairs, report
