"""Import both prototype GLBs into a new Blender comparison file only."""
from pathlib import Path
import bpy,json
from mathutils import Vector

root=Path(__file__).resolve().parents[1]
assets=root/'web-preview/prototype/assets'
validation=json.loads((assets/'validation.json').read_text())
serialized=json.loads((assets/'serialized-validation.json').read_text())
latest=json.loads((assets/'after/scene.json').read_text())
assert validation['passed'] and serialized['passed'], 'Geometry validation must pass before saving Blender output'
assert serialized['after']['triangles']==latest['stats']['uniqueTriangles'], 'Serialized validation must match the current export'
bpy.ops.wm.read_factory_settings(use_empty=True)
names={'before':'01 · Исходная','terrain':'02 · По рельефу','smooth':'03 · Плавные дороги','structure':'04 · Бордюры и эстакады','after':'05 · Плечи +10 см'}
for version in names:
    collection=bpy.data.collections.new(names[version])
    bpy.context.scene.collection.children.link(collection)
    bpy.ops.import_scene.gltf(filepath=str(assets/version/'model.glb'))
    for obj in list(bpy.context.selected_objects):
        for old in list(obj.users_collection):old.objects.unlink(obj)
        collection.objects.link(obj)
    if version!='after':collection.hide_render=True;collection.hide_viewport=True
scene=bpy.context.scene;scene.unit_settings.system='METRIC'
scene['urban_model']=str(assets/'urban-model.json')
scene['validation']=str(assets/'validation.json')
scene['experiment']='350 × 300 m; smooth roads; non-road ground raised 0.10 m; 0.15 m wide curbs; concrete overpasses: 1 m side overhang, shoulders +0.10 m above asphalt, underside -1 m; parapet tops +0.70 m above asphalt / 0.20 m wide'
scene['origin_msk_east_north_up']=[2125.,8070.,145.]
scene['shoulder_rule']='Concrete shoulders follow the source asphalt edge at +0.10 m; inward risers close the step; ground-connected ends share the ground height datum. Parapet top remains +0.70 m above asphalt.'
scene['grade_connection_rule']='Ground curb stops at source-confirmed grade mouths; original road boundary determines outside before extension; a continuously joined mouth cut prevents transverse caps and detached concrete islands; concrete shoulders continue lateral boundaries; raised land excludes intersecting ramp slab, remains under clear high spans.'
scene['limitations']='Prototype: no buildings/trees; inferred thin descent walls; user-defined curb/deck/parapet dimensions; unresolved paint retained at previous height.'
camera=bpy.data.cameras.new('Общий план');obj=bpy.data.objects.new('Общий план',camera);scene.collection.objects.link(obj)
obj.location=(80,-320,370);obj.rotation_euler=(Vector((0,0,0))-obj.location).to_track_quat('-Z','Y').to_euler();camera.lens=40;camera.clip_end=2000;scene.camera=obj
light=bpy.data.lights.new('Солнце','SUN');light.energy=3;sun=bpy.data.objects.new('Солнце',light);scene.collection.objects.link(sun);sun.rotation_euler=(.4,-.5,-.4)
scene.world=bpy.data.worlds.new('Небо');scene.world.color=(.3,.3,.3)
for screen in bpy.data.screens:
    for area in screen.areas:
        if area.type=='VIEW_3D':
            area.spaces.active.region_3d.view_distance=430
            area.spaces.active.region_3d.view_location=(0,0,0)
            area.spaces.active.clip_end=3000
            area.spaces.active.shading.color_type='MATERIAL'
output=root/'output/Kutuzovskaya_raised_shoulders.blend'
bpy.ops.wm.save_as_mainfile(filepath=str(output))
counts={c.name:sum(len(o.data.polygons) for o in c.objects if o.type=='MESH') for c in bpy.data.collections if c.name.startswith(('01','02','03','04','05'))}
expected={v:json.loads((assets/v/'scene.json').read_text())['stats']['uniqueTriangles'] for v in names}
assert all(counts[names[v]]==expected[v] for v in names)
print('BLENDER VERIFIED',json.dumps(counts,ensure_ascii=False),'SAVED',str(output),flush=True)
