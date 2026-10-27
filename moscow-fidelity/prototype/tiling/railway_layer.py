"""Generate only the railway overlay; existing terrain and structures are inputs."""
from collections import defaultdict
import numpy as np
import shapely as sh
from railway_support import Floors, floor_group, source_tiers, POLICY
from railway_geometry import densify, network, ribbon
from object_geometry import clip_triangles


def water_clearance(chunks,city):
    """Check the emitted ground ribbons, including the complete cross-section."""
    water=[r for r in city['surfaces'] if r['kind']=='water']
    if not water:return dict(checkedVertices=0,minimumClearanceM=None)
    tree=sh.STRtree([sh.geometry.shape(r['geometry']) for r in water])
    planes=np.asarray([r['heightPlane'] for r in water]);origin=np.asarray(city['originMSK'])
    ground={f['id'] for f in city['features'] if floor_group(f)=='ground'}
    minimum=float('inf');count=0
    for source,tris,_ in chunks:
        if source not in ground or not len(tris):continue
        p=tris[:,:,:3].reshape(-1,3);xy=p[:,[0,2]]*[1,-1]+origin[:2]
        ids,wi=tree.query(sh.points(xy),predicate='covered_by')
        if not len(ids):continue
        height=np.sum(planes[wi]*np.c_[xy[ids],np.ones(len(ids))],axis=1)
        clearance=p[ids,1]+origin[2]-height
        if float(clearance.min())<.02-1e-5:
            raise ValueError(('Ground railway intersects source water',source,float(clearance.min())))
        minimum=min(minimum,float(clearance.min()));count+=len(ids)
    return dict(checkedVertices=count,minimumClearanceM=minimum if count else None)


def select_input(metadata, features, surfaces):
    """Read existing floor cells near rails; never regenerate the landscape."""
    rails=[f for f in features if f['layer'] in ('Railroad_line','Railroad_tunnel_line')
           and f['geometryType']=='polyline']
    polys=np.array([sh.LineString(np.asarray(f['coordinates'])[:,:2]).buffer(11) for f in rails],object)
    tree=sh.STRtree(polys); occupied=set()
    for rail in rails:
        for x,y in densify(np.asarray(rail['coordinates'])[:,:2],step=5):
            for a in range(int(np.floor((x-15)/20)),int(np.floor((x+15)/20))+1):
                for b in range(int(np.floor((y-15)/20)),int(np.floor((y+15)/20))+1):occupied.add((a,b))
    rows=[]
    for s in surfaces:
        if s['kind'] not in {'land','roadbed_flat','roadbed_overpass','roadbed_tunnel_descent','roadbed_tunnel','water'}:continue
        rings=s['geometry']['coordinates']
        ring=rings[0] if s['geometry']['type']=='Polygon' else [q for poly in rings for q in poly[0]]
        xs=[p[0] for p in ring];ys=[p[1] for p in ring]
        a0=int(min(xs)//20);a1=int(max(xs)//20);b0=int(min(ys)//20);b1=int(max(ys)//20)
        if (a1-a0+1)*(b1-b0+1)<100 and not any((a,b) in occupied for a in range(a0,a1+1) for b in range(b0,b1+1)):continue
        if len(tree.query(sh.geometry.shape(s['geometry']),predicate='intersects')):rows.append(s)
    return dict(metadata,features=rails,surfaces=rows)


def generate(city, materials):
    sources = [f for f in city['features'] if f['layer'] in ('Railroad_line','Railroad_tunnel_line')
               and f['geometryType'] == 'polyline']
    floors = Floors(city); records = []
    for f in sources:
        xy = densify(np.asarray(f['coordinates'])[:, :2])
        group = floor_group(f); z = floors.sample(xy, group, f['id'])
        records.append(dict(id=f['id'], points=np.column_stack([xy,z]),
                            floorGroup=group, tiers=source_tiers(f)))
    edges, stats = network(records)
    owners = {}
    for e in sorted(edges, key=lambda e:e['id']):
        for n in e['nodes']:owners.setdefault(n,e)
    def heights(xy, edge, centre_z):
        centre = xy.mean(0); owner = edge
        for end, index in ((0,0),(-1,1)):
            if np.linalg.norm(centre-edge['points'][end,:2]) < 1e-5:
                owner = owners[edge['nodes'][index]];break
        z = floors.sample(xy, owner['floorGroup'], owner['id'])
        c = floors.sample([centre], owner['floorGroup'], owner['id'])[0]
        return z + centre_z - c
    origin = np.asarray(city['originMSK']); x0,y0,x1,y1 = city['boundsMSK']
    clip = [x0-origin[0],origin[1]-y1,x1-origin[0],origin[1]-y0]
    joins = defaultdict(list); output = []; rows = []
    for index,edge in enumerate(edges):
        if len(edges)>50 and index%50==0:
            print('RAILWAY RIBBONS',index,'/',len(edges),flush=True)
        tris, mats, rings = ribbon(edge, heights, materials['bed'], materials['rail'],
                                   origin, bounds=city['boundsMSK'])
        for end,index in ((0,0),(-1,1)):
            joins[edge['nodes'][index]].append(dict(source=edge['id'],vertices=rings[end,:,:3].tolist(),uv=rings[end,:,6:8].tolist()))
        tris,mats = clip_triangles(tris,mats,clip)
        output.append((edge['id'],tris,mats))
        rows.append(dict(source=edge['id'],component=edge['component'],nodes=edge['nodes'],
                         stationStartM=float(edge['station'][0]),stationEndM=float(edge['station'][-1]),
                         physicalLengthM=float(np.linalg.norm(np.diff(edge['points'],axis=0),axis=1).sum()),
                         floorGroup=edge['floorGroup'],sourceTiers=list(edge['tiers']),
                         supportOwners=sorted(floors.owners[edge['id']])))
    joint_max=0.;uv_max=0.;tested=0
    for node,items in joins.items():
        if len(items)!=2:continue
        a,b=items;pa=np.asarray(a['vertices']);pb=np.asarray(b['vertices']);ua=np.asarray(a['uv']);ub=np.asarray(b['uv'])
        if np.linalg.norm(pa[0]-pb[-1])<np.linalg.norm(pa[0]-pb[0]):pb=pb[::-1];ub=ub[::-1]
        gap=float(np.linalg.norm(pa-pb,axis=1).max());delta=ua[:,1]-ub[:,1];phase=float(np.abs(delta-np.rint(delta)).max())
        joint_max=max(joint_max,gap);uv_max=max(uv_max,phase);tested+=1
        assert gap<1e-5 and phase<1e-8,(node,gap,phase)
    clearance=water_clearance(output,city)
    stats.update(canonicalTriangles=sum(len(t) for _,t,_ in output),
        sourceLengthM=sum(r['physicalLengthM'] for r in rows),continuousSourceJoints=tested,
        maxSourceJointGapM=joint_max,maxSourceJointPhaseError=uv_max,
        nearestFloorSamples=len(floors.fallbacks),
        maxNearestFloorDistanceM=max((r['distanceM'] for r in floors.fallbacks),default=0),
        outsideRegionMiters=sum(e.get('outsideRegionMiters',0) for e in edges),
        inferredWaterCrossings=sum(len(p) for p in floors.water_profiles.values()),
        waterCrossingSamples=floors.water_samples,
        waterClearance=clearance,
        tierBoundSamples=floors.samples)
    return output,dict(stats=stats,edges=rows,sourceJoints=dict(joins),heightBinding=POLICY,
        waterCrossings=[{k:v for k,v in p.items() if k not in ('axis','domain')} for profiles in floors.water_profiles.values() for p in profiles])
