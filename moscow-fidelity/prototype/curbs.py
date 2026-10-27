"""A reconstruction rule: raised land and solid curbs along ground-road contours.

The source boundary fixes XY. Height and width are explicit design parameters;
they are not claimed to be surveyed dimensions supplied by 2GIS.
"""
import numpy as np
import shapely as sh
from shapely.geometry import Polygon, LineString
from spatial_mask import LinearMask

LAND_RAISE = .10
CURB_WIDTH = .15
CURB_MATERIAL = 9


def parts(g, kind):
    if g.is_empty: return []
    if g.geom_type == kind: return [g]
    return [p for sub in getattr(g, 'geoms', []) for p in parts(sub, kind)]


def band(road, opening, extent, precision):
    from passage_space import stable_area
    # One global union, rather than a border per source feature/tile/mesh.
    expanded = road.buffer(CURB_WIDTH, quad_segs=4, join_style='mitre', mitre_limit=2)
    g=sh.set_precision(sh.make_valid(expanded.difference(road)
        .difference(opening).intersection(extent)), precision)
    return stable_area(g,precision)


def solid_sides(curb_band, road, dem, demtree, groups, z_at, extent):
    """Top and bottom cells are emitted by the land partition; add volume sides.

    Polygon rings put solid on the left; side faces consequently point right.
    No artificial wall is constructed along the experiment's cropping rectangle.
    """
    front = []; seen = set(); count = 0
    sh.prepare(road);sh.prepare(curb_band)
    road_edges=LinearMask(road.boundary)
    crop_boundary=extent.boundary.buffer(.00005)
    for poly in parts(sh.orient_polygons(curb_band), 'Polygon'):
        for ring in [poly.exterior, *poly.interiors]:
            xy = np.asarray(ring.coords)[:,:2]
            for start, end in zip(xy, xy[1:]):
                segment = LineString([start,end]).difference(crop_boundary)
                for line in parts(segment, 'LineString'):
                    for i in demtree.query(line,predicate='intersects'):
                        for piece in parts(line.intersection(dem[i][0]), 'LineString'):
                            coords = np.asarray(piece.coords)[:,:2]
                            for a,b in zip(coords,coords[1:]):
                                if np.linalg.norm(a-b)<1e-5: continue
                                # Intersection may reverse ring direction.
                                if np.dot(b-a,end-start)<0: a,b=b,a
                                key=tuple(sorted([tuple(np.round(a,5)),tuple(np.round(b,5))]))
                                if key in seen: continue
                                seen.add(key)
                                low=z_at(dem[i][1],[a,b]); high=low+LAND_RAISE
                                v=np.array([[*a,low[0]],[*b,low[1]],[*b,high[1]],[*a,high[0]]])
                                face=LineString([a,b])
                                outward=np.array([b[1]-a[1],a[0]-b[0]])/np.linalg.norm(b-a)
                                # A cut end near the road is not a road-facing
                                # face. Classify by the directed solid boundary,
                                # not proximity alone (which mislabels tiny
                                # transition-end edges after grid rounding).
                                midpoint_xy=(a+b)/2
                                # At a narrow corner a fixed 1 mm probe can
                                # jump across the asphalt into the opposite
                                # curb. Confirm both sides locally instead.
                                road_facing=any(
                                    curb_band.covers(sh.Point(midpoint_xy-outward*probe)) and
                                    road.covers(sh.Point(midpoint_xy+outward*probe))
                                    for probe in (.00001,.000025,.00005,.0001,.001))
                                midpoint=face.interpolate(.5,normalized=True)
                                distance=0. if road.covers(midpoint) else midpoint.distance(road_edges.segments[int(road_edges.tree.nearest(midpoint))])
                                kind='curb_front' if distance<.00005 and road_facing else 'curb_back'
                                groups[(kind,CURB_MATERIAL)].extend([v[[0,1,2]],v[[0,2,3]]])
                                if kind=='curb_front': front.append(face)
                                count+=1
    return sh.union_all(front), count


def source_evidence(records):
    outlines=[f for f in records if f['layer'].startswith('Roadbed_outline')]
    ground=[f['id'] for f in outlines if f['properties'].get('db_road_part')=='border_flat']
    return dict(groundOutlineSourceIds=ground,groundOutlineFeatureCount=len(ground),
        otherLevelOutlineFeatureCount=len(outlines)-len(ground),
        policy='Ground curbs replace legacy ground edges; road polygon union defines the border. '
               'Source outline records remain as evidence. No duplicate legacy curb meshes are emitted.')
