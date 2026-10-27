"""Regression: a real animated Sber logo must not move again after a static bake."""
import bpy,sys,json
from pathlib import Path
from mathutils import Matrix,Vector
sys.path.insert(0,str(Path(__file__).resolve().parent))
from gltf_static import bake_static_nodes
source='/Users/niemandx/AI_Modeling/moscow_10x10/source/cache/model_32_sbercity2_a.glb'
bpy.ops.import_scene.gltf(filepath=source)
bpy.context.scene.frame_set(1);bpy.context.view_layer.update()
objects=list(bpy.context.scene.objects);m=Matrix.Translation(Vector((2050,8400,138)))@Matrix.Rotation(.5,4,'Z')
expected={obj.name:[m@obj.matrix_world@v.co for v in obj.data.vertices] for obj in objects if obj.type=='MESH'}
bake_static_nodes(objects,m)
for frame in [1,100,200,1]:
    bpy.context.scene.frame_set(frame);bpy.context.view_layer.update()
    for name,positions in expected.items():
        obj=bpy.data.objects[name]
        error=max((obj.matrix_world@v.co-p).length for v,p in zip(obj.data.vertices,positions))
        assert error<.001,(frame,name,error)
        assert obj.animation_data is None
print('PASS: original Sber GLB remains fixed at frames 1, 100, 200, 1 after baking',flush=True)
