"""Keep raised planting out of source-confirmed railway ground mouths.

An axis ribbon protects the track itself, but not the full width of a bridge
or tunnel approach shared by several tracks. Reserve that width from the
source slab and its confirmed mouth before constructing raised green borders.
"""
import numpy as np
import shapely as sh
from passage_space import ground_approach, APPROACH_LENGTH
from transitions import union

EDGE_CLEARANCE = .002  # Exceeds the maximum accepted 1 mm serialized uncertainty.
EMERGENCE_HEIGHT = .202  # Finished planting is terrain + 0.20 m; 2 mm clearance.
SOURCE_BOUNDARY_TOLERANCE = .00005  # Shared 10 micrometre construction grid.


def green_intrusion(green,reserved):
    """Resolve only the source-grid uncertainty at the reservation boundary.

    Success cannot come from a small total area: a thin interior island is
    still rejected. The 2 mm construction clearance remains much wider than
    this band, and serialized obstruction checks are performed independently.
    """
    overlap=green.intersection(reserved)
    interior=overlap.intersection(reserved.buffer(-SOURCE_BOUNDARY_TOLERANCE))
    return dict(passed=bool(interior.area<1e-10),rawOverlapM2=overlap.area,
                resolvedOverlapM2=interior.area,boundaryToleranceM=SOURCE_BOUNDARY_TOLERANCE)


def low_slab(coordinates, height=EMERGENCE_HEIGHT, precision=1e-5):
    """Clip source triangle-strip height offsets, not a fixed entry length.

    Heights are offsets above the same terrain used for the source slab.
    High spans retain the planting underneath them. Negative tunnel depths
    are bounded separately by their source cut and do not enter this rule.
    """
    xyz=np.asarray(coordinates);polygons=[]
    for i in range(len(xyz)-2):
        ring=xyz[i:i+3]
        for threshold,below in ((height,True),(-EDGE_CLEARANCE,False)):
            if not len(ring):break
            output=[];previous=ring[-1]
            for current in ring:
                a=previous[2]<=threshold if below else previous[2]>=threshold
                b=current[2]<=threshold if below else current[2]>=threshold
                if a!=b:output.append(previous+(current-previous)*((threshold-previous[2])/(current[2]-previous[2])))
                if b:output.append(current)
                previous=current
            ring=np.asarray(output)
        if len(ring)>2:
            polygon=sh.Polygon(ring[:,:2])
            if polygon.area>1e-8:polygons.append(polygon)
    return union(polygons,precision)


def reserve_interfaces(features, interfaces, extent, precision=1e-5):
    wanted={p for r in interfaces for e in r['ends']
            if e['kind']!='railway_ground' for p in e.get('parents',[])}
    slabs={};emergence={}
    for f in features:
        if f['id'] not in wanted:continue
        xyz=np.asarray(f['coordinates']);triangles=[]
        for i in range(len(xyz)-2):
            p=sh.Polygon(xyz[i:i+3,:2])
            if p.area>1e-8:triangles.append(p)
        slabs[f['id']]=union(triangles,precision).intersection(extent)
        emergence[f['id']]=low_slab(xyz,precision=precision)
    reserved=[]
    for r in interfaces:
        if not r.get('atGround') or not any(e['kind']=='railway_ground' for e in r['ends']):continue
        parents=[p for e in r['ends'] if e['kind']!='railway_ground' for p in e['parents']]
        source=union([slabs[p] for p in parents],precision)
        mouth=sh.geometry.shape(r['mouthGeometry'])
        approach=ground_approach(mouth,source,precision)
        inside=source.intersection(mouth.buffer(APPROACH_LENGTH,cap_style='square'))
        low=union([emergence[p] for e in r['ends'] if e['kind']=='roadbed_overpass' for p in e['parents']],precision)
        reserved.append(sh.union_all([approach,inside,low]).buffer(EDGE_CLEARANCE,join_style='mitre'))
    return union(reserved,precision).intersection(extent)


def railway_reserve(city, precision=1e-5):
    from railway_transitions import discover,source_candidates
    from build import z_at
    extent=sh.box(*city['boundsMSK'])
    interfaces=[r for r in city['roadInterfaces'] if any(e['kind']=='railway_ground' for e in r['ends'])]
    # Descent mouths are independently reconstructed from the same source
    # endpoint levels; older inventories contain bridge mouths only.
    candidates=source_candidates(city['features'],extent,precision)
    _,tunnels=discover(candidates,city['features'],extent,precision,z_at,part='roadbed_tunnel_descent')
    interfaces+=tunnels
    return reserve_interfaces(city['features'],interfaces,extent,precision)
