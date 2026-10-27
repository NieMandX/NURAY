"""Regression: clipping preserves holes, surface elevation, face materials and tiers."""
import bpy,sys
from pathlib import Path
import numpy as np
sys.path.insert(0,'/private/tmp/nuray-fidelity-deps311')
sys.path.insert(0,str(Path(__file__).resolve().parent))
from shapely.geometry import Polygon
from repair_blender import cut_mask,triangles,array

xy=[(0,0),(10,0),(10,10),(0,10)]
mesh=bpy.data.meshes.new('sloping_reference_surface')
mesh.from_pydata([(x,y,2*x+3*y+7) for x,y in xy],[],[(0,1,2),(0,2,3)])
for name in ['side_0','side_1']:mesh.materials.append(bpy.data.materials.new(name))
mesh.polygons[1].material_index=1
mesh.attributes.new('2gis_tier','INT','FACE').data.foreach_set('value',[0,-1])
mesh.attributes.new('source_object_index','INT','FACE').data.foreach_set('value',[10,20])
obj=bpy.data.objects.new('cut_regression',mesh);bpy.context.scene.collection.objects.link(obj)
mask=Polygon([(2,2),(8,2),(8,8),(2,8)],holes=[[(4,4),(6,4),(6,6),(4,6)]])
report=[];cut_mask(obj,mask,report)
ts,_=triangles(obj)
area=np.abs(np.cross(ts[:,1]-ts[:,0],ts[:,2]-ts[:,0])[:,2]).sum()/2
assert abs(area-68)<1e-5,area
assert np.max(np.abs(ts[:,:,2]-(2*ts[:,:,0]+3*ts[:,:,1]+7)))<5e-5
assert set(array(obj.data.polygons,'material_index',1,np.int32).ravel())=={0,1}
assert set(array(obj.data.attributes['2gis_tier'].data,'value',1,np.int32).ravel())=={0,-1}
assert set(array(obj.data.attributes['source_object_index'].data,'value',1,np.int32).ravel())=={10,20}
for tri in ts:
    assert Polygon(tri[:,:2]).intersection(mask).area<1e-6
print('PASS: 68 m2 retained, hole preserved, sloping plane/materials/tiers intact',flush=True)
