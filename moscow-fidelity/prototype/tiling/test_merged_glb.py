import json,struct,hashlib
from pathlib import Path
import numpy as np
from export_merged_glb import weld
from merged_asset import read_container

def validate(path):
    path=Path(path)
    doc,binary,offset,header_sha,total=read_container(path)
    n=binary.stat().st_size-offset
    assert len(doc['buffers'])==1 and doc['buffers'][0]['byteLength']<=n<=doc['buffers'][0]['byteLength']+3
    buf=np.memmap(binary,dtype='u1',mode='r',offset=offset);meta=doc['extras']['nuray'];proof=json.loads((path.parent/'validation.json').read_text())
    assert proof['passed'] and len(meta['draws'])==len(proof['batches'])
    for v in doc['bufferViews']:assert 0<=v.get('byteOffset',0) and v.get('byteOffset',0)+v['byteLength']<=n
    def data(i):
        v=doc['bufferViews'][i];return buf[v['byteOffset']:v['byteOffset']+v['byteLength']]
    for d,p in zip(meta['draws'],proof['batches']):
        vertices=data(d['vertexView']);indices=data(d['indexView']);h=hashlib.sha256();h.update(vertices);h.update(indices);assert h.hexdigest()==p['packedSha256']
        ix=indices.view('<u4');assert ix.size==d['triangles']*3 and ix.max()<d['vertexCount']
    for mesh in doc['meshes']:
        for p in mesh['primitives']:
            pos=doc['accessors'][p['attributes']['POSITION']];normal=doc['accessors'][p['attributes']['NORMAL']];uv=doc['accessors'][p['attributes']['TEXCOORD_0']]
            assert pos['count']==normal['count']==uv['count'];assert p['material']<len(doc['materials'])
            a=doc['accessors'][p['indices']];assert a['count']%3==0 and a['byteOffset']+a['count']*4<=doc['bufferViews'][a['bufferView']]['byteLength']
    for node in doc['nodes'][1:]:
        attrs=node['extensions']['EXT_mesh_gpu_instancing']['attributes'];assert len({doc['accessors'][i]['count'] for i in attrs.values()})==1
    assert len(doc['nodes'])==proof['objects']==meta['nodes']
    if path.suffix=='.gltf':assert doc['buffers'][0]['uri']=='model.bin'
    else:assert not any('uri' in b for b in doc['buffers'])
    assert all('bufferView' in i for i in doc['images'])
    result=dict(passed=True,format=path.suffix[1:],assetBytes=total,headerSha256=header_sha,
                geometryBatches=len(meta['draws']),objects=len(doc['nodes']),packedGeometryHashesVerified=True)
    print('MERGED STRUCTURE, RESOURCES, ALL PACKED GEOMETRY HASHES AND INSTANCING PASS',json.dumps(result),flush=True)
    return result

if __name__=='__main__':
    import sys
    a=np.arange(40,dtype='<u4').reshape(5,8);a[4]=a[1];ix=np.array([[1,2,3],[4,2,0]],dtype='<u4');v,i=weld(a,ix);assert len(v)==4 and np.array_equal(a[ix],v[i])
    validate(Path(sys.argv[1]))
