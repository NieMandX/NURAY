"""Source-level connectivity regressions, including the reported real ramp end."""
from pathlib import Path
from collections import defaultdict
import json,sys,numpy as np,shapely as sh
from shapely.affinity import affine_transform
sys.path.insert(0,str(Path(__file__).resolve().parent))
from transitions import shared_interfaces,discover,interface_coverage
from overpasses import build as decks
from build import triangulate,z_at,plane

P=.00001
extent=sh.box(0,0,12,12)
def road(poly,c,part,level,owner):
    return dict(id=owner,kind='road',part=part,tiers=[level],poly=poly,patches=[(poly,np.asarray(c))])

for offset in [0,4]:
    # The same continuous carriageway changes from descent to overpass at x=2.
    source=[road(sh.box(0,4,2,8),[.3,0,offset-.6],'roadbed_tunnel_descent',-2,'descent'),
            road(sh.box(2,4,12,8),[.3,0,offset-.6],'roadbed_overpass',1,'overpass')]
    interfaces=shared_interfaces(source,extent,P,z_at)
    connections,connectors=discover(source,sh.Polygon(),extent,P,z_at,interfaces)
    assert len(interfaces)==1 and len(connections)==2 and not connectors
    assert interfaces[0]['atGround']==(offset==0)
    assert interface_coverage(interfaces,connections,P)['passed']
    assert not interface_coverage(interfaces,connections[:1],P)['passed'], 'Missing direction escaped coverage audit'
    dem=[(extent,np.zeros(3))];groups=defaultdict(list)
    rows=[dict(kind=r['part'],tiers=r['tiers'],owner=r['id'],poly=r['poly'],plane=r['patches'][0][1]) for r in source]
    profiles,_=decks(rows,dem,sh.STRtree([extent]),groups,extent,P,triangulate,z_at,plane,connections)
    profile=profiles[0];assert profile['passed'],profile
    gate=sh.box(1.999,4.05,2.001,7.95)
    assert not sh.geometry.shape(profile['parapetGeometry']).intersects(gate)
    assert profile['raisedConcreteInEntryPassageM2']<.0001
    assert profile['shoulderRiserInEntryPassageM']==0
    # The above-ground connection must not blend the shoulder down to DEM=0.
    for tri in groups[('overpass_shoulder',10)]:
        assert tri[:,2].min()>=offset+.1-1e-5
    # Equal XY boundaries alone are insufficient: preserve separated levels.
    mismatch=[source[0],{**source[1],'patches':[(source[1]['poly'],np.array([.3,0,offset-.59]))]}]
    assert not shared_interfaces(mismatch,extent,P,z_at)
    coincident=[source[0],{**source[1],'poly':source[0]['poly'],'patches':source[0]['patches']}]
    assert not shared_interfaces(coincident,extent,P,z_at), 'Same-side overlap mistaken for continuation'
print('Class-transition regressions passed at zero and nonzero height, in both directions; coverage fails with a missing connection.')

# Part of one ground mouth is an exact contact; the remainder lies just
# inside the ground polygon. Keep one continuous noded concrete cut.
partial_ground=sh.Polygon([(0,4),(2,4),(2,6),(2.1,6),(2.1,8),(0,8)])
partial=[road(partial_ground,[0,0,0],'roadbed_flat',0,'flat'),
         road(sh.box(2,4,12,8),[.3,0,-.6],'roadbed_overpass',1,'ramp')]
interfaces=shared_interfaces(partial,extent,P,z_at)
connections,_=discover(partial,partial_ground,extent,P,z_at,interfaces)
assert len(connections)==1 and abs(connections[0]['mouthWidthM']-4)<P
assert interface_coverage(interfaces,connections,P)['passed']
print('Partial ground-contact regression passed: exact and overlapping fragments retain one complete mouth.')

fixture=json.loads((Path(__file__).parent/'fixtures/overpass-descent-interface.json').read_text())
for angle,offset in [(0,[0,0]),(.73,[121,-44])]:
    c,s=np.cos(angle),np.sin(angle);matrix=np.array([[c,-s],[s,c]])
    transform=[c,-s,s,c,*offset]
    candidates=[]
    for row in fixture['roads']:
        patches=[]
        for patch in row['patches']:
            poly=sh.geometry.shape(patch['geometry']);height=np.array(patch['plane'])
            normal=matrix@height[:2];new_height=np.r_[normal,height[2]-np.dot(normal,offset)]
            patches.append((affine_transform(poly,transform),new_height))
        candidates.append(dict(id=row['id'],kind='road',part=row['part'],tiers=row['tiers'],
            poly=sh.union_all([p for p,c in patches],grid_size=P),patches=patches))
    ext=affine_transform(sh.box(*fixture['bounds']),transform)
    interfaces=shared_interfaces(candidates,ext,P,z_at)
    connections,_=discover(candidates,sh.Polygon(),ext,P,z_at,interfaces)
    assert len(interfaces)==1 and len(connections)==2,(angle,interfaces,connections)
    assert abs(interfaces[0]['mouthWidthM']-6.999908455)<.0001
    assert interfaces[0]['maxHeightMismatchM']<.00001
    assert interface_coverage(interfaces,connections,P)['passed']
print('Real 2GIS regression passed: 7 m bent shared edge, split source patches, rotation and translation; no location-specific patch.')

# Validate serialized triangles as 3D obstacles. An end face below the road
# and an unrelated high bridge remain legal; a 10 cm riser does not.
sys.path.insert(0,str(Path(__file__).parent/'tiling'))
from interface_validation import check_interfaces
interface=dict(id='synthetic',ends=[dict(kind='roadbed_overpass'),dict(kind='roadbed_tunnel_descent')],mouthWidthM=4)
planes=np.array([[1,0,0,.001],[-1,0,0,.001],[0,0,1,-.05],[0,0,-1,3.95],
                 [0,1,0,-.02],[0,-1,0,.75]])
volumes=[(interface,[(sh.box(-.001,.05,.001,3.95),planes)])]
wall=np.array([[[0,0,0],[0,.1,4],[0,.1,0]],[[0,0,0],[0,0,4],[0,.1,4]]])
assert not check_interfaces(volumes,[('overpass_riser',wall)])['passed']
assert not check_interfaces(volumes,[('inferred-walls',wall)])['passed']
assert check_interfaces(volumes,[('overpass_side',wall-[0,1,0])])['passed']
assert check_interfaces(volumes,[('parapet_side',wall+[0,5,0])])['passed']
print('Serialized passage-volume regressions passed: detects 10 cm concrete/wall barrier, accepts buried end faces and separated overhead geometry.')

# One broad zero-height end includes two carriageways and a two-metre median.
# Full-edge proximity rejects it; both exact source contacts must still open.
from transitions import discover,shared_interfaces,interface_coverage
split_roads=[]
for rid,poly,kind,c in [('bridge',sh.box(0,0,10,6),'roadbed_overpass',np.array([.2,0,0])),
                       ('south',sh.box(-5,0,0,2),'roadbed_flat',np.zeros(3)),
                       ('north',sh.box(-5,4,0,6),'roadbed_flat',np.zeros(3))]:
 split_roads.append(dict(id=rid,kind='road',part=kind,tiers=[1] if kind=='roadbed_overpass' else [0],poly=poly,patches=[(poly,c)]))
split_extent=sh.box(-10,-5,15,11)
split_interfaces=shared_interfaces(split_roads,split_extent,1e-5,z_at)
split_connections,_=discover(split_roads,sh.union_all([r['poly'] for r in split_roads[1:]]),split_extent,1e-5,z_at,split_interfaces)
assert len(split_connections)==2 and interface_coverage(split_interfaces,split_connections,1e-5)['passed']
assert all(abs(c['mouthWidthM']-2)<1e-7 for c in split_connections)
print('Divided-entry regression passed: two exact source mouths open independently while the median stays separate.')
