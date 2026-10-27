"""Single GLB experiment: one static city node, shared GPU-instanced templates.

Exact packed vertex attributes survive. GPU allocation batches are linear byte
ranges, not geographic tiles. Standard glTF primitives share the same buffers;
NURAY extras permit bounded-memory streaming without decoding float normals.
"""
import argparse,collections,gzip,hashlib,json,shutil,struct
from pathlib import Path
import numpy as np
from scipy.spatial.transform import Rotation
from object_geometry import decode_normals

IDENTITY=[1,0,0,0,0,1,0,0,0,0,1,0]
LIMIT=4_000_000

def weld(words,indices):
    unique,remap=np.unique(words.view('V32').ravel(),return_inverse=True)
    result=unique.view('<u4').reshape(-1,8).copy();ix=remap[indices].astype('<u4')
    for start in range(0,len(indices),100000):
        assert np.array_equal(words[indices[start:start+100000]],result[ix[start:start+100000]])
    return result,ix

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--source',type=Path,required=True);ap.add_argument('--output',type=Path,required=True);ap.add_argument('--skip-trace',action='store_true',help='Export raster GLB without its optional ray acceleration cache');a=ap.parse_args()
    root=a.source;folder=root/'canonical/full';scene=json.loads((folder/'scene.json').read_text());catalog=json.loads((root/'tileset.json').read_text())
    assert json.loads((root/'validation.json').read_text())['passed']
    out=a.output;out.mkdir(parents=True,exist_ok=True);binary=out/'model.bin.tmp';stream=binary.open('wb');views=[];accessors=[];draws=[];images=[];textures=[];nodes=[];meshes=[dict(name='Город · вся статическая геометрия',primitives=[])];tinted={};mats=[]
    def view(data,**meta):
        while stream.tell()%4:stream.write(b'\0')
        b=memoryview(data).cast('B');idx=len(views);views.append(dict(buffer=0,byteOffset=stream.tell(),byteLength=len(b),**meta));stream.write(b);return idx
    def acc(buffer,count,kind,component=5126,offset=0,**meta):
        idx=len(accessors);accessors.append(dict(bufferView=buffer,byteOffset=offset,componentType=component,count=int(count),type=kind,**meta));return idx
    def array(data,kind,**meta):return acc(view(data),len(data),kind,**meta)
    # Small resources first so the streaming client can construct PBR materials
    # and all instance transforms before reading the large geometry ranges.
    for name in scene['textures']:
        p=folder/Path(name).name;raw=p.read_bytes();images.append(dict(name=name,bufferView=view(raw),mimeType='image/png' if raw[:8]==b'\x89PNG\r\n\x1a\n' else 'image/jpeg'));textures.append(dict(source=len(images)-1,sampler=0))
    image_ids={image['name']:i for i,image in enumerate(images)}
    for m in scene['materials']:
        pbr=dict(baseColorFactor=m['color']+[1],metallicFactor=m['metallic'],roughnessFactor=m['roughness'])
        if m.get('texture'):pbr['baseColorTexture']=dict(index=image_ids[Path(m['texture']).name])
        mat=dict(name=m['name'],doubleSided=True,pbrMetallicRoughness=pbr)
        if m.get('alphaCutoff',0)>0:mat.update(alphaMode='MASK',alphaCutoff=m['alphaCutoff'])
        mats.append(mat)
    groups=collections.defaultdict(list)
    for row in scene['instances']:groups[row['mesh']].append(row['matrix'])
    static=[c for c in scene['chunks'] if not c.get('instanced')];shared=[c for c in scene['chunks'] if c.get('instanced')]
    assert all(groups[c['id']]==[IDENTITY] for c in static)
    transforms=[IDENTITY];instance_info={}
    nodes.append(dict(name='Город · объединённый',mesh=0))
    for c in shared:
        matrices=np.asarray(groups[c['id']],dtype='<f4').reshape(-1,3,4);linear=matrices[:,:,:3].astype(float)
        scales=np.linalg.norm(linear,axis=1);rot=linear/scales[:,None,:]
        assert np.allclose(rot.transpose(0,2,1)@rot,np.eye(3),atol=1e-6) and (np.linalg.det(rot)>0).all()
        quat=Rotation.from_matrix(rot).as_quat().astype('<f4');scale=scales.astype('<f4');translation=matrices[:,:,3].copy()
        restored=Rotation.from_quat(quat).as_matrix()*scale[:,None,:]
        assert np.allclose(restored,linear,rtol=1e-6,atol=1e-6)
        attrs=dict(TRANSLATION=array(translation,'VEC3'),ROTATION=array(quat,'VEC4'),SCALE=array(scale,'VEC3'))
        meshid=len(meshes);meshes.append(dict(name=c['name'],primitives=[]));nodes.append(dict(name=c['name'],mesh=meshid,extensions={'EXT_mesh_gpu_instancing':dict(attributes=attrs)}))
        first=len(transforms);transforms.extend(groups[c['id']]);instance_info[c['id']]=(meshid,first,len(matrices))
    transform_array=np.asarray(transforms,dtype='<f4');transform_view=view(transform_array)
    pending_v=[];pending_i=[];count=0;source_triangles=0;source_vertices=0;welded_vertices=0;proof=[]
    def write_mesh(words,ix,meshid,first=0,instances=1,tint=False,label='city'):
        nonlocal welded_vertices
        original=len(words);words,ix=weld(words,ix);welded_vertices+=len(words)
        floats=words.view('<f4');position=floats[:,:3];minimum=position.min(0);maximum=position.max(0)
        material=words[ix[:,0],6]&0x7fffffff
        assert ((words[ix,6]&0x7fffffff)==material[:,None]).all()
        order=np.argsort(material,kind='stable');ix=ix[order];material=material[order]
        vb=view(words,byteStride=32,target=34962);ib=view(ix,target=34963)
        attributes=dict(POSITION=acc(vb,len(words),'VEC3',min=minimum.tolist(),max=maximum.tolist()),TEXCOORD_0=acc(vb,len(words),'VEC2',offset=16))
        normals=decode_normals(words[:,3]);attributes['NORMAL']=array(normals,'VEC3')
        if tint:
            colors=np.asarray([scene['materials'][int(m)]['color'] for m in words[:,6]&0x7fffffff],dtype='<f4')
            colors=np.clip(colors*np.where(floats[:,7]>0,floats[:,7],1)[:,None],0,1).astype('<f4');attributes['COLOR_0']=array(colors,'VEC3')
        mids,starts,lengths=np.unique(material,return_index=True,return_counts=True)
        for mid,start,length in zip(mids,starts,lengths):
            target=int(mid)
            if tint:
                if target not in tinted:
                    tinted[target]=len(mats);m=json.loads(json.dumps(mats[target]));m['pbrMetallicRoughness']['baseColorFactor']=[1,1,1,1];mats.append(m)
                target=tinted[target]
            meshes[meshid]['primitives'].append(dict(attributes=attributes,indices=acc(ib,length*3,'SCALAR',component=5125,offset=int(start)*12),material=target))
        bounds=dict(min=minimum.tolist(),max=maximum.tolist())
        if instances>1 or first:
            m=transform_array[first:first+instances].reshape(-1,3,4);corners=np.array([[x,y,z] for x in (minimum[0],maximum[0]) for y in (minimum[1],maximum[1]) for z in (minimum[2],maximum[2])]);corners=np.einsum('nij,kj->nki',m[:,:,:3],corners)+m[:,:,3,None].transpose(0,2,1);bounds=dict(min=corners.min((0,1)).tolist(),max=corners.max((0,1)).tolist())
        draws.append(dict(id=len(draws),name=label,vertexView=vb,indexView=ib,vertexBytes=words.nbytes,indexBytes=ix.nbytes,vertexCount=len(words),triangles=len(ix),instanceFirst=first,instanceCount=instances,instanced=bool(first),bounds=bounds))
        proof.append(dict(label=label,sourceVertices=original,vertices=len(words),triangles=len(ix),allVertexAttributesBitIdentical=True,packedSha256=hashlib.sha256(words.tobytes()+ix.tobytes()).hexdigest()))
        print('MERGED',len(draws),label,'vertices',original,'->',len(words),'triangles',len(ix),flush=True)
    def flush():
        nonlocal count
        if not pending_v:return
        write_mesh(np.concatenate(pending_v),np.concatenate(pending_i),0,label='city-'+str(len(draws)))
        pending_v.clear();pending_i.clear();count=0
    for c in static+shared:
        data=gzip.decompress((folder/Path(c['file']).name).read_bytes());words=np.frombuffer(data[:c['vertexBytes']],'<u4').reshape(-1,8);ix=np.frombuffer(data[c['vertexBytes']:],'<u4').reshape(-1,3)
        source_triangles+=len(ix);source_vertices+=len(words)
        if c.get('instanced'):
            flush();mesh,first,instances=instance_info[c['id']];write_mesh(words.copy(),ix.copy(),mesh,first,instances,c.get('vertexTint',False),c['name']);continue
        # Large source meshes are scanned in bounded blocks. No spatial grid,
        # clipping, geometry reconstruction or per-tile allocation is involved.
        for start in range(0,len(ix),500000):
            block=ix[start:start+500000];ids,remap=np.unique(block,return_inverse=True);vertices=words[ids].copy()
            if count+len(vertices)>LIMIT:flush()
            pending_v.append(vertices);pending_i.append(remap.reshape(-1,3).astype('<u4')+count);count+=len(vertices)
    flush();stream.close();binary_size=binary.stat().st_size
    meta={k:catalog[k] for k in ('regionName','origin','boundsMSK','extentMetres','witnessViews','crsProj','axes','geography') if k in catalog}
    meta.update(version=1,format='nuray-merged-glb-v1',sourceCatalog='../tileset.json',materials=scene['materials'],imageNames=image_ids,draws=draws,transformsView=transform_view,nodes=len(nodes),sourceTiles=len(catalog['tiles']))
    stats=dict(passed=True,staticCityObjects=1,sharedTemplateObjects=len(shared),objects=len(nodes),gpuBatches=len(draws),uniqueTriangles=source_triangles,expandedTriangles=sum(d['triangles']*d['instanceCount'] for d in draws),sourceVertices=source_vertices,vertices=welded_vertices,geometryBytes=sum(d['vertexBytes']+d['indexBytes'] for d in draws)+transform_array.nbytes,sharedInstances=sum(d['instanceCount'] for d in draws if d['instanced']),allVertexAttributesBitIdentical=True,instanceMatricesPreserved=True,sourceValidationSha256=hashlib.sha256((root/'validation.json').read_bytes()).hexdigest(),batches=proof)
    assert source_triangles==scene['stats']['uniqueTriangles'];assert stats['expandedTriangles']==scene['stats']['expandedTriangles']
    meta['stats']={k:v for k,v in stats.items() if k!='batches'}
    doc=dict(asset=dict(version='2.0',generator='NURAY merged city experiment'),scene=0,scenes=[dict(nodes=list(range(len(nodes))))],nodes=nodes,meshes=meshes,materials=mats,buffers=[dict(byteLength=binary_size)],bufferViews=views,accessors=accessors,images=images,textures=textures,samplers=[dict(magFilter=9729,minFilter=9987,wrapS=10497,wrapT=10497)],extensionsUsed=['EXT_mesh_gpu_instancing'],extensionsRequired=['EXT_mesh_gpu_instancing'],extras=dict(nuray=meta))
    header=json.dumps(doc,separators=(',',':')).encode();header+=b' '*((-len(header))%4);padding=(-binary_size)%4;size=28+len(header)+binary_size+padding
    if size>=2**32:raise ValueError('Merged asset exceeds the GLB 32-bit length limit')
    target=out/'model.glb.tmp'
    with target.open('wb') as f,binary.open('rb') as src:
        f.write(struct.pack('<4sII',b'glTF',2,size));f.write(struct.pack('<I4s',len(header),b'JSON'));f.write(header);f.write(struct.pack('<I4s',binary_size+padding,b'BIN\0'));shutil.copyfileobj(src,f,8*1024*1024);f.write(b'\0'*padding)
    target.replace(out/'model.glb');binary.unlink();stats.update(glbBytes=size,gltfPrimitives=sum(len(m['primitives']) for m in meshes))
    (out/'validation.json').write_text(json.dumps(stats,separators=(',',':')));(out/'metadata.json').write_text(json.dumps(meta,separators=(',',':')))
    print('MERGED GLB PASSED',json.dumps({k:v for k,v in stats.items() if k!='batches'}),flush=True)
    if not a.skip_trace:
        from build_merged_trace import build
        build((out/'model.glb').resolve())

if __name__=='__main__':main()
