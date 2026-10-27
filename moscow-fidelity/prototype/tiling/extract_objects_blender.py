"""Read-only extraction of corrected 2GIS buildings and vegetation.

Run Blender on the retained corrected .blend. Nothing is saved to that file.
Whole objects are extracted before region/tile clipping, with hierarchy already
frozen by the fidelity repair. The existing NURAY PBR conversion is retained.
"""
import argparse, json, sys
from pathlib import Path
from collections import defaultdict
import bpy
import numpy as np
from mathutils import Euler

parser=argparse.ArgumentParser()
parser.add_argument('--catalog',type=Path,required=True)
parser.add_argument('--pbr-source',type=Path,required=True)
parser.add_argument('--audit',type=Path,required=True)
parser.add_argument('--output',type=Path,required=True)
args=parser.parse_args(sys.argv[sys.argv.index('--')+1:])
assert bpy.context.scene.get('fidelity_repair_version'), 'Use the corrected source scene'
catalog=json.loads(args.catalog.read_text());bounds=catalog['boundsMSK']
args.output.mkdir(parents=True,exist_ok=True)
source=json.loads(args.pbr_source.read_text());by_name=defaultdict(list)
for i,m in enumerate(source['materials']):by_name[m['name']].append((i,m))
objects=[];templates=[];instances=[];serial=0

def array(items,prop,width=1,dtype=np.float32):
    out=np.empty(len(items)*width,dtype=dtype);items.foreach_get(prop,out)
    return out.reshape(-1,width) if width>1 else out

def overlaps(p):
    return len(p) and p[:,0].max()>=bounds[0] and p[:,0].min()<=bounds[2] and p[:,1].max()>=bounds[1] and p[:,1].min()<=bounds[3]

def material_id(mat,category,objname):
    name=mat.name if mat else 'Default';options=by_name.get(name,[])
    if category=='Buildings':options=[x for x in options if x[1]['family']=='Buildings']
    elif category=='Detailed_2GIS_models':
        coated=any(s in objname.lower() for s in ('tower','mfkvtb','iqquarter','cityofcapitals','oko','imperiya'))
        options=[x for x in options if (x[1]['family']=='coated facade')==coated]
    # A retained atlas may have several aliases but only one physical variant.
    physical={json.dumps({k:v for k,v in m.items() if k!='name'},sort_keys=True):i for i,m in options}
    if len(physical)!=1:raise ValueError(('Missing/ambiguous retained PBR material',name,category,objname,options))
    return next(iter(physical.values()))

def mesh_data(obj,category,template=False):
    me=obj.data;me.calc_loop_triangles()
    if not len(me.loop_triangles):return None
    p=array(me.vertices,'co',3).astype(float)
    mw=np.asarray(obj.matrix_world,dtype=float)
    if not template:p=p@mw[:3,:3].T+mw[:3,3]
    if not template and not overlaps(p):return None
    ids=array(me.loop_triangles,'vertices',3,np.int32)
    loops=array(me.loop_triangles,'loops',3,np.int32)
    normals=array(me.corner_normals,'vector',3)[loops].astype(float)
    if not template:normals=normals@np.linalg.inv(mw[:3,:3])
    normals/=np.maximum(np.linalg.norm(normals,axis=2,keepdims=True),1e-20)
    uv=array(me.uv_layers.active.data,'uv',2)[loops] if me.uv_layers.active else p[ids][:,:,:2]
    if me.uv_layers.active:uv[:,:,1]=1-uv[:,:,1]
    mids=array(me.loop_triangles,'material_index',dtype=np.int32)
    remap={i:material_id(me.materials[i] if i<len(me.materials) else None,category,obj.name) for i in np.unique(mids)}
    materials=np.asarray([remap[i] for i in mids],dtype=np.uint32)
    tris=np.concatenate((p[ids],normals,uv),axis=2)
    face_ids=array(me.loop_triangles,'polygon_index',dtype=np.int32)
    return tris,materials,face_ids

def save(name,category,parts,**meta):
    global serial
    tris=np.concatenate([p[0] for p in parts]);mats=np.concatenate([p[1] for p in parts])
    if category!='tree-template' and not overlaps(tris[:,:,:3].reshape(-1,3)):return
    filename=f'object-{serial:04d}.npz';serial+=1
    np.savez_compressed(args.output/filename,triangles=tris,materials=mats)
    row=dict(id=name,category=category,file=filename,triangles=len(tris),bounds=dict(min=tris[:,:,:3].min((0,1)).tolist(),max=tris[:,:,:3].max((0,1)).tolist()),**meta)
    (templates if category=='tree-template' else objects).append(row)

index=json.loads(bpy.data.texts['building_source_index.json'].as_string())
building_parts=defaultdict(list)
for obj in bpy.data.collections['Buildings'].objects:
    if obj.type!='MESH' or obj.hide_render:continue
    result=mesh_data(obj,'Buildings')
    if result is None:continue
    tris,mats,faces=result
    attr=obj.data.attributes.get('source_object_index')
    if not attr:raise ValueError('Source ownership is required: '+obj.name)
    owners=array(attr.data,'value',dtype=np.int32)[faces]
    for owner in np.unique(owners):
        sel=owners==owner
        if overlaps(tris[sel,:,:3].reshape(-1,3)):building_parts[int(owner)].append((tris[sel],mats[sel]))
for owner,parts in building_parts.items():
    row=index[str(owner)];save('building:'+str(owner),'building',parts,sourceObject=row['object'],sourceLayer=row['source_layer'],sourceBuildingId=row['source_layer'].rsplit('_',1)[-1])
print('EXTRACT ordinary buildings',len(objects),flush=True)

# Group every node of one source model under one vertical anchor. In particular,
# a floating sign is never independently draped onto terrain a second time.
landmarks=defaultdict(list);metadata={}
co=bpy.data.collections.get('Detailed_2GIS_models')
for obj in co.objects if co else []:
    if obj.type!='MESH' or obj.hide_render:continue
    result=mesh_data(obj,'Detailed_2GIS_models')
    if result is None:continue
    key=(str(obj.get('source_glb','')),str(obj.get('2gis_building_id','')))
    landmarks[key].append(result[:2]);metadata[key]=dict(sourceFile=key[0],sourceBuildingId=key[1],sourceTerrainBaseM=float(obj.get('terrain_base_m',0)))
for key,parts in landmarks.items():save('landmark:'+Path(key[0]).stem+':'+key[1],'landmark',parts,**metadata[key])
print('EXTRACT building groups',len(objects),flush=True)

audit=json.loads(args.audit.read_text());saved=set()
for row in audit['street']['rows']:
    obj=bpy.data.objects.get(row['name'])
    if not obj or not str(obj.get('source_layer',obj.name)).startswith('Model_tree_'):continue
    p=array(obj.data.vertices,'co',3).astype(float)
    keep=(p[:,0]>=bounds[0])&(p[:,0]<bounds[2])&(p[:,1]>=bounds[1])&(p[:,1]<bounds[3])
    selected=np.flatnonzero(keep)
    if not len(selected):continue
    rotations=array(obj.data.attributes['source_rotation'].data,'vector',3)[keep]
    scales=array(obj.data.attributes['source_scale'].data,'vector',3)[keep]
    for name in row['sources']:
        if name not in saved:
            result=mesh_data(bpy.data.objects[name],'Street_furniture_and_trees',True)
            if result is None:raise ValueError('Empty source tree template '+name)
            save(name,'tree-template',[result[:2]]);saved.add(name)
    for src,p0,r,s in zip(selected,p[keep],rotations,scales):
        linear=np.asarray(Euler(r.tolist()).to_matrix())@np.diag(s)
        instances.append(dict(id=f'{obj.name}:{src}',layer=obj.get('source_layer',obj.name),sourcePointIndex=int(src),templates=row['sources'],position=p0.tolist(),linear=linear.tolist(),sourceGLB=str(obj.get('source_glb',''))))
print('EXTRACT vegetation',len(instances),'templates',len(templates),flush=True)
manifest=dict(version=1,sourceBlend=bpy.data.filepath,sourceFidelity=dict(bpy.context.scene.items()).get('fidelity_repair_version'),boundsMSK=bounds,objects=objects,templates=templates,instances=instances,pbrSource=str(args.pbr_source.resolve()),sourceOrigin=source['origin'])
(args.output/'extraction.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
print('EXTRACTION COMPLETE',flush=True)
