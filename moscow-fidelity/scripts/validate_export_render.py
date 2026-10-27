"""Validate the saved city, export the 5 km viewer asset, and render review crops."""
import bpy,sys,json,runpy,time
from pathlib import Path
from mathutils import Vector

WORK=Path('/Users/niemandx/Documents/ChatGPT/IDEAS/moscow-fidelity')
SCRIPTS=WORK/'scripts'
MODEL=WORK/'web-preview/assets/moscow-city-5km-v2'
assert bpy.context.scene.get('fidelity_repair_version')==1
logo=bpy.data.objects['model_32_sbercity2_a_sbercity2_logo']
tower=bpy.data.objects['model_32_sbercity2_a_sbercity2']
def bbox(obj):
    points=[obj.matrix_world@Vector(v) for v in obj.bound_box]
    return [[min(p[k] for p in points),max(p[k] for p in points)] for k in range(3)]
lb,tb=bbox(logo),bbox(tower)
assert abs(lb[2][0]-tb[2][1])<.005,(lb,tb)
for frame in [1,100,200,1]:
    bpy.context.scene.frame_set(frame);bpy.context.view_layer.update()
    assert max(abs(a-b) for aa,bb in zip(lb,bbox(logo)) for a,b in zip(aa,bb))<.001
paint={m.get('fidelity_paint'):list(m.diffuse_color) for m in bpy.data.materials if m.get('fidelity_paint')}
assert all(abs(a-b)<1e-5 for a,b in zip(paint['white'],[.96,.96,.96,1]))
assert all(abs(a-b)<1e-5 for a,b in zip(paint['yellow'],[1,.93,.045,1]))
assert bpy.data.objects['Shore'].hide_render
path=bpy.data.objects['Pedestrian_paths_source_geometry']
assert abs(path.get('terrain_display_offset',0)-.19)<1e-6
path_report=json.loads(path['fidelity_path_report'])
assert path_report['missing_terrain_vertices']==0,path_report
validation={'source':bpy.data.filepath,'sber_logo_bounds':lb,'sber_roof_m':tb[2][1],'animation_frames_checked':[1,100,200,1],'paint_linear_rgba':paint,'paths':path_report}
(WORK/'output/saved-scene-validation.json').write_text(json.dumps(validation,ensure_ascii=False,indent=2))
print('SAVED SCENE VALIDATION PASSED',json.dumps(validation),flush=True)

# Open the corrected file on the main comparison area in the user's next Blender session.
target=Vector((650,7280,165));eye=Vector((20,6200,1100));rotation=(target-eye).to_track_quat('-Z','Y')
for screen in bpy.data.screens:
    for area in screen.areas:
        if area.type=='VIEW_3D':
            region=area.spaces.active.region_3d;region.view_location=target;region.view_rotation=rotation;region.view_distance=1450
bpy.ops.wm.save_as_mainfile(filepath=bpy.data.filepath,compress=True)

exporter=Path('/Users/niemandx/Documents/ChatGPT/IDEAS/light-study/scripts/export-moscow.py')
sys.argv=['blender','--','--extent','5000','--output',str(MODEL),'--require-fidelity']
runpy.run_path(str(exporter),run_name='__main__')
print('VIEWER EXPORT READY',MODEL,flush=True)

original={o:(o.data,o.hide_render) for o in bpy.context.scene.objects if o.type=='MESH'}
for view in ['park','river','sber','markings']:
    for obj,(mesh,hidden) in original.items():
        replaced=obj.data;obj.data=mesh;obj.hide_render=hidden
        if replaced!=mesh and replaced.users==0:bpy.data.meshes.remove(replaced)
    bpy.context.view_layer.update()
    sys.argv=['blender','--','--view',view,'--output',str(WORK/'output'/(view+'-after.png'))]
    runpy.run_path(str(SCRIPTS/'render_review.py'),run_name='__main__')
print('ALL REVIEWS COMPLETE',flush=True)
