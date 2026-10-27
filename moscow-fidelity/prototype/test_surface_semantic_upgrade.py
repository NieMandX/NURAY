import numpy as np
import shapely as sh
from collections import defaultdict
import build as b
from surface_semantic_upgrade import upgrade

b.surfaces=[];b.groups=defaultdict(list);b.shading_flags=defaultdict(list)
b.relationships=[];b.unresolved=[];b.source_owners={};b._surface_id_counter=0
coeff=np.array([.07,-.03,2.])
def cell(poly,owner,material,kind='land'):
    b.add_surface(sh.set_precision(poly,b.GRID),coeff,owner,material,kind,[0])
cell(sh.box(0,0,4,2),'lawn',2)
cell(sh.box(0,2,4,3),'walk',7)
cell(sh.box(0,3,4,3.15),'lawn',9,'curb_top')
for s in b.surfaces:
    if s['kind']=='curb_top':b.groups[('curb_bottom',9)].extend(t[::-1] for t in b.triangulate(s['poly'],coeff-[0,0,.1]))
cell(sh.box(0,-1,4,0),'road',0,'roadbed_flat')
cell(sh.box(0,-2,4,-1),'water',13,'water')
before={k:np.asarray(v).copy() for k,v in b.groups.items()}
footprint=sh.union_all([s['poly'] for s in b.surfaces])
old=[dict(id='lawn',kind='land',rank=40,poly=sh.box(0,0,4,3.15)),
     dict(id='walk',kind='land',rank=60,poly=sh.box(0,2,4,3))]
new=[dict(id='beach',kind='land',rank=50,poly=sh.set_precision(sh.box(1,-2,3,3.15),b.GRID),material=24)]
r=upgrade(b,old,new)
assert r['affectedCells']==2 and r['coverageExactlyPreserved']
assert sh.union_all([s['poly'] for s in b.surfaces]).equals(footprint)
assert abs(sum(s['poly'].area for s in b.surfaces if s['owner']=='beach')-4.3)<1e-9
assert all(s['material']==(9 if s['kind']=='curb_top' else 24) for s in b.surfaces if s['owner']=='beach')
assert all(np.array_equal(s['plane'],coeff) for s in b.surfaces)
for kind,mat in [('roadbed_flat',0),('water',13)]:assert np.array_equal(before[kind,mat],np.asarray(b.groups[kind,mat]))
assert all(s['owner']=='walk' for s in b.surfaces if s['poly'].intersects(sh.Point(2,2.5)))
def area(faces):
    a=np.asarray(faces);return np.linalg.norm(np.cross(a[:,1]-a[:,0],a[:,2]-a[:,0]),axis=1).sum()/2 if len(a) else 0
assert abs(sum(area(v) for v in before.values())-sum(area(v) for v in b.groups.values()))<1e-9
assert len({s['id'] for s in b.surfaces})==len(b.surfaces)
assert all(len(b.shading_flags.get(k,[])) in (0,len(v)) for k,v in b.groups.items())
print('Passed: new semantic contours preserve slopes, complete coverage and emitted area, retain higher-priority paths/curbs, and never modify roads or water.')
