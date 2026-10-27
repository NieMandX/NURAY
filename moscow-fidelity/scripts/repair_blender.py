"""Repair a copy of the retained 2GIS scene; never overwrite the input file.

Usage: blender -b INPUT.blend --python repair_blender.py -- --masks DIR --output FILE
Requires Shapely 2.1 in Blender's Python path (or --dependencies).
"""
import argparse, json, sys, time
from pathlib import Path
import bpy
import numpy as np
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree

WHITE=(.96,.96,.96,1.)
YELLOW=(1.,.93,.045,1.)
BLUE=(.0844,.2961,.7758,1.)
OTHER_MAX=.65

def enum_set(owner,prop,value):
    allowed={v.identifier for v in owner.bl_rna.properties[prop].enum_items}
    if value not in allowed:raise ValueError((prop,value,allowed))
    setattr(owner,prop,value)

def array(data,prop,width,dtype=np.float32):
    out=np.empty(len(data)*width,dtype=dtype);data.foreach_get(prop,out)
    return out.reshape(-1,width)

def triangles(obj):
    me=obj.data;me.calc_loop_triangles()
    vs=array(me.vertices,'co',3);ids=array(me.loop_triangles,'vertices',3,np.int32)
    return vs[ids],array(me.loop_triangles,'polygon_index',1,np.int32).ravel()

def polygon_parts(shape):
    if shape.is_empty:return []
    if shape.geom_type=='Polygon':return [shape]
    if not hasattr(shape,'geoms'):return []
    return [p for child in shape.geoms for p in polygon_parts(child)]

def tiled_polygon_parts(shape,size=250):
    """Bound triangulation cost for the connected pedestrian network of the whole city."""
    import math,shapely
    x0,y0,x1,y1=shape.bounds;index=0
    for ix in range(math.floor(x0/size),math.floor(x1/size)+1):
        for iy in range(math.floor(y0/size),math.floor(y1/size)+1):
            part=shapely.clip_by_rect(shape,ix*size,iy*size,(ix+1)*size,(iy+1)*size)
            if not shapely.is_valid(part):part=shapely.make_valid(part)
            yield from polygon_parts(part)
            index+=1
            if index%200==0:print('PATH GRID',index,flush=True)

def replace_triangles(obj,ts,source_faces):
    old=obj.data;mesh=bpy.data.meshes.new(old.name+'_fidelity')
    mesh.from_pydata(ts.reshape(-1,3).tolist(),[],np.arange(len(ts)*3).reshape(-1,3).tolist())
    for mat in old.materials:mesh.materials.append(mat)
    mids=array(old.polygons,'material_index',1,np.int32).ravel()
    mesh.polygons.foreach_set('material_index',mids[source_faces])
    for old_attr in old.attributes:
        if old_attr.domain!='FACE' or old_attr.data_type!='INT':continue
        values=array(old_attr.data,'value',1,np.int32).ravel()
        attr=mesh.attributes.get(old_attr.name) or mesh.attributes.new(old_attr.name,'INT','FACE')
        attr.data.foreach_set('value',values[source_faces])
    mesh.update();obj.data=mesh
    if old.users==0:bpy.data.meshes.remove(old)

def cut_mask(obj,mask,report):
    """Subtract in XY, retaining the exact plane of every original triangle."""
    import shapely
    if mask.is_empty:return
    shapely.prepare(mask)
    print('CUT BEGIN',obj.name,flush=True)
    ts,face_ids=triangles(obj);kept=[];sources=[];removed=0.;cut_count=0;local_cache={}
    def local_for(cell,b):
        x0,y0=cell*200-32;x1,y1=(cell+1)*200+32
        if b[:,0].min()>=x0 and b[:,1].min()>=y0 and b[:,2].max()<=x1 and b[:,3].max()<=y1:
            key=tuple(cell)
            if key not in local_cache:
                local=shapely.clip_by_rect(mask,float(x0),float(y0),float(x1),float(y1))
                local=local if shapely.is_valid(local) else shapely.make_valid(local)
                shapely.prepare(local);local_cache[key]=local
            return local_cache[key]
        local=shapely.clip_by_rect(mask,float(b[:,0].min())-.001,float(b[:,1].min())-.001,float(b[:,2].max())+.001,float(b[:,3].max())+.001)
        if not shapely.is_valid(local):local=shapely.make_valid(local)
        shapely.prepare(local);return local
    for start in range(0,len(ts),25000):
        batch=ts[start:start+25000];fi=face_ids[start:start+25000]
        pp=shapely.polygons(batch[:,:,:2]);bb_all=shapely.bounds(pp)
        cell_all=np.floor((bb_all[:,:2]+bb_all[:,2:])/400).astype(np.int64);keys_all=cell_all[:,0]*100000+cell_all[:,1]
        hit=np.zeros(len(pp),dtype=bool);fully=np.zeros(len(pp),dtype=bool)
        # GEOS global prepared predicates still scan distant polygon components.
        # Restrict both predicates to a cached spatial cell before testing triangles.
        for key in np.unique(keys_all):
            select=keys_all==key;local=local_for(cell_all[select][0],bb_all[select])
            hit[select]=shapely.intersects(local,pp[select]);fully[select]=shapely.covers(local,pp[select])
        kept.append(batch[~hit]);sources.append(fi[~hit])
        if not np.any(hit):continue
        affected=batch[hit];polys=pp[hit];af=fi[hit]
        covered=fully[hit]
        removed+=float(shapely.area(polys[covered]).sum());cut_count+=int(hit.sum())
        # Localize complex city-wide masks before overlay. Global prepared tests are
        # cheap, but repeating a full million-edge polygon in every difference is not.
        pending=polys[~covered];partial=np.empty(len(pending),dtype=object)
        if len(pending):
            bb=shapely.bounds(pending);cells=np.floor((bb[:,:2]+bb[:,2:])/400).astype(np.int64)
            keys=cells[:,0]*100000+cells[:,1]
            for key in np.unique(keys):
                select=keys==key;b=bb[select];local=local_for(cells[select][0],b)
                # Clip once more to each small triangle's bounds. This prevents GEOS
                # from scanning every distant hole of the connected path network.
                tight=np.array([shapely.clip_by_rect(local,float(q[0])-.001,float(q[1])-.001,float(q[2])+.001,float(q[3])+.001) for q in b],dtype=object)
                valid=shapely.is_valid(tight)
                if not np.all(valid):tight[~valid]=shapely.make_valid(tight[~valid])
                partial[select]=shapely.difference(pending[select],tight,grid_size=.001)
        extras=[];extra_ids=[]
        for original,poly,remainder,source in zip(affected[~covered],polys[~covered],partial,af[~covered]):
            removed+=poly.area-remainder.area
            if remainder.is_empty:continue
            original=original.astype(float)
            matrix=np.column_stack((original[:,:2],np.ones(3)))
            if abs(np.linalg.det(matrix))<1e-10:continue
            plane=np.linalg.solve(matrix,original[:,2])
            for part in polygon_parts(remainder):
                for tri in shapely.get_parts(shapely.constrained_delaunay_triangles(part)):
                    if tri.area<1e-8:continue
                    xy=np.asarray(tri.exterior.coords)[:3,:2]
                    xyz=np.column_stack((xy,np.column_stack((xy,np.ones(3)))@plane))
                    # Keep upward-facing winding; source normals are recomputed after clipping.
                    if np.cross(xyz[1]-xyz[0],xyz[2]-xyz[0])[2]<0:xyz=xyz[[0,2,1]]
                    extras.append(xyz);extra_ids.append(source)
        if extras:kept.append(np.asarray(extras,dtype=np.float32));sources.append(np.asarray(extra_ids,dtype=np.int32))
        if start%250000==0:print('CUT PROGRESS',obj.name,start,'/',len(ts),flush=True)
    if cut_count:
        new=np.concatenate(kept);src=np.concatenate(sources);replace_triangles(obj,new,src)
        report.append({'object':obj.name,'old_triangles':len(ts),'new_triangles':len(new),'affected':cut_count,'removed_projected_area_m2':removed})
        print('CUT',obj.name,len(ts),'->',len(new),round(removed,2),'m2',flush=True)

def paint_material(name,color,kind):
    mat=bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat.use_nodes=True;mat.diffuse_color=color;mat['fidelity_paint']=kind
    bsdf=next(n for n in mat.node_tree.nodes if n.type=='BSDF_PRINCIPLED')
    bsdf.inputs['Base Color'].default_value=color
    bsdf.inputs['Roughness'].default_value=.55
    bsdf.inputs['Metallic'].default_value=0
    bsdf.inputs['Emission Strength'].default_value=0
    return mat

def restore_markings(masks,report):
    import shapely
    white=paint_material('Road paint — white',WHITE,'white')
    yellow=paint_material('Road paint — yellow',YELLOW,'yellow')
    blue=paint_material('Road paint — blue',BLUE,'blue')
    for category in ['Road_markings','Road_marking_symbols']:
        collection=bpy.data.collections.get(category)
        if not collection:continue
        for obj in collection.objects:
            if obj.type!='MESH':continue
            layer=obj.get('source_layer',obj.name)
            if layer=='PolygonMarkings_save_island':continue # asphalt background, not paint
            kind='yellow' if layer in ['LinearMarking_Stop','LinearMarking_TramStop','PolygonMarkings_waffle'] else ('blue' if layer=='LinearMarking_ShortIntermittentBlue' else 'white')
            obj.data.materials.clear();obj.data.materials.append({'white':white,'yellow':yellow,'blue':blue}[kind])
            obj.data.polygons.foreach_set('material_index',np.zeros(len(obj.data.polygons),dtype=np.int32))
            mixed=0
            if layer=='PolygonMarkings_pedestrian_crossing':
                ts,faces=triangles(obj);centers=ts[:,:,:2].mean(axis=1)
                attr=obj.data.attributes.get('2gis_tier');tiers=array(attr.data,'value',1,np.int32).ravel()[faces] if attr else np.zeros(len(ts),dtype=np.int32)
                yellow_faces=np.zeros(len(obj.data.polygons),dtype=np.int32)
                for tier in np.unique(tiers):
                    mask=masks.get('yellow_crossing_tier_'+str(tier))
                    if mask is None:continue
                    select=tiers==tier;marked=shapely.intersects_xy(mask,centers[select,0],centers[select,1])
                    yellow_faces[faces[select][marked]]=1
                obj.data.materials.append(yellow);obj.data.polygons.foreach_set('material_index',yellow_faces);mixed=int(yellow_faces.sum())
            report.append({'object':obj.name,'paint':kind,'yellow_crossing_faces':mixed})

def cap_other_materials():
    count=0
    for mat in bpy.data.materials:
        if mat.get('fidelity_paint'):continue
        if mat.get('fidelity_albedo_capped'):continue
        rgb=list(mat.diffuse_color);scale=min(1.,OTHER_MAX/max(max(rgb[:3]),1e-8))
        mat.diffuse_color=(*[v*scale for v in rgb[:3]],rgb[3])
        if mat.use_nodes:
            bsdf=next((n for n in mat.node_tree.nodes if n.type=='BSDF_PRINCIPLED'),None)
            if bsdf:
                base=bsdf.inputs['Base Color']
                if base.is_linked:
                    link=base.links[0];source=link.from_socket
                    if link.from_node.type=='TEX_IMAGE':mat['fidelity_color_image']=link.from_node.image.name
                    mat.node_tree.links.remove(link)
                    multiply=mat.node_tree.nodes.new('ShaderNodeVectorMath');enum_set(multiply,'operation','SCALE')
                    multiply.inputs['Scale'].default_value=OTHER_MAX
                    mat.node_tree.links.new(source,multiply.inputs[0]);mat.node_tree.links.new(multiply.outputs[0],base)
                    mat['fidelity_texture_factor']=OTHER_MAX
                else:
                    rgba=list(base.default_value);s=min(1.,OTHER_MAX/max(max(rgba[:3]),1e-8));base.default_value=(*[v*s for v in rgba[:3]],rgba[3])
        mat['fidelity_albedo_capped']=OTHER_MAX;count+=1
    return count

def add_paths(mask,terrain,report):
    import shapely
    if mask.is_empty:return
    print('PATHS BEGIN',round(mask.area,1),'m2',flush=True)
    tris,_=triangles(terrain)
    tree=BVHTree.FromPolygons(tris.reshape(-1,3).tolist(),np.arange(len(tris)*3).reshape(-1,3).tolist(),all_triangles=True)
    verts=[];faces=[];missing=0
    # Split long path triangles before sampling terrain; use the same 10 m maximum as the source pipeline.
    for polygon in tiled_polygon_parts(mask):
        for tri in shapely.get_parts(shapely.constrained_delaunay_triangles(polygon)):
            stack=[np.asarray(tri.exterior.coords)[:3,:2]]
            while stack:
                xy=stack.pop();lengths=np.sum((np.roll(xy,-1,axis=0)-xy)**2,axis=1);i=int(np.argmax(lengths))
                if lengths[i]>100:
                    a,b,c=xy[i],xy[(i+1)%3],xy[(i+2)%3];mid=(a+b)/2;stack.extend([np.array([a,mid,c]),np.array([mid,b,c])]);continue
                xyz=[]
                for x,y in xy:
                    hit=tree.ray_cast(Vector((float(x),float(y),1000)),Vector((0,0,-1)))
                    if hit[0] is None:
                        # Float32 mesh boundaries can be <1 mm inside their float64 source.
                        # Use adjacent terrain within 2 mm only; never invent elevations.
                        for dx,dy in [(.002,0),(-.002,0),(0,.002),(0,-.002)]:
                            hit=tree.ray_cast(Vector((float(x+dx),float(y+dy),1000)),Vector((0,0,-1)))
                            if hit[0] is not None:break
                    if hit[0] is None:missing+=1;break
                    xyz.append((float(x),float(y),hit[0].z+.19))
                if len(xyz)==3:
                    if np.cross(np.subtract(xyz[1],xyz[0]),np.subtract(xyz[2],xyz[0]))[2]<0:xyz=[xyz[0],xyz[2],xyz[1]]
                    offset=len(verts);verts.extend(xyz);faces.append((offset,offset+1,offset+2))
    mesh=bpy.data.meshes.new('Pedestrian_paths_source_geometry');mesh.from_pydata(verts,[],faces);mesh.update()
    obj=bpy.data.objects.new('Pedestrian_paths_source_geometry',mesh);bpy.data.collections['Land_cover'].objects.link(obj)
    obj['source_layer']='Pedestrian_paths_source_geometry';obj['fidelity_source']='2GIS line widths at zoom 19; source centerlines; terrain drape';obj['terrain_display_offset']=.19
    mat=bpy.data.materials.get('Land_cover');mesh.materials.append(mat)
    report.update(triangles=len(faces),missing_terrain_vertices=missing,projected_area_m2=mask.area)
    obj['fidelity_path_report']=json.dumps(report)
    print('PATHS END',report,flush=True)

def sample_heights(names,points):
    result=[{'xy':list(p),'hits':{}} for p in points]
    for name in names:
        obj=bpy.data.objects.get(name)
        if not obj:continue
        ts,_=triangles(obj);lo=ts[:,:,:2].min(axis=1);hi=ts[:,:,:2].max(axis=1)
        for row,p in zip(result,points):
            ss=ts[np.all(lo<=p,axis=1)&np.all(hi>=p,axis=1)].astype(float)
            zs=[]
            for tri in ss:
                mat=np.column_stack((tri[:,:2],np.ones(3)))
                if abs(np.linalg.det(mat))<1e-10:continue
                weights=np.linalg.solve(mat.T,[*p,1])
                if min(weights)>-1e-6:zs.append(float(weights@tri[:,2]))
            if zs:row['hits'][name]=max(zs)
    return result

def separate_detailed_greens(masks,report):
    if bpy.context.scene.get('fidelity_detailed_greens'):return
    mask=masks['Immersive_park_polygon_green']
    for name in ['Forest_quarter','Internal_forest_quarter','Internal_lawn','Flowerbed_quarter']:
        obj=bpy.data.objects.get(name)
        if obj:cut_mask(obj,mask,report.setdefault('detailed_green_cuts',[]))
    bpy.context.scene['fidelity_detailed_greens']=True

def remove_legacy_entrances(report):
    if bpy.context.scene.get('fidelity_legacy_entrances_removed'):return
    text=bpy.data.texts.get('building_source_index.json')
    if not text:raise RuntimeError('Batched-building source index is missing')
    index=json.loads(text.as_string())
    ids=[int(k) for k,v in index.items() if v['source_layer'].startswith('Underpass_entrance_')]
    count=0
    for obj in bpy.data.collections['Buildings'].objects:
        if obj.type!='MESH':continue
        attr=obj.data.attributes.get('source_object_index')
        if not attr:raise RuntimeError('Building batch lacks source identity: '+obj.name)
        values=array(attr.data,'value',1,np.int32).ravel()
        ts,faces=triangles(obj);keep=~np.isin(values[faces],ids)
        if np.all(keep):continue
        assert not obj.data.uv_layers,'Unexpected building UVs; preserve them before filtering'
        count+=int((~keep).sum());replace_triangles(obj,ts[keep],faces[keep])
    report['legacy_entrance_source_objects']=len(ids)
    report['legacy_entrance_triangles_removed']=count
    bpy.context.scene['fidelity_legacy_entrances_removed']=True

def restore_open_descents(masks,report):
    """Use explicit source tunnel-descents, never open the covered tunnel roof."""
    mask=masks.get('tunnel_descent')
    if mask is None:raise RuntimeError('Open tunnel descent mask is required')
    mask=mask.buffer(.003)
    for category in ['Green_areas','Land_cover']:
        for obj in list(bpy.data.collections[category].objects):
            if obj.type!='MESH' or obj.hide_render or obj.name in ['Pier_quarter','Bridge_area']:continue
            cut_mask(obj,mask,report.setdefault('tunnel_cuts',[]))
    # Source style 656067 only shows these coarse boxes when immersiveRoadsOn=false.
    legacy=bpy.data.objects.get('Underpass_entrance')
    if legacy:
        legacy.hide_render=True;legacy.hide_set(True)
        legacy['fidelity_hidden_reason']='Non-immersive fallback; source immersive road descents are present'
    report['open_descent_area_m2']=masks['tunnel_descent'].area
    remove_legacy_entrances(report)
    bpy.context.scene['fidelity_open_descents']=True

def resolve_background(masks,report):
    """A separate coarse TIN must not compete with the complete detailed ground."""
    import shapely
    admin=masks.get('Administrative_quarter')
    if admin is None:raise RuntimeError('Administrative ground coverage mask is required')
    terrain=bpy.data.objects['Terrain_2GIS_TIN']
    bounds=terrain.bound_box
    expected=shapely.box(min(p[0] for p in bounds),min(p[1] for p in bounds),max(p[0] for p in bounds),max(p[1] for p in bounds))
    assert expected.difference(admin.buffer(.005)).area<.01,'Detailed ground has coverage gaps'
    terrain.hide_render=True;terrain.hide_set(True)
    terrain['fidelity_hidden_reason']='Complete source ground already follows DEM; coarse duplicate TIN intersects detailed surfaces'
    green=['Forest_quarter','Internal_forest_quarter','Internal_lawn','Flowerbed_quarter']
    keys=green+[k for k in masks if k.startswith('Immersive_park_polygon_')]+['Pedestrian_quarter','pedestrian_lines']
    foreground=shapely.union_all([masks[k] for k in keys if k in masks])
    for name in ['Administrative_quarter','Dwelling_quarter']:
        obj=bpy.data.objects.get(name)
        if obj:cut_mask(obj,foreground,report.setdefault('background_cuts',[]))
    report['coarse_terrain_hidden']=True
    report['detailed_ground_coverage_m2']=admin.area

def repair(masks_dir):
    import shapely
    if bpy.context.scene.get('fidelity_repair_version'):raise RuntimeError('Scene already repaired; refusing to apply twice')
    print('REPAIR BEGIN',bpy.data.filepath,flush=True)
    masks={p.stem:shapely.from_wkb(p.read_bytes()) for p in Path(masks_dir).glob('*.wkb')}
    empty=shapely.Polygon();water=masks['Water_area'].buffer(.003)
    paved_keys=[k for k in masks if k.startswith('Immersive_park_polygon_') and k!='Immersive_park_polygon_green']
    paving=shapely.union_all([masks[k] for k in paved_keys])
    grass=masks.get('Immersive_park_polygon_green',empty)
    pedestrian=masks.get('Pedestrian_quarter',empty)
    # Existing detailed polygons define plazas and islands more precisely than line strokes.
    line_mask=masks.get('pedestrian_lines',empty).difference(shapely.union_all([paving,grass,water]))
    report={'version':1,'input':bpy.data.filepath,'animated_objects':[],'cuts':[],'markings':[],'paths':{}}
    for obj in bpy.data.objects:
        if obj.type=='MESH' and obj.get('source_glb') and obj.animation_data:
            before=[min((obj.matrix_world@Vector(v)).z for v in obj.bound_box),max((obj.matrix_world@Vector(v)).z for v in obj.bound_box)]
            obj.animation_data_clear();obj.parent=None;obj.matrix_world=Matrix.Identity(4)
            after=[min(v[2] for v in obj.bound_box),max(v[2] for v in obj.bound_box)]
            report['animated_objects'].append({'name':obj.name,'z_before':before,'z_after':after})
    bpy.context.view_layer.update()
    # Shore is a gradient render target in the 2GIS style, not a solid land polygon.
    shore=bpy.data.objects.get('Shore')
    if shore:shore.hide_render=True;shore.hide_set(True);shore['fidelity_hidden_reason']='2GIS shoreline gradient helper, not land geometry'
    terrain=bpy.data.objects['Terrain_2GIS_TIN']
    if bpy.data.objects.get('Pedestrian_paths_source_geometry'):
        report['paths']=json.loads(bpy.data.objects['Pedestrian_paths_source_geometry']['fidelity_path_report'])
    else:
        add_paths(line_mask,terrain,report['paths'])
        checkpoint=Path(bpy.data.filepath).parent/'paths-checkpoint.blend'
        bpy.ops.wm.save_as_mainfile(filepath=str(checkpoint),copy=True,compress=True)
        print('PATH CHECKPOINT',checkpoint,flush=True)
    for category in ['Green_areas','Land_cover','Terrain']:
        for obj in list(bpy.data.collections[category].objects):
            if obj.type!='MESH' or obj.hide_render or obj.name in ['Pedestrian_paths_source_geometry','Pier_quarter','Bridge_area']:continue
            layer=obj.get('source_layer',obj.name);mask=water
            if category=='Terrain':mask=shapely.union_all([mask,pedestrian,paving,line_mask])
            elif layer=='Forest_quarter':mask=shapely.union_all([mask,pedestrian,paving,line_mask])
            elif layer in ['Internal_forest_quarter','Flowerbed_quarter','Internal_lawn']:mask=shapely.union_all([mask,paving,line_mask])
            elif layer in paved_keys:mask=shapely.union_all([mask,grass])
            cut_mask(obj,mask,report['cuts'])
    # Blue park paving is a colored playground surface, not a water body.
    blue=bpy.data.objects.get('Immersive_park_polygon_blue')
    if blue:
        for collection in list(blue.users_collection):collection.objects.unlink(blue)
        bpy.data.collections['Land_cover'].objects.link(blue)
        material=bpy.data.materials.new('Park blue paving');material.diffuse_color=(.15,.32,.52,1);material.use_nodes=True
        next(n for n in material.node_tree.nodes if n.type=='BSDF_PRINCIPLED').inputs['Base Color'].default_value=material.diffuse_color
        blue.data.materials.clear();blue.data.materials.append(material)
    resolve_background(masks,report)
    separate_detailed_greens(masks,report)
    restore_open_descents(masks,report)
    restore_markings(masks,report['markings']);report['capped_other_materials']=cap_other_materials()
    park_points=[(560,7160),(630,7250),(800,7360),(560,7260),(660,7160)]
    report['park_samples']=sample_heights(['Forest_quarter','Immersive_park_polygon_pedestrian_stone','Terrain_2GIS_TIN'],park_points)
    report['river_samples']=sample_heights(['Terrain_2GIS_TIN','Water_area','Administrative_quarter','Shore'],[(2347.99,8578.3),(2359.91,8572.34),(2503.88,8615.43),(2528.44,8626.65)])
    for point in report['park_samples']:
        assert 'Immersive_park_polygon_pedestrian_stone' in point['hits'],point
        assert 'Forest_quarter' not in point['hits'],point
    for point in report['river_samples']:assert 'Terrain_2GIS_TIN' not in point['hits'],point
    for obj in bpy.data.objects:
        if obj.type=='MESH' and obj.get('source_glb'):assert not obj.animation_data,obj.name
    for point in report['markings']:
        if point['object']=='PolygonMarkings_pedestrian_crossing':assert point['yellow_crossing_faces']>0,point
    bpy.context.scene['fidelity_repair_version']=1
    bpy.context.scene['fidelity_paint']='Linear white 0.96; yellow 1.0/0.93/0.045; other base reflectances <=0.65. Non-emissive.'
    return report

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--masks',required=True,type=Path);parser.add_argument('--output',required=True,type=Path);parser.add_argument('--dependencies',type=Path)
    args=parser.parse_args(sys.argv[sys.argv.index('--')+1:])
    if Path(bpy.data.filepath).resolve()==args.output.resolve():raise RuntimeError('Output must differ from input')
    if args.dependencies:sys.path.insert(0,str(args.dependencies))
    started=time.time();report=repair(args.masks);report['seconds']=time.time()-started
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.with_suffix('.report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    bpy.ops.wm.save_as_mainfile(filepath=str(args.output),compress=True)
    print('FIDELITY COMPLETE',args.output,report['seconds'],flush=True)
