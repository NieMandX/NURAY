"""Render small comparison crops without saving changes to the .blend."""
import bpy, sys, argparse, json
import numpy as np
from pathlib import Path
from mathutils import Vector

parser=argparse.ArgumentParser();parser.add_argument('--view',choices=['park','river','sber','markings'],required=True);parser.add_argument('--output',type=Path,required=True)
args=parser.parse_args(sys.argv[sys.argv.index('--')+1:])
views={
    'park':dict(target=(650,7280,165),camera=(20,6200,1100),scale=1050,radius=900),
    'river':dict(target=(2560,8690,125),camera=(3200,7750,950),scale=1100,radius=900),
    'sber':dict(target=(2050,8430,260),camera=(1500,7750,780),scale=480,radius=420),
    'markings':dict(target=(2260,8620,132),camera=(2260,8620,620),scale=320,radius=300),
}
v=views[args.view];target=Vector(v['target']);radius=v['radius']
sc=bpy.context.scene
for obj in list(sc.objects):
    if obj.type!='MESH' or obj.hide_render:continue
    if all(c.hide_render for c in obj.users_collection):continue
    if any(c.name=='Street_furniture_and_trees' for c in obj.users_collection):
        old=obj.data;xyz=np.empty(len(old.vertices)*3,dtype=np.float32);old.vertices.foreach_get('co',xyz);xyz=xyz.reshape(-1,3)
        keep=(abs(xyz[:,0]-target.x)<radius)&(abs(xyz[:,1]-target.y)<radius)
        if not np.any(keep):obj.hide_render=True;continue
        mesh=bpy.data.meshes.new(old.name+'_review_crop');mesh.from_pydata(xyz[keep].tolist(),[],[])
        for name in ['source_rotation','source_scale']:
            vals=np.empty(len(old.vertices)*3,dtype=np.float32);old.attributes[name].data.foreach_get('vector',vals)
            mesh.attributes.new(name,'FLOAT_VECTOR','POINT').data.foreach_set('vector',vals.reshape(-1,3)[keep].ravel())
        obj.data=mesh
    else:
        bb=[obj.matrix_world@Vector(p) for p in obj.bound_box]
        if max(p.x for p in bb)<target.x-radius or min(p.x for p in bb)>target.x+radius or max(p.y for p in bb)<target.y-radius or min(p.y for p in bb)>target.y+radius:obj.hide_render=True
        elif not obj.get('source_glb') and not obj.data.uv_layers and len(obj.data.polygons)>5000:
            old=obj.data;old.calc_loop_triangles()
            xyz=np.empty(len(old.vertices)*3,dtype=np.float32);old.vertices.foreach_get('co',xyz);xyz=xyz.reshape(-1,3)
            ids=np.empty(len(old.loop_triangles)*3,dtype=np.int32);old.loop_triangles.foreach_get('vertices',ids);ts=xyz[ids.reshape(-1,3)]
            keep=(ts[:,:,0].max(axis=1)>target.x-radius)&(ts[:,:,0].min(axis=1)<target.x+radius)&(ts[:,:,1].max(axis=1)>target.y-radius)&(ts[:,:,1].min(axis=1)<target.y+radius)
            if not np.any(keep):obj.hide_render=True;continue
            mids=np.empty(len(old.loop_triangles),dtype=np.int32);old.loop_triangles.foreach_get('material_index',mids)
            ts=ts[keep];mesh=bpy.data.meshes.new(old.name+'_review_crop');mesh.from_pydata(ts.reshape(-1,3).tolist(),[],np.arange(len(ts)*3).reshape(-1,3).tolist())
            for material in old.materials:mesh.materials.append(material)
            mesh.polygons.foreach_set('material_index',mids[keep]);mesh.update();obj.data=mesh
cam=sc.camera;cam.location=v['camera'];cam.rotation_euler=(target-cam.location).to_track_quat('-Z','Y').to_euler()
if 'ORTHO' not in {e.identifier for e in cam.data.bl_rna.properties['type'].enum_items}:raise RuntimeError('Orthographic camera unavailable')
cam.data.type='ORTHO';cam.data.ortho_scale=v['scale'];cam.data.clip_start=.1;cam.data.clip_end=20000
try:sc.render.engine='CYCLES'
except TypeError:raise RuntimeError('Cycles renderer unavailable')
sc.cycles.samples=16;sc.cycles.use_denoising=True
if 'FIXED' in {e.identifier for e in sc.render.bl_rna.properties['threads_mode'].enum_items}:
    sc.render.threads_mode='FIXED';sc.render.threads=4
sc.render.resolution_x=1100;sc.render.resolution_y=900;sc.render.resolution_percentage=100
if 'PNG' not in {e.identifier for e in sc.render.image_settings.bl_rna.properties['file_format'].enum_items}:raise RuntimeError('PNG unavailable')
sc.render.image_settings.file_format='PNG';sc.render.filepath=str(args.output)
args.output.parent.mkdir(parents=True,exist_ok=True)
print('RENDER REVIEW',args.view,flush=True);bpy.ops.render.render(write_still=True)
print('RENDER SAVED',args.output,flush=True)
