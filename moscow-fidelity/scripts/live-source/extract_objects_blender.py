"""Extract current source GLBs and ordinary buildings without a legacy .blend.

All node transforms are frozen at evaluated pose before the source MSK transform.
The source-relative vertical datum is bound once per building by prepare_objects.
"""
import argparse,gzip,json,sys,math,hashlib,collections
from pathlib import Path
import bpy
import numpy as np
from mathutils import Matrix,Euler
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts'))
sys.path.insert(0,str(ROOT/'prototype/tiling'))
from gltf_static import bake_static_nodes
from approved_vegetation import FAMILIES
p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
a=p.parse_args(sys.argv[sys.argv.index('--')+1:]);a.output.mkdir(parents=True,exist_ok=True)
plan=json.loads((a.source/'plan.json').read_text())
scene=json.load(gzip.open(a.source/'output'/plan.get('output_subdir','area_5000')/'scene.json.gz','rt'));bounds=scene['plan']['extent_msk_east_north']
bpy.ops.wm.read_factory_settings(use_empty=True)
materials=[];material_ids={};objects=[];templates=[];instances=[];textures={};serial=0

def array(items,prop,width=1,dtype=np.float32):
    out=np.empty(len(items)*width,dtype=dtype);items.foreach_get(prop,out)
    return out.reshape(-1,width) if width>1 else out

def material_id(mat,category,objname=''):
    name=mat.name if mat else category;color=[.2852,.3082,.3174];rough=.79;metal=0.;image=None;alpha=0.
    if mat:
        color=list(mat.diffuse_color[:3])
        if mat.use_nodes:
            nodes=mat.node_tree.nodes;bsdf=next((n for n in nodes if n.type=='BSDF_PRINCIPLED'),None)
            if bsdf:
                color=list(bsdf.inputs['Base Color'].default_value[:3]);metal=float(bsdf.inputs['Metallic'].default_value)
                rough=max(.38,float(bsdf.inputs['Roughness'].default_value));alpha=.4 if bsdf.inputs['Alpha'].is_linked else 0.
            # KHR_materials_unlit is a display shader; retain its atlas and convert
            # to the same opaque physical facade model, without discarding colors.
            image=next((n.image for n in nodes if n.type=='TEX_IMAGE' and n.image),None)
        if image:color=[.65]*3
        else:
            peak=max(max(color),1e-8);color=[v*min(1.,.65/peak) for v in color]
    family=category;kind=1
    if category=='Detailed_2GIS_models' and any(s in objname.lower() for s in ('tower','mfkvtb','iqquarter','cityofcapitals','oko','imperiya')):
        family='coated facade';kind=11;rough=.24;color=[v*.35 for v in color]
    file=None
    if image:
        if not image.packed_file:raise ValueError('Expected embedded source image '+image.name)
        raw=bytes(image.packed_file.data);h=hashlib.sha256(raw).hexdigest();ext='.png' if raw[:8]==b'\x89PNG\r\n\x1a\n' else '.jpg'
        file='texture-'+h[:16]+ext;(a.output/file).write_bytes(raw);textures[file]=dict(bytes=len(raw),sha256=h,size=list(image.size))
    key=json.dumps([family,color,rough,metal,file,alpha],sort_keys=True)
    if key not in material_ids:
        material_ids[key]=len(materials);materials.append(dict(name=name,family=family,color=color,roughness=rough,metallic=metal,ior=1.5,kind=kind,texture=file,alphaCutoff=alpha))
    return material_ids[key]

def mesh_data(obj,category):
    me=obj.data;me.calc_loop_triangles()
    if not len(me.loop_triangles):return None
    positions=array(me.vertices,'co',3).astype(float);ix=array(me.loop_triangles,'vertices',3,np.int32);loops=array(me.loop_triangles,'loops',3,np.int32)
    normals=array(me.corner_normals,'vector',3)[loops].astype(float)
    normals/=np.maximum(np.linalg.norm(normals,axis=2,keepdims=True),1e-20)
    uv=array(me.uv_layers.active.data,'uv',2)[loops] if me.uv_layers.active else positions[ix][:,:,:2]
    if me.uv_layers.active:uv[:,:,1]=1-uv[:,:,1]
    mids=array(me.loop_triangles,'material_index',dtype=np.int32)
    remap={i:material_id(me.materials[i] if i<len(me.materials) else None,category,obj.name) for i in np.unique(mids)}
    return np.concatenate([positions[ix],normals,uv],axis=2),np.asarray([remap[i] for i in mids],dtype=np.uint32)

def overlaps(p):
    return len(p) and p[:,0].max()>=bounds[0] and p[:,0].min()<=bounds[2] and p[:,1].max()>=bounds[1] and p[:,1].min()<=bounds[3]

def save(name,category,parts,**meta):
    global serial
    if not parts:return
    tris=np.concatenate([p[0] for p in parts]);mats=np.concatenate([p[1] for p in parts])
    if category!='tree-template' and not overlaps(tris[:,:,:3].reshape(-1,3)):return
    file=f'object-{serial:05d}.npz';serial+=1;np.savez_compressed(a.output/file,triangles=tris,materials=mats)
    row=dict(id=name,category=category,file=file,triangles=len(tris),bounds=dict(min=tris[:,:,:3].min((0,1)).tolist(),max=tris[:,:,:3].max((0,1)).tolist()),**meta)
    (templates if category=='tree-template' else objects).append(row)

def imported(file,transform):
    before=set(bpy.data.objects);bpy.ops.import_scene.gltf(filepath=str(file),import_pack_images=True)
    nodes=[o for o in bpy.data.objects if o not in before];bpy.context.view_layer.update();bake_static_nodes(nodes,transform)
    return nodes

def remove(nodes):
    for obj in nodes:bpy.data.objects.remove(obj,do_unlink=True)
    bpy.data.orphans_purge(do_recursive=True)

for index,f in enumerate(scene['models']):
    props=f['properties'];scale=props['scale'];angle=props.get('angle',0);c,s=math.cos(angle),math.sin(angle);j=f['jacobian'];e,n=f['position']
    matrix=Matrix(((scale*(j[0][0]*c+j[0][1]*s),scale*(-j[0][0]*s+j[0][1]*c),0,e),(scale*(j[1][0]*c+j[1][1]*s),scale*(-j[1][0]*s+j[1][1]*c),0,n),(0,0,scale*f['z_factor'],0),(0,0,0,1)))
    nodes=imported(f['local_file'],matrix);parts=[mesh_data(o,'Detailed_2GIS_models') for o in nodes if o.type=='MESH'];parts=[p for p in parts if p is not None]
    bid=str(props.get('building_id',props.get('db_object_building_id','')))
    save('landmark:'+bid+':'+Path(f['local_file']).stem,'landmark',parts,sourceFile=f['local_file'],sourceBuildingId=bid,sourceTerrainBaseM=0.,heightReference='source-relative',sourceChannel=f.get('sourceChannel'))
    remove(nodes);print('FRESH MODEL',index+1,'/',len(scene['models']),bid,flush=True)

for d in scene['meshes']:
    if d['category']!='Buildings' or not d['faces']:continue
    me=bpy.data.meshes.new(d['name']);me.from_pydata(d['vertices'],[],d['faces']);me.update()
    obj=bpy.data.objects.new(d['name'],me);bpy.context.scene.collection.objects.link(obj)
    part=mesh_data(obj,'Buildings');bid=d['name'].rsplit('_',1)[-1]
    save('building:'+d['name'],'building',[part] if part else [],sourceBuildingId=bid,sourceLayer=d['name'],sourceTerrainBaseM=0.,heightReference='source-relative')
    bpy.data.objects.remove(obj,do_unlink=True);bpy.data.meshes.remove(me)
print('FRESH BUILDINGS',len(objects),flush=True)

family={layer:template for layer,template,model in FAMILIES};saved={};library=collections.defaultdict(set);dedup=set()
for i,inst in enumerate(scene['instances']):
    layer=inst['layer'];library[layer].add(inst['file'])
    if layer not in family:continue
    name=family[layer]
    if name not in saved:
        nodes=imported(inst['file'],Matrix.Identity(4));parts=[mesh_data(o,'vegetation') for o in nodes if o.type=='MESH'];save(name,'tree-template',[p for p in parts if p is not None]);saved[name]=inst['file'];remove(nodes)
    elif saved[name]!=inst['file']:raise ValueError(('Multiple physical templates for vegetation class',layer))
    point=np.asarray(inst['position']);key=(layer,tuple(np.round(point,4)))
    if key in dedup:continue
    dedup.add(key);rotation=inst.get('rotation') or [0,0,0];rotation=[math.radians(v or 0) for v in rotation]
    scale=inst.get('scale',1);scale=[scale]*3 if isinstance(scale,(int,float)) else scale
    linear=np.asarray(Euler(rotation).to_matrix())@np.diag(scale)
    identity=hashlib.sha256(json.dumps([layer,inst['properties'].get('id'),key[1]],default=float).encode()).hexdigest()[:20]
    instances.append(dict(id='plant:'+identity,layer=layer,sourcePointIndex=i,templates=[name],position=point.tolist(),linear=linear.tolist(),sourceGLB=inst['file'],providerId=inst['properties'].get('id')))

source=dict(origin=plan.get('origin_msk',[2125,8070,145]),materials=materials,textures=textures)
(a.output/'scene.json').write_text(json.dumps(source,separators=(',',':')))
(a.output/'library-audit.json').write_text(json.dumps({'street':{'rows':[dict(name=k,sourceFiles=sorted(v)) for k,v in library.items()]}},indent=2))
manifest=dict(version=2,sourceBlend='fresh network snapshot '+str(a.source.resolve()),sourceFidelity='current browser decoder + evaluated GLB nodes',boundsMSK=bounds,objects=objects,templates=templates,instances=instances,pbrSource=str((a.output/'scene.json').resolve()),sourceOrigin=source['origin'])
(a.output/'extraction.json').write_text(json.dumps(manifest,ensure_ascii=False,separators=(',',':')))
print('FRESH EXTRACTION COMPLETE',len(objects),'objects',len(instances),'plants',len(templates),'templates',flush=True)
