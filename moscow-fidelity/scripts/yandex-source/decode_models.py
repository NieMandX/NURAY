"""Decode captured glTF and Draco into original root-node triangle groups.

Dependency: DracoPy==2.2.0 (https://github.com/seung-lab/DracoPy).
No Blender/GPU context is required. Preserve node transforms and embedded images.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct

import DracoPy
import numpy as np
from scipy.spatial.transform import Rotation


def decode(path, output):
    raw = path.read_bytes()
    assert struct.unpack_from('<4sII',raw)==(b'glTF',2,len(raw))
    size = struct.unpack_from('<I',raw,12)[0]
    doc = json.loads(raw[20:20+size]);binary=raw[28+size:]
    assert not doc.get('skins'), 'Skinning requires a bind-pose adapter'
    def view(index):
        v=doc['bufferViews'][index]
        assert v.get('buffer',0)==0
        return binary[v.get('byteOffset',0):v.get('byteOffset',0)+v['byteLength']]
    def accessor(index):
        a=doc['accessors'][index];v=doc['bufferViews'][a['bufferView']]
        assert not a.get('sparse')
        dtype={5120:'i1',5121:'u1',5122:'<i2',5123:'<u2',5125:'<u4',5126:'<f4'}[a['componentType']]
        width={'SCALAR':1,'VEC2':2,'VEC3':3,'VEC4':4}[a['type']]
        data=np.ndarray((a['count'],width),dtype=dtype,buffer=view(a['bufferView']),
            offset=a.get('byteOffset',0),strides=(v.get('byteStride',np.dtype(dtype).itemsize*width),np.dtype(dtype).itemsize)).copy()
        if a.get('normalized'):
            info=np.iinfo(dtype);data=np.maximum(data.astype(float)/info.max,-1)
        return data
    meshes={}
    for i,mesh in enumerate(doc['meshes']):
        rows=[]
        for prim in mesh['primitives']:
            assert prim.get('mode',4)==4
            extension=prim.get('extensions',{}).get('KHR_draco_mesh_compression')
            if extension:
                decoded=DracoPy.decode(view(extension['bufferView']))
                attrs={name:decoded.get_attribute_by_unique_id(uid)['data'] for name,uid in extension['attributes'].items()}
                indices=decoded.faces.astype(np.int64)
                for name,index in prim['attributes'].items():
                    if name not in attrs:attrs[name]=accessor(index)
            else:
                attrs={name:accessor(index) for name,index in prim['attributes'].items()}
                indices=accessor(prim['indices']).reshape(-1,3) if 'indices' in prim else np.arange(len(attrs['POSITION'])).reshape(-1,3)
            pos=attrs['POSITION'][indices].astype(float)
            normal=attrs.get('NORMAL')
            if normal is None:
                normal=np.cross(pos[:,1]-pos[:,0],pos[:,2]-pos[:,0]);normal=np.repeat(normal[:,None,:],3,axis=1)
            else:normal=normal[indices].astype(float)
            normal/=np.maximum(np.linalg.norm(normal,axis=2,keepdims=True),1e-20)
            uv=attrs['TEXCOORD_0'][indices] if 'TEXCOORD_0' in attrs else np.zeros((len(indices),3,2))
            tint=np.ones((len(indices),3,1))
            if 'COLOR_0' in attrs:
                colors=attrs['COLOR_0'].astype(float)
                source_color=doc['accessors'][prim['attributes']['COLOR_0']]
                if source_color.get('normalized') and colors.max()>1:
                    colors/={5121:255,5123:65535}[source_color['componentType']]
                assert np.allclose(colors[:,:3],colors[:,0:1]), 'Non-grey vertex colours need an RGB adapter'
                # The source material is OPAQUE; its vertex alpha is ignored.
                tint=colors[indices,0:1]
            assert len(indices)*3==doc['accessors'][prim['indices']]['count']
            rows.append((np.concatenate([pos,normal,uv,tint],axis=2),np.full(len(indices),prim.get('material',-1),dtype=np.int32)))
        meshes[i]=rows
    roots={}
    def walk(index,parent,root_index):
        node=doc['nodes'][index]
        if 'matrix' in node:matrix=np.array(node['matrix']).reshape(4,4).T
        else:
            matrix=np.eye(4);matrix[:3,:3]=Rotation.from_quat(node.get('rotation',[0,0,0,1])).as_matrix()*node.get('scale',[1,1,1]);matrix[:3,3]=node.get('translation',[0,0,0])
        matrix=parent@matrix
        if 'mesh' in node:
            for attrs,ids in meshes[node['mesh']]:
                result=attrs.copy();result[:,:,:3]=result[:,:,:3]@matrix[:3,:3].T+matrix[:3,3]
                result[:,:,3:6]=result[:,:,3:6]@np.linalg.inv(matrix[:3,:3])
                result[:,:,3:6]/=np.maximum(np.linalg.norm(result[:,:,3:6],axis=2,keepdims=True),1e-20)
                if np.linalg.det(matrix[:3,:3])<0:result=result[:,[0,2,1]]
                roots.setdefault(root_index,[]).append((result.astype('<f4'),ids))
        for child in node.get('children',[]):walk(child,matrix,root_index)
    for node in doc['scenes'][doc.get('scene',0)]['nodes']:walk(node,np.eye(4),node)
    stem=path.stem
    manifest={'source':str(path),'sha256':hashlib.sha256(raw).hexdigest(),'nodes':{},'materials':[],
        'animationPolicy':'static source node transforms; animation tracks not played',
        'sourceAnimations':len(doc.get('animations',[]))}
    for material in doc.get('materials',[]):
        pbr=material.get('pbrMetallicRoughness',{});texture=None
        if 'baseColorTexture' in pbr:
            t=pbr['baseColorTexture'];assert t.get('texCoord',0)==0 and not t.get('extensions')
            image=doc['images'][doc['textures'][t['index']]['source']];data=view(image['bufferView'])
            suffix='.png' if data[:8]==b'\x89PNG\r\n\x1a\n' else '.jpg'
            texture='yandex-'+hashlib.sha256(data).hexdigest()[:20]+suffix;(output/texture).write_bytes(data)
        manifest['materials'].append(dict(name=f"Yandex · {stem} · {len(manifest['materials'])}",
            color=pbr.get('baseColorFactor',[1,1,1,1])[:3],roughness=pbr.get('roughnessFactor',1),metallic=pbr.get('metallicFactor',0),
            ior=material.get('extensions',{}).get('KHR_materials_ior',{}).get('ior',1.5),texture='textures/'+texture if texture else None,
            alphaCutoff=material.get('alphaCutoff',.5) if material.get('alphaMode')=='MASK' else 0,family='yandex-source-model',kind=1))
    for index,rows in roots.items():
        triangles=np.concatenate([v[0] for v in rows]);ids=np.concatenate([v[1] for v in rows]);file=f'{stem}-node-{index}.npz'
        np.savez_compressed(output/file,triangles=triangles[:,:,:8],tints=triangles[:,:,8],materials=ids)
        manifest['nodes'][str(index)]=dict(file=file,triangles=len(triangles),bounds=dict(min=triangles[:,:,:3].min((0,1)).tolist(),max=triangles[:,:,:3].max((0,1)).tolist()))
    (output/(stem+'.json')).write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    print('DECODED',path.name,len(roots),sum(v['triangles'] for v in manifest['nodes'].values()),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('source',type=Path);a=p.parse_args()
    output=a.source/'decoded-models';output.mkdir(exist_ok=True)
    for path in sorted([*(a.source/'models').glob('*.glb'),*(a.source/'decoded').glob('*.data3d')]):decode(path,output)
