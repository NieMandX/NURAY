import numpy as np
import shapely as sh
from partition_refinement import clip_triangle
from build import triangulate,plane

cut=sh.box(4,-1,6,11)
horizontal=np.array([[0.,0,0],[10,0,0],[0,10,0]])
faces=clip_triangle(horizontal,cut,triangulate,plane)
assert sh.union_all([sh.Polygon(t[:,:2]) for t in faces]).symmetric_difference(sh.Polygon(horizontal[:,:2]).difference(cut)).area<1e-9
vertical=np.array([[0.,0,0],[10,0,0],[10,0,1]])
faces=clip_triangle(vertical,cut,triangulate,plane)
for t in faces:
 assert not (t[:,0].min()<4 and t[:,0].max()>6)
 assert np.cross(t[1]-t[0],t[2]-t[0])[1]<0
assert abs(sum(np.linalg.norm(np.cross(t[1]-t[0],t[2]-t[0]))/2 for t in faces)-4)<1e-9
print('Passed: horizontal and vertical surfaces are clipped to the same seam while preserving winding.')

# Exercise the full repartition, including the newly exposed outer curb top.
from collections import defaultdict
import build as b
from curbs import band,solid_sides
from partition_refinement import refine
from coverage import physical_land_boundary,uncovered_length
b.B=[-2.,-2.,22.,12.];b.EXTENT=sh.box(*b.B);b.GRID=1e-5
b.records=[];b.surfaces=[];b.groups=defaultdict(list);b.shading_flags=defaultdict(list);b.source_owners={};b.relationships=[];b.slit_repairs=[]
b.dem=[(b.EXTENT,np.zeros(3))];b.demtree=sh.STRtree([b.EXTENT]);b.transition_cut=sh.Polygon()
b.grade_connections=[]
rows=[dict(id=str(i),kind='road',layer='Main_Roadbed',part='roadbed_flat',tiers=[0],material=0,rank=100,poly=p) for i,p in enumerate([sh.box(0,0,10,10),sh.box(10.04,0,20,10)])]
roads=sh.union_all([r['poly'] for r in rows]);b.curb_band=band(roads,sh.Polygon(),b.EXTENT,b.GRID)
land=b.EXTENT.difference(roads);rows.append(dict(id='land',kind='land',layer='Administrative_quarter',part='roadbed_flat',tiers=[0],material=1,rank=0,poly=land))
b.add_surface(roads,np.zeros(3),'asphalt',0,'roadbed_flat',[0])
b.add_surface(land.difference(b.curb_band),np.array([0,0,.1]),'land',1,'land',[0])
b.add_surface(b.curb_band,np.array([0,0,.1]),'land',9,'curb_top',[0])
b.curb_front,_=solid_sides(b.curb_band,roads,b.dem,b.demtree,b.groups,b.z_at,b.EXTENT)
b.curb_report={};b.road_seam_report=dict(repairs=0,repairedAreaM2=0)
fixed=refine(b,sh.Polygon(),roads,rows)
assert fixed.covers(sh.Point(10.02,5))
assert len({s['id'] for s in b.surfaces})==len(b.surfaces)
gate=sh.box(10.001,.01,10.039,9.99)
for s in b.surfaces:
 if s['kind'] in ('land','curb_top'):assert s['poly'].intersection(gate).area<1e-9
for (kind,material),faces in b.groups.items():
 if kind not in ('land','curb_top','curb_front','curb_back'):continue
 for t in faces:
  assert sh.Polygon(t[:,:2]).intersection(gate).area<1e-9
expected=physical_land_boundary(fixed,sh.Polygon(),b.EXTENT,.00005)
assert uncovered_length(expected,b.curb_front,.00005)<.001
print('Passed: full seam repartition updates asphalt, land, curb tops/sides and unique surface identities.')

# A later structural rebuild removes additional ground after the first pass
# has deleted surface records. IDs must not be recycled from the list length.
new_cut=sh.box(-1,2,0,4);b.transition_cut=new_cut
refine(b,sh.Polygon(),fixed,rows,extra_ground_cut=new_cut)
b.add_surface(sh.box(-1.8,-1.8,-1.7,-1.7),np.array([0,0,.1]),'restored',1,'land',[0])
assert len({s['id'] for s in b.surfaces})==len(b.surfaces)
assert all(s['poly'].intersection(new_cut).area<1e-9 for s in b.surfaces if s['kind'] in ('land','curb_top'))
for key,flags in b.shading_flags.items():assert len(flags)==len(b.groups[key]),key
print('Passed: structural ground cuts preserve the shared partition and monotonic surface IDs across repeated rebuilds.')

# Reapplying an already empty ground cut is a true no-op: every retained face,
# surface identity and shading flag remains byte-for-byte unchanged.
before_faces={k:np.asarray(v).tobytes() for k,v in b.groups.items()}
before_ids=[s['id'] for s in b.surfaces]
before_flags={k:list(v) for k,v in b.shading_flags.items()}
refine(b,sh.Polygon(),fixed,rows,extra_ground_cut=sh.box(-.9,2.1,-.8,2.2))
assert before_faces=={k:np.asarray(v).tobytes() for k,v in b.groups.items()}
assert before_ids==[s['id'] for s in b.surfaces]
assert before_flags==dict(b.shading_flags)
print('Passed: a ground delta without affected cells preserves every existing face and surface ID.')
