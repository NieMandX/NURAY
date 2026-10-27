"""Source-style and pedestrian connection regressions, independent fixtures."""
from pathlib import Path
from collections import defaultdict
import numpy as np
import shapely as sh
from source_styles import zigzag,load,pedestrian_profile,PEDESTRIAN_MATERIAL
from pedestrian import discover
from overpasses import build
from build import triangulate,z_at,plane
from tiling.interface_validation import passage_volumes,check_interfaces

line=zigzag([[0,0],[8,0]],3.5,2)
assert np.allclose(line.coords,[[0,0],[2,2],[4,0],[6,2],[8,0]])
reverse=zigzag([[8,0],[0,0]],3.5,2)
assert np.allclose(reverse.coords,[[8,0],[6,-2],[4,0],[2,-2],[0,0]])
assert zigzag([[0,0],[1,0]],3.5,2).is_empty
assert zigzag([],3.5,2).is_empty and zigzag([[0,0]],3.5,2).is_empty
assert np.allclose(zigzag([[0,0],[0,0],[8,0]],3.5,2).coords,line.coords)
area=line.buffer(.075,join_style='mitre')
left=area.intersection(sh.box(-1,-3,3.1,3));right=area.intersection(sh.box(3.1,-3,10,3))
assert sh.union_all([left,right]).symmetric_difference(area).area<1e-10
# Restarting the source modifier at a storage cut would change tooth spacing.
wrong=zigzag([[0,0],[3.1,0]],3.5,2).buffer(.075).union(zigzag([[3.1,0],[8,0]],3.5,2).buffer(.075))
assert wrong.symmetric_difference(area).area>.1

style=load(Path('/Users/niemandx/AI_Modeling/moscow_10x10/source/style_flat.json'))
profile=pedestrian_profile(style)
assert profile['material']==PEDESTRIAN_MATERIAL and profile['parapetWidth']==.3
extent=sh.box(-4,-4,24,8)
pieces=[(sh.box(0,0,5,3),np.array([.4,0,0])),
        (sh.box(5,0,15,3),np.array([0,0,2])),
        (sh.box(15,0,20,3),np.array([-.4,0,8]))]
candidates=[dict(id=f'ped:{i}',transport='pedestrian',part='roadbed_overpass',kind='road',tiers=[1],
                 poly=p,patches=[(p,c)]) for i,(p,c) in enumerate(pieces)]
def axis(rid,layer,coords,begin,end,**props):
    return dict(id=rid,layer=layer,geometryType='polyline',coordinates=coords,properties=dict(db_segment_level_begin=begin,db_segment_level_end=end,**props))
records=[axis('bridge','Pedestrian_road_overground',[[0,1.5,0],[20,1.5,0]],0,0,db_tiers=[1]),
         axis('west','Pedestrian_road',[[-2,1.5,0],[0,1.5,0]],0,0),
         axis('east','Pedestrian_road',[[20,1.5,0],[22,1.5,0]],0,0)]
cons,interfaces=discover(candidates,records,sh.Polygon(),extent,1e-5,z_at)
assert len(cons)==2,cons
# Height, topology and crop boundaries independently prevent false openings.
for invalid in [records[:1], [dict(r,properties={**r['properties'],'db_segment_level_begin':1,'db_segment_level_end':1}) for r in records]]:
    assert not discover(candidates,invalid,sh.Polygon(),extent,1e-5,z_at)[0]
cut_records=[dict(r,properties={**r['properties'],'beginningIsCut':1,'endingIsCut':1}) for r in records]
assert len(discover(candidates,cut_records,sh.Polygon(),extent,1e-5,z_at)[0])==2
assert not discover(candidates,records,sh.Polygon(),sh.box(0,-4,20,8),1e-5,z_at)[0]
crossfall=np.array([0,.02,0]);dem=[(extent,crossfall)]
rows=[dict(poly=p,plane=c+crossfall+[0,0,.1],owner=f'ped:{i}',kind='roadbed_overpass',tiers=[1],
           transport='pedestrian',profile=profile) for i,(p,c) in enumerate(pieces)]
groups=defaultdict(list)
profiles,_=build(rows,dem,sh.STRtree([extent]),groups,extent,1e-5,triangulate,z_at,plane,cons)
assert profiles[0]['passed'],profiles
assert profiles[0]['openInterfaceSegments']==2
city=dict(originMSK=[0,0,0],roadInterfaces=interfaces,surfaces=[dict(kind=r['kind'],tiers=r['tiers'],owner=r['owner'],geometry=sh.geometry.mapping(r['poly']),heightPlane=r['plane'].tolist()) for r in rows])
# Inspect actual 3D faces, not just 'open' flags: no transverse rails/walls.
meshes=[(kind,np.asarray(ts)[:,:,[0,2,1]]*np.array([1,1,-1])) for (kind,mat),ts in groups.items() if ts]
check=check_interfaces(passage_volumes(city),meshes)
assert check['passed'],check
# A deliberately reintroduced cap must fail the same checker.
cap=np.array([[[0,1.6,0],[0,1.66,-3],[0,.16,-3]]])
assert not check_interfaces(passage_volumes(city),meshes+[('parapet_side',cap)])['passed']
print('Passed: one-sided source zigzag, direction, short/duplicate lines, transport-cut invariance; two open pedestrian landings; reject missing/wrong-level/region-cut connections; source cut flags alone do not veto a proven connection; actual cap obstruction detection.')

from source_styles import check_marking_support
import shapely as sh
road=sh.box(0,0,20,10);extent=sh.box(-10,-10,30,20)
quantized={'source':{'coordinateStepM':.021}}
near=check_marking_support(sh.LineString([(1,-.009),(19,-.009)]),road,extent,quantized,1e-5)
assert near['passed'] and near['centrelineOutsideRoadM']>17
wrong=check_marking_support(sh.LineString([(1,-2),(19,-2)]),road,extent,quantized,1e-5)
assert not wrong['passed'] and wrong['centrelineBeyondSourcePrecisionM']>17
assert not check_marking_support(sh.LineString([(1,-.009),(19,-.009)]),road,extent,{},1e-5)['passed']
print('Passed: recorded source quantization bounds distinguish millimetre rounding from wrong-side zigzags; missing precision metadata does not grant tolerance.')
