"""Attribute-preserving object clipping and the existing NURAY vertex format."""
import gzip, json, struct
from pathlib import Path
import numpy as np

AXES=np.array([[1,0,0],[0,0,1],[0,-1,0]],dtype=float)

def clip_triangle(triangle,bounds):
    poly=list(triangle)
    for axis,edge,sign in ((0,bounds[0],1),(0,bounds[2],-1),(2,bounds[1],1),(2,bounds[3],-1)):
        out=[]
        for i,p in enumerate(poly):
            q=poly[(i+1)%len(poly)];a=(p[axis]-edge)*sign;b=(q[axis]-edge)*sign
            if a>=0:out.append(p)
            if (a>=0)!=(b>=0):
                v=p+(q-p)*(a/(a-b));v[axis]=edge;out.append(v)
        poly=out
        if len(poly)<3:return []
    return [np.array([poly[0],poly[i],poly[i+1]]) for i in range(1,len(poly)-1)]

def clip_triangles(tris,materials,bounds):
    p=tris[:,:,:3];inside=((p[:,:,0]>=bounds[0])&(p[:,:,0]<=bounds[2])&(p[:,:,2]>=bounds[1])&(p[:,:,2]<=bounds[3])).all(1)
    outside=(p[:,:,0].max(1)<bounds[0])|(p[:,:,0].min(1)>bounds[2])|(p[:,:,2].max(1)<bounds[1])|(p[:,:,2].min(1)>bounds[3])
    extra=[];ids=[]
    for t,m in zip(tris[~inside&~outside],materials[~inside&~outside]):
        parts=clip_triangle(t,bounds);extra.extend(parts);ids.extend([m]*len(parts))
    return (np.concatenate((tris[inside],extra)) if extra else tris[inside],np.concatenate((materials[inside],ids)).astype(np.uint32))

def pack(triangles,materials,path,tints=None):
    if not len(triangles):return None
    triangles=np.asarray(triangles,dtype='<f4');p=triangles[:,:,:3];n=triangles[:,:,3:6]
    n=n/np.maximum(np.abs(n).sum(2,keepdims=True),1e-20);xy=n[:,:,:2].copy();mask=n[:,:,2]<0
    xy[mask]=(1-np.abs(xy[mask][:,::-1]))*np.where(xy[mask]>=0,1,-1)
    octn=np.round(np.clip(xy,-1,1)*32767).astype('<i2').reshape(-1,2)
    words=np.zeros((len(triangles)*3,8),dtype='<u4');floats=words.view('<f4')
    floats[:,:3]=p.reshape(-1,3);words[:,3]=octn.copy().view('<u4').ravel();floats[:,4:6]=triangles[:,:,6:8].reshape(-1,2)
    words[:,6]=np.repeat(materials,3).astype(np.uint32)|0x80000000
    if tints is not None:
        tints=np.asarray(tints,dtype='<f4').reshape(-1)
        assert len(tints)==len(words) and np.isfinite(tints).all() and np.all(tints>0)
        floats[:,7]=tints
    verts,ix=np.unique(words,axis=0,return_inverse=True);ix=ix.reshape(-1,3).astype('<u4')
    pp=verts.view('<f4')[ix,:3];keep=np.linalg.norm(np.cross(pp[:,1]-pp[:,0],pp[:,2]-pp[:,0]),axis=1)>1e-9;ix=ix[keep]
    if not len(ix):return None
    # Match transport-tile compression. Level 9 costs minutes on long fence
    # meshes without changing a single decoded vertex, index or attribute.
    with gzip.GzipFile(filename=str(path),mode='wb',mtime=0,compresslevel=6) as f:f.write(verts.tobytes());f.write(ix.tobytes())
    return dict(vertexBytes=verts.nbytes,vertexCount=len(verts),triangles=len(ix),bounds=dict(min=pp[keep].min((0,1)).tolist(),max=pp[keep].max((0,1)).tolist()))

def decode_normals(words):
    xy=words.copy().view('<i2').reshape(-1,2).astype(float)/32767
    n=np.column_stack((xy,1-np.abs(xy).sum(1)));mask=n[:,2]<0
    n[mask,:2]=(1-np.abs(xy[mask,::-1]))*np.where(xy[mask]>=0,1,-1)
    return (n/np.linalg.norm(n,axis=1,keepdims=True)).astype('<f4')

def export_glb(manifest,folder):
    """One standard GLB with shared tree meshes and one node per occurrence."""
    binary=bytearray();views=[];accessors=[];meshes=[];nodes=[];images=[];textures=[];tinted_materials={}
    def view(data):
        while len(binary)%4:binary.append(0)
        views.append(dict(buffer=0,byteOffset=len(binary),byteLength=len(data)));binary.extend(data);return len(views)-1
    def accessor(a,kind,component=5126):
        row=dict(bufferView=view(a.tobytes()),componentType=component,count=len(a),type=kind)
        if kind=='VEC3':row.update(min=a.min(0).tolist(),max=a.max(0).tolist())
        accessors.append(row);return len(accessors)-1
    for c in manifest['chunks']:
        raw=gzip.decompress((folder/Path(c['file']).name).read_bytes());u=np.frombuffer(raw[:c['vertexBytes']],'<u4').reshape(-1,8);v=u.view('<f4');ix=np.frombuffer(raw[c['vertexBytes']:],'<u4').reshape(-1,3)
        attrs=dict(POSITION=accessor(v[:,:3].copy(),'VEC3'),NORMAL=accessor(decode_normals(u[:,3]),'VEC3'),TEXCOORD_0=accessor(v[:,4:6].copy(),'VEC2'))
        mids=u[ix[:,0],6]&0x7fffffff;primitives=[]
        if c.get('vertexTint'):
            colors=np.asarray([manifest['materials'][int(m)]['color'] for m in u[:,6]&0x7fffffff],dtype='<f4')
            colors=np.clip(colors*np.where(v[:,7]>0,v[:,7],1)[:,None],0,1).astype('<f4')
            attrs['COLOR_0']=accessor(colors,'VEC3')
        for material in np.unique(mids):
            target=int(material)
            if c.get('vertexTint'):
                if target not in tinted_materials:tinted_materials[target]=len(manifest['materials'])+len(tinted_materials)
                target=tinted_materials[target]
            primitives.append(dict(attributes=attrs,indices=accessor(ix[mids==material].ravel().copy(),'SCALAR',5125),material=target))
        meshes.append(dict(name=c['name'],primitives=primitives))
    for i in manifest['instances']:
        matrix=np.eye(4);matrix[:3]=np.asarray(i['matrix']).reshape(3,4)
        nodes.append(dict(mesh=i['mesh'],matrix=matrix.T.ravel().tolist(),name=i.get('id',manifest['chunks'][i['mesh']]['name'])))
    texture_ids={};mats=[]
    for m in manifest['materials']:
        pbr=dict(baseColorFactor=m['color']+[1],metallicFactor=m['metallic'],roughnessFactor=m['roughness'])
        if m.get('texture'):
            file=m['texture']
            if file not in texture_ids:
                raw=(folder/Path(file).name).read_bytes();image=len(images);images.append(dict(bufferView=view(raw),mimeType='image/png' if raw[:8]==b'\x89PNG\r\n\x1a\n' else 'image/jpeg'))
                texture_ids[file]=len(textures);textures.append(dict(source=image))
            pbr['baseColorTexture']=dict(index=texture_ids[file])
        mat=dict(name=m['name'],doubleSided=True,pbrMetallicRoughness=pbr)
        if m.get('alphaCutoff',0)>0:mat.update(alphaMode='MASK',alphaCutoff=m['alphaCutoff'])
        mats.append(mat)
    for source in tinted_materials:
        mat=json.loads(json.dumps(mats[source]));mat['pbrMetallicRoughness']['baseColorFactor']=[1,1,1,1]
        mats.append(mat)
    gltf=dict(asset=dict(version='2.0',generator='NURAY tiled city'),scene=0,scenes=[dict(nodes=list(range(len(nodes))))],nodes=nodes,meshes=meshes,materials=mats,buffers=[dict(byteLength=len(binary))],bufferViews=views,accessors=accessors,images=images,textures=textures,extras=dict(originMSK=manifest['origin']))
    j=json.dumps(gltf,separators=(',',':')).encode();j+=b' '*((-len(j))%4);binary+=b'\0'*((-len(binary))%4)
    # Stream the already assembled chunks rather than allocating several extra
    # copies of a multi-GB monolithic export during byte concatenation.
    temporary=folder/'model.glb.tmp'
    with temporary.open('wb') as stream:
        stream.write(struct.pack('<4sII',b'glTF',2,28+len(j)+len(binary)))
        stream.write(struct.pack('<I4s',len(j),b'JSON'));stream.write(j)
        stream.write(struct.pack('<I4s',len(binary),b'BIN\0'));stream.write(binary)
    temporary.replace(folder/'model.glb')
    for name in ('model.glb.gz','model.glb.archive.json'):
        if (folder/name).exists():(folder/name).unlink()
