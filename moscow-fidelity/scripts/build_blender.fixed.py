import bpy,bmesh,json,gzip,sys,math,gc
gc.disable()  # Large acyclic JSON arrays; reference counting still releases temporaries.
from pathlib import Path
from mathutils import Matrix,Vector,Euler
sys.path.insert(0,str(Path(__file__).resolve().parent))
OUT=Path(sys.argv[sys.argv.index('--')+1]);data=json.load(gzip.open(OUT/('scene_terrain.json.gz' if (OUT/'scene_terrain.json.gz').exists() else 'scene_with_icons.json.gz'),'rt'));plan=data['plan'];B=plan['extent_msk_east_north'];cx,cy=plan['center_msk_east_north'];size=plan['size_m'];ground_center=data.get('terrain',{}).get('height_center_m',0)
data.pop('building_footprints',None);data.pop('icons',None)
print('Loaded prepared scene',size,'m',flush=True)
bpy.ops.wm.read_factory_settings(use_empty=True)
scene=bpy.context.scene;scene.unit_settings.system='METRIC';scene.unit_settings.scale_length=1
scene['CRS']=plan['crs_name'];scene['PROJ']=plan['crs_proj'];scene['axis_order']='Blender X=Easting, Y=Northing, Z=Up. Geodetic Russian X=Northing, Y=Easting.'
scene['vertical_datum']=plan['vertical_reference'];scene['source']='Public 2GIS vector/immersive tiles and original GLB models';scene['extent_msk_east_north']=B
if data.get('terrain'):scene['terrain']=json.dumps(data['terrain'])
collections={};materials={};model_report=[]
palette={'Buildings':(.62,.67,.69,1),'Road_surfaces':(.23,.26,.28,1),'Road_edges':(.65,.68,.67,1),'Road_markings':(.92,.91,.84,1),'Road_marking_symbols':(.94,.94,.89,1),'Land_cover':(.59,.60,.57,1),'Green_areas':(.3,.45,.3,1),'Water':(.22,.46,.57,1),'Base':(.51,.53,.51,1)}
def collection(name):
    if name not in collections:
        co=bpy.data.collections.new(name);scene.collection.children.link(co);collections[name]=co
        if name.endswith('_hidden'):co.hide_render=True;co.hide_viewport=True
    return collections[name]
def material(cat):
    if cat not in materials:
        m=bpy.data.materials.new(cat);m.diffuse_color=palette.get(cat,(.6,.6,.6,1));materials[cat]=m
    return materials[cat]
def relink(obj,cat):
    for co in list(obj.users_collection):co.objects.unlink(obj)
    collection(cat).objects.link(obj)
def create_mesh(d):
    mesh=bpy.data.meshes.new(d['name']);mesh.from_pydata(d['vertices'],d.get('edges',[]),d['faces']);mesh.update()
    obj=bpy.data.objects.new(d['name'],mesh);collection(d['category']).objects.link(obj)
    mat=material(d['category'])
    if d.get('material_color'):
        mat=bpy.data.materials.new(d['name']+'_source_color');mat.diffuse_color=d['material_color']
    mesh.materials.append(mat);obj['source_layer']=d['name']
    if d.get('face_tiers'):
        attr=mesh.attributes.new('2gis_tier','INT','FACE');attr.data.foreach_set('value',[max(t or [0]) for t in d['face_tiers']])
    return obj
def import_objects(file):
    before=set(bpy.data.objects);bpy.ops.import_scene.gltf(filepath=file,import_pack_images=True);return [o for o in bpy.data.objects if o not in before]
def clip_mesh(obj):
    bm=bmesh.new();bm.from_mesh(obj.data)
    for co,no in [((B[0],0,0),(-1,0,0)),((B[2],0,0),(1,0,0)),((0,B[1],0),(0,-1,0)),((0,B[3],0),(0,1,0))]:
        if not bm.verts:break
        bmesh.ops.bisect_plane(bm,geom=list(bm.verts)+list(bm.edges)+list(bm.faces),dist=1e-6,plane_co=co,plane_no=no,clear_outer=True,clear_inner=False)
    bm.to_mesh(obj.data);bm.free();obj.data.update()
for f in data['models']:
    p=f['properties'];scale=p.get('scale',1);a=p.get('angle',0);c,s=math.cos(a),math.sin(a);j=f['jacobian'];e,n=f['position']
    m=Matrix(((scale*(j[0][0]*c+j[0][1]*s),scale*(-j[0][0]*s+j[0][1]*c),0,e),(scale*(j[1][0]*c+j[1][1]*s),scale*(-j[1][0]*s+j[1][1]*c),0,n),(0,0,scale*f['z_factor'],f.get('terrain_base_m',0)),(0,0,0,1)))
    objects=import_objects(f['local_file']);bpy.context.view_layer.update();kept=[]
    from gltf_static import bake_static_nodes
    bake_static_nodes(objects,m)
    for obj in objects:
        if obj.type!='MESH':continue
        coords=[v.co for v in obj.data.vertices]
        if not coords or max(v.x for v in coords)<B[0] or min(v.x for v in coords)>B[2] or max(v.y for v in coords)<B[1] or min(v.y for v in coords)>B[3]:continue
        clip_mesh(obj)
        if not obj.data.vertices:continue
        obj.name=Path(f['local_file']).stem+'_'+obj.name;relink(obj,'Detailed_2GIS_models');obj['2gis_building_id']=str(p.get('building_id',''));obj['source_glb']=f['local_file'];obj['terrain_base_m']=f.get('terrain_base_m',0);kept.append(obj)
        zs=[v.co.z for v in obj.data.vertices];model_report.append({'source':Path(f['local_file']).name,'z_min':min(zs),'z_max':max(zs),'vertices':len(zs)})
    for obj in objects:
        if obj not in kept:bpy.data.objects.remove(obj,do_unlink=True)
    print('model',Path(f['local_file']).name,'kept meshes',len(kept),flush=True)
templates={};use_nodes=len(data['instances'])>20000
for i,inst in enumerate(data['instances']):
    file=inst['file']
    if file not in templates:
        imported=import_objects(file);bpy.context.view_layer.update();templates[file]=[]
        for obj in imported:
            if obj.type=='MESH':
                # Bake the glTF node transforms into template data in Blender Z-up axes.
                mesh=obj.data.copy();mesh.transform(obj.matrix_world);templates[file].append(mesh)
        for obj in imported:bpy.data.objects.remove(obj,do_unlink=True)
    if use_nodes:continue
    sc=inst.get('scale',1);sc=[sc]*3 if isinstance(sc,(int,float)) else sc
    rot=inst.get('rotation') or [0,0,0];rot=[v or 0 for v in rot]
    mat=Matrix.Translation(Vector(inst['position']))@Euler([math.radians(v) for v in rot]).to_matrix().to_4x4()@Matrix.Diagonal(Vector([*sc,1]))
    for mesh in templates[file]:
        obj=bpy.data.objects.new(inst['layer'],mesh);collection('Street_furniture_and_trees').objects.link(obj);obj.matrix_world=mat;obj['source_layer']=inst['layer']
    if i%500==0:print('street objects',i,flush=True)
street_report={'source_point_instances':len(data['instances']),'method':'Linked mesh objects'}
if use_nodes:
    sys.path.insert(0,str(Path(__file__).resolve().parent))
    from street_instances_blender import build_street_instances
    street_report=build_street_instances(data['instances'],templates,collection)
    print('street instance batches',street_report,flush=True)
scene['street_instances']=json.dumps(street_report)
data.pop('instances',None);data.pop('models',None)
# Import assets before adding the large terrain/road meshes: glTF import updates
# the dependency graph repeatedly, so importing into a light scene is much faster.
for index,d in enumerate(data['meshes']):
    create_mesh(d);d['vertices']=[];d['faces']=[];d.pop('edges',None);d.pop('face_tiers',None)
    if index%500==0:print('Blender mesh groups',index,flush=True)
data.pop('meshes',None)
if not data.get('terrain'):
    base={'name':f'Extent_{size}m','category':'Base','vertices':[[B[0],B[1],-.25],[B[2],B[1],-.25],[B[2],B[3],-.25],[B[0],B[3],-.25]],'faces':[[0,1,2,3]]};create_mesh(base)
# Retain source point locations as inspectable geometry, with attributes in the adjacent archive.
source_points=json.load(gzip.open(OUT/'source_points.json.gz','rt'))
for layer in sorted({p['layer'] for p in source_points}):
    create_mesh({'name':layer,'category':'Source_points_hidden','vertices':[p['position'] for p in source_points if p['layer']==layer],'faces':[]})
del source_points
text=bpy.data.texts.new('README_GEOGRAPHY');text.write('All source geometry: 2GIS. 1 Blender unit = 1 metre.\n'+json.dumps(plan,ensure_ascii=False,indent=2)+'\nPublic datum conversion is not survey-calibrated. Visible Z uses source DEM + relative object heights; hidden source points retain original relative height. Provider vertical datum is not independently certified. Original tile archives, property records, style and resources are retained beside this scene.\nHidden collections preserve non-rendered source lines, areas and POI locations. Trees use original map display models and representative display variation, not surveyed crowns.\n')
project_readme=Path(__file__).resolve().parents[1]/'README.md'
if project_readme.exists():bpy.data.texts.new('README_PROJECT_RU').write(project_readme.read_text())
bpy.ops.object.camera_add(location=(cx+size*1.1,cy-size*1.5,ground_center+size*1.2));cam=bpy.context.object;cam.name='Overview';direction=Vector((cx,cy,ground_center+80))-cam.location;cam.rotation_euler=direction.to_track_quat('-Z','Y').to_euler();cam.data.type='ORTHO';cam.data.ortho_scale=size*1.65;cam.data.clip_end=size*20;scene.camera=cam;relink(cam,'Presentation')
scene.render.engine='BLENDER_WORKBENCH';scene.render.resolution_x=1600;scene.render.resolution_y=1200;scene.render.resolution_percentage=100
shade=scene.display.shading;shade.light='STUDIO';shade.color_type='MATERIAL';shade.show_shadows=True;shade.show_cavity=True;shade.cavity_type='BOTH';shade.curvature_ridge_factor=1.4;shade.curvature_valley_factor=1.1;shade.background_type='WORLD';scene.world=bpy.data.worlds.new('World');scene.world.color=(.055,.065,.075)
scene.view_settings.view_transform='Standard';scene.render.image_settings.file_format='PNG';scene.render.film_transparent=False
for screen in bpy.data.screens:
    for area in screen.areas:
        if area.type=='VIEW_3D':
            sp=area.spaces.active;sp.clip_end=size*20;sp.clip_start=.1;sp.region_3d.view_distance=size*1.7;sp.region_3d.view_location=(cx,cy,60);sp.region_3d.view_rotation=cam.rotation_euler.to_quaternion();sp.overlay.show_floor=False;sp.overlay.show_axis_x=False;sp.overlay.show_axis_y=False;sp.shading.color_type='MATERIAL';sp.shading.light='STUDIO';sp.shading.show_shadows=True;sp.shading.show_cavity=True
sys.path.insert(0,str(Path(__file__).resolve().parent))
from colour_and_light import configure_colour_and_light
colour_report=configure_colour_and_light()
for screen in bpy.data.screens:
    for area in screen.areas:
        if area.type=='VIEW_3D':area.spaces.active.region_3d.view_location.z=ground_center+80
bpy.ops.object.select_all(action='DESELECT');bpy.context.view_layer.objects.active=None
bpy.ops.file.pack_all()
report={'objects':len(bpy.data.objects),'meshes':len(bpy.data.meshes),'model_measurements':model_report,'bounds_msk_east_north':B,'extent_m':size,'axis_mapping':'X=east Y=north Z=up','vertical_reference':plan['vertical_reference'],'colour':colour_report,'street_instances':street_report}
terrain_obj=bpy.data.objects.get('Terrain_2GIS_TIN')
if terrain_obj:
    xs=[v.co.x for v in terrain_obj.data.vertices];ys=[v.co.y for v in terrain_obj.data.vertices]
    report['measured_terrain_extent_m']=[max(xs)-min(xs),max(ys)-min(ys)]
    assert all(abs(v-size)<.01 for v in report['measured_terrain_extent_m']),report['measured_terrain_extent_m']
    del xs,ys
report['visible_faces_by_collection']={co.name:sum(len(o.data.polygons) for o in co.objects if o.type=='MESH') for co in scene.collection.children if not co.hide_render}
(OUT/'blender_report.json').write_text(json.dumps(report,indent=2))
(OUT/'georeferencing.json').write_text(json.dumps({'plan':plan,'terrain':data.get('terrain')},ensure_ascii=False,indent=2))
filepath=OUT/f'MoscowCity_{size}m_MSK77.blend';bpy.ops.wm.save_as_mainfile(filepath=str(filepath),compress=True)
if size>1000:
    optimizer=Path(__file__).resolve().parent/'optimize_and_validate_full.py'
    exec(compile(optimizer.read_text(),str(optimizer),'exec'),{'__name__':'__main__','__file__':str(optimizer),'OUTPUT_DIRECTORY':OUT})
    print('SAVED',filepath,flush=True)
    raise SystemExit(0)
scene.render.filepath=str(OUT/'overview.png');bpy.ops.render.render(write_still=True)
cam.location=(cx,cy,ground_center+size*2);cam.rotation_euler=(0,0,0);cam.data.ortho_scale=size*1.05*max(1,scene.render.resolution_x/scene.render.resolution_y);scene.render.filepath=str(OUT/'top_view.png');bpy.ops.render.render(write_still=True)
if size>1000:
    cam.location=(cx+1100,cy-1500,ground_center+1200);cam.rotation_euler=(Vector((cx,cy,ground_center+80))-cam.location).to_track_quat('-Z','Y').to_euler();cam.data.ortho_scale=1650
    scene.render.filepath=str(OUT/'city_detail.png');bpy.ops.render.render(write_still=True)
print('SAVED',filepath,flush=True)
