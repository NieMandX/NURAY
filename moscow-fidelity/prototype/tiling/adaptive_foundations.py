"""Extend actual ground-contact facade edges down to the finished terrain.

Never extrude a roof silhouette or a bounding box. Only edges at the source
building's rigid placement base qualify, so elevated arch lintels, balconies,
canopies and disconnected roof fragments cannot become solid walls. Solve the
profile against the canonical ground before the transport grid cuts any mesh.
"""
from collections import defaultdict
from pathlib import Path
import gzip
import numpy as np
import shapely as sh
from physical_geometry import ownership
from street_placement import SurfaceSampler, GROUND_NAMES
from object_geometry import pack

BASE_TOLERANCE = .02  # Source-model/terrain-base rounding, not a search radius.
MIN_GAP = .005
BURIAL = .02
CONTACT_BAND = .025  # Retained source XY quantization is about 2.1 cm.
MATERIAL = 6  # Established gray concrete PBR, shared with retaining walls.
POLICY = dict(version=1, baseToleranceM=BASE_TOLERANCE, minimumGapM=MIN_GAP,
              burialM=BURIAL, contactBandM=CONTACT_BAND, material=MATERIAL,
              rule='extend source facade bottom edges at the rigid building base; exact upper envelope of finished ground; sample adjacent ground within 2.5 cm only for quantization gaps; no nearest-triangle extrapolation',
              exclusions='canopies, roof-only pieces, elevated arch/overhang edges, unsupported terrain voids; no tile-boundary caps')


def eligible(row):
    return (row['category'] in {'building', 'landmark'}
            and row['placement'].get('targetBaseM') is not None
            and row['placement'].get('sourceBaseM') is not None
            and row.get('sourceLayer', '').split('_')[0] != 'Canopy'
            and '_roof_' not in row.get('sourceLayer', ''))


def base_edges(triangles, base):
    """Keep the real bottom edge, including its exact packed height/position."""
    edges = {}
    for t in triangles:
        on = np.abs(t[:, 1] - base) <= BASE_TOLERANCE
        if on.sum() != 2 or t[~on, 1][0] <= base + BASE_TOLERANCE:
            continue
        a, b = t[on]
        if np.linalg.norm(b[[0, 2]] - a[[0, 2]]) < 1e-5:
            continue
        # Keep the facade's winding, so the plinth has the same outward normal.
        source_normal=np.cross(t[1]-t[0],t[2]-t[0])
        if np.dot(np.cross([0,-1,0],b-a),source_normal)<0:a,b=b,a
        ordered=(a,b) if tuple(a)<tuple(b) else (b,a)
        key = tuple(np.round(np.r_[ordered[0], ordered[1]], 6))
        edges[key] = (a.copy(), b.copy())
    return list(edges.values())


def ground_intervals(a, b, ground):
    """Intersect a segment with every ground triangle analytically.

    Every profile breakpoint is a terrain/curb triangle edge or an intersection
    of overlapping height planes. Endpoint-only sampling would miss a valley.
    """
    line = sh.LineString([a[[0, 2]], b[[0, 2]]])
    ids = ground.tree.query(line, predicate='intersects')
    out = []
    for i in ids:
        t = ground.tris[i]; p, q, r = t[:, [0, 2]]
        matrix = np.column_stack((q - p, r - p))
        uv = np.linalg.solve(matrix, np.column_stack((a[[0, 2]] - p, b[[0, 2]] - p)))
        weights = np.vstack((1 - uv.sum(0), uv))
        lo, hi = 0., 1.
        for w0, w1 in weights:
            d = w1 - w0
            if abs(d) < 1e-12:
                if w0 < -1e-9: hi = -1.
            elif d > 0: lo = max(lo, -w0 / d)
            else: hi = min(hi, -w0 / d)
        if hi - lo <= 1e-10: continue
        heights = t[:, 1] @ weights
        out.append((lo, hi, heights[0], heights[1], int(i)))
    if not out: return []
    breaks = sorted({0., 1., *(x for r in out for x in r[:2])})
    result = []
    for lo, hi in zip(breaks, breaks[1:]):
        if hi - lo <= 1e-10: continue
        mid = (lo + hi) / 2
        active = [r for r in out if r[0] - 1e-10 <= mid <= r[1] + 1e-10]
        if not active: continue  # A cutout is not ground; never bridge it.
        splits = {lo, hi}
        for j, x in enumerate(active):
            for y in active[:j]:
                d = (x[3] - x[2]) - (y[3] - y[2])
                if abs(d) < 1e-12: continue
                cross = (y[2] - x[2]) / d
                if lo < cross < hi: splits.add(cross)
        splits = sorted(splits)
        for u, v in zip(splits, splits[1:]):
            r = max(active, key=lambda r: r[2] + (u + v) / 2 * (r[3] - r[2]))
            h = lambda s: r[2] + s * (r[3] - r[2])
            result.append((u, v, h(u), h(v), r[4]))
    return result


def panels_for_edge(a, b, ground):
    length = float(np.linalg.norm(b[[0, 2]] - a[[0, 2]]))
    intervals = [(*r,[0.,0.]) for r in ground_intervals(a, b, ground)]
    # Separate source meshes can miss a finished curb edge by one coordinate
    # quantization step. Use a bounded, real adjacent contact, never an arbitrary
    # nearest plane or a long extrapolation over a tunnel opening.
    d=(b-a)[[0,2]];side=np.array([-d[1],d[0]])/length*CONTACT_BAND
    for offset in [side,-side]:
        covered=sh.union_all([sh.LineString([[u,0],[v,0]]) for u,v,*_ in intervals])
        missing=sh.LineString([[0,0],[1,0]]).difference(covered)
        if missing.is_empty:break
        aa,bb=a.copy(),b.copy();aa[[0,2]]+=offset;bb[[0,2]]+=offset
        for u,v,h0,h1,source in ground_intervals(aa,bb,ground):
            for gap in sh.get_parts(missing):
                lo,hi=max(u,gap.bounds[0]),min(v,gap.bounds[2])
                if hi-lo<=1e-10:continue
                height=lambda s:h0+(h1-h0)*(s-u)/(v-u)
                intervals.append((lo,hi,height(lo),height(hi),source,offset.tolist()))
    intervals.sort(key=lambda r:r[0])
    panels = []
    for u, v, h0, h1, source, offset in intervals:
        p, q = a + (b - a) * u, a + (b - a) * v
        gap = np.array([p[1] - h0, q[1] - h1])
        if gap.max() <= MIN_GAP: continue
        # Terminate at the exact terrain/facade crossing, not below a buried
        # portion of the building. The tiny buried toe seals float32 seams.
        if gap.min() < 0:
            f = gap[0] / (gap[0] - gap[1])
            cross = p + (q - p) * f; height = h0 + (h1 - h0) * f
            if gap[0] < 0: p, h0 = cross, height
            else: q, h1 = cross, height
        # Remove arithmetic residue at zero, which otherwise looks like a cut
        # to the tile exporter but like a non-touch to the canonical topology.
        p,q=np.round([p,q],10)
        low = np.array([p, q]); low[:, 1] = [h0 - BURIAL, h1 - BURIAL]
        if np.linalg.norm(q - p) < 1e-6: continue
        panels.append(dict(top=[p.tolist(), q.tolist()], bottom=low.tolist(),
                           ground=list(ground.refs[source]),groundOffsetM=offset,maxGapM=float(gap.max())))
    unsupported = max(0., 1 - sum(v - u for u, v, *_ in intervals)) * length
    return panels, unsupported


def panel_triangles(panel):
    a, b = np.asarray(panel['top']); c, d = np.asarray(panel['bottom'])
    points = np.array([[a, c, d], [a, d, b]])
    normal = np.cross(c - a, b - a); normal /= np.linalg.norm(normal)
    attrs = np.zeros((2, 3, 8)); attrs[:, :, :3] = points
    attrs[:, :, 3:6] = normal
    # World-aligned metres along the facade and in height, continuous at cuts.
    tangent = (b - a)[[0, 2]]; tangent /= np.linalg.norm(tangent)
    attrs[:, :, 6] = points[:, :, [0, 2]] @ tangent
    attrs[:, :, 7] = points[:, :, 1]
    # Coincident terrain-triangle cuts can produce sub-float32 slivers.
    # Remove only faces that collapse in the actual transport precision.
    packed = points.astype('<f4')
    valid = np.linalg.norm(np.cross(packed[:,1]-packed[:,0],packed[:,2]-packed[:,0]),axis=1)>1e-9
    if not valid.all():
        # At kilometre offsets one Float32 cell can exceed 0.1 mm. A panel
        # whose two ends become the exact same XZ column has no representable
        # face, regardless of its original double-precision width. Keep the
        # narrow-face guard for any other degeneracy; never hide a real wall.
        same_column=np.array_equal(a.astype('<f4')[[0,2]],b.astype('<f4')[[0,2]])
        assert np.linalg.norm((b-a)[[0,2]]) < .0001 or same_column,('Non-numeric foundation degeneracy',panel)
    return attrs[valid]


def collect(root, city, scene):
    owners = ownership(root, city, scene)
    rows = {r['id']: r for r in city['objectLayer']['buildings']}
    triangles = defaultdict(list)
    for chunk in scene['chunks']:
        if chunk['id'] not in owners: continue
        raw = gzip.decompress((root/'canonical/full'/Path(chunk['file']).name).read_bytes())
        v = np.frombuffer(raw[:chunk['vertexBytes']], '<f4').reshape(-1, 8)[:, :3]
        ix = np.frombuffer(raw[chunk['vertexBytes']:], '<u4').reshape(-1, 3)
        ts = v[ix].astype(float); ids = np.asarray(owners[chunk['id']])
        for oid in sorted(set(ids)):
            if eligible(rows[oid]): triangles[oid].append(ts[ids == oid])
    return rows, triangles


def install(root, city, scene):
    assert not city['objectLayer'].get('foundations'), 'Foundations already installed; rebuild from the immutable parent'
    print('FOUNDATION INPUT: finished ground and source facade edges',flush=True)
    ground = SurfaceSampler(root, scene, GROUND_NAMES)
    rows, objects = collect(root, city, scene)
    records = []; faces = []; ranges = []; audit = []
    for index,(oid, ts) in enumerate(sorted(objects.items())):
        if index%250==0:print('FOUNDATION BUILDINGS',index,'/',len(objects),flush=True)
        row = rows[oid]; base = row['placement']['targetBaseM'] - city['originMSK'][2]
        edges = base_edges(np.concatenate(ts), base); panels = []; unsupported = 0.
        for a, b in edges:
            pp, missing = panels_for_edge(a, b, ground)
            panels.extend(pp); unsupported += missing
        panels = [p for p in panels if len(panel_triangles(p))]
        audit.append(dict(id=oid,baseEdges=len(edges),panels=len(panels),unsupportedGroundM=unsupported))
        if not panels: continue
        first = len(faces)
        for p in panels: faces.extend(panel_triangles(p))
        ranges.append(dict(id=oid, first=first, count=len(faces)-first))
        records.append(dict(id=oid,sourceBuildingId=row.get('sourceBuildingId'),baseM=base,
                            panels=panels,maxGapM=max(p['maxGapM'] for p in panels)))
    chunks = []
    if faces:
        idx = len(scene['chunks']); file = f'mesh-{idx:03d}.bin.gz'
        meta = pack(faces, np.full(len(faces), MATERIAL, dtype=np.uint32), root/'canonical/full'/file)
        assert meta['triangles'] == len(faces), 'Collapsed foundation: inspect before publishing'
        scene['chunks'].append(dict(id=idx,name='building_foundation',category='foundation',file=file,
                                    objectGeometry=True,sourceObjectIds=[r['id'] for r in records],
                                    sourceObjectRanges=ranges,**meta))
        scene['instances'].append(dict(mesh=idx,matrix=[1,0,0,0,0,1,0,0,0,0,1,0])); chunks.append(idx)
    stats = dict(checkedObjects=len(rows),eligibleObjects=len(objects),supportedObjects=len(records),
                 unchangedObjects=len(rows)-len(records),triangles=len(faces),
                 maxGapM=max((r['maxGapM'] for r in records), default=0),
                 unsupportedGroundM=sum(r['unsupportedGroundM'] for r in audit))
    layer = dict(policy=POLICY,stats=stats,chunks=chunks,buildings=records,audit=audit)
    city['objectLayer']['foundations'] = layer
    return layer
