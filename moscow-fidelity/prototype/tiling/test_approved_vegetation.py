"""Check approved colors and smoothing through the city binary and standard GLB."""
import gzip, json, struct, tempfile
from pathlib import Path
import numpy as np
from approved_vegetation import ASSETS, FAMILIES, palette_for, geometry, read_glb, digest
from object_geometry import pack, export_glb, decode_normals

catalog=json.loads((ASSETS/'catalog.json').read_text())
index=json.loads((ASSETS/'library/index.json').read_text())
models={m['id']:m for m in index['models']}
assert len({layer for layer,_,_ in FAMILIES})==len({m for _,_,m in FAMILIES})==9
for model in models.values():
    source=ASSETS/model['file'];assert digest(source)==model['glbSha256']
    pal=palette_for(catalog['materials'],model['foliageColor'])
    a,m,tints,expected=geometry(source,pal,1.)
    doc,p,n,_,_=read_glb(source)
    assert np.array_equal(a[:,:,:3],p) and np.array_equal(a[:,:,3:6],n)
    with tempfile.TemporaryDirectory() as tmp:
        folder=Path(tmp);meta=pack(a,m,folder/'mesh.bin.gz',tints=tints)
        raw=gzip.decompress((folder/'mesh.bin.gz').read_bytes())
        words=np.frombuffer(raw[:meta['vertexBytes']],'<u4').reshape(-1,8);v=words.view('<f4')
        ix=np.frombuffer(raw[meta['vertexBytes']:],'<u4').reshape(-1,3)
        assert np.array_equal(v[ix,:3],p) and np.array_equal(v[ix,7],tints)
        assert np.max(np.abs(decode_normals(words[:,3])[ix]-n))<.00015
        manifest=dict(origin=[0,0,0],materials=pal,chunks=[dict(id=0,name=model['id'],file='mesh.bin.gz',vertexTint=True,**meta)],
            instances=[dict(mesh=0,matrix=[1,0,0,0,0,1,0,0,0,0,1,0])])
        export_glb(manifest,folder)
        raw=(folder/'model.glb').read_bytes();length=struct.unpack_from('<I',raw,12)[0]
        output=json.loads(raw[20:20+length]);binary=raw[28+length:]
        def acc(index):
            a=output['accessors'][index];b=output['bufferViews'][a['bufferView']]
            return np.frombuffer(binary,'<f4' if a['componentType']==5126 else '<u4',
                a['count']*({'VEC3':3,'VEC2':2,'SCALAR':1}[a['type']]),b.get('byteOffset',0)).reshape(a['count'],-1)
        for prim in output['meshes'][0]['primitives']:
            c=acc(prim['attributes']['COLOR_0']);tri=acc(prim['indices']).reshape(-1,3)
            packed_ids=words[tri[:,0],6]&0x7fffffff
            assert len(set(packed_ids))==1
            original_material=pal[int(packed_ids[0])]
            pbr=output['materials'][prim['material']]['pbrMetallicRoughness']
            assert pbr['baseColorFactor']==[1,1,1,1]
            assert pbr['roughnessFactor']==original_material['roughness']
            assert pbr['metallicFactor']==original_material['metallic']
            expected_color=np.asarray(original_material['color'])*v[tri,7,None]
            assert np.allclose(c[tri],expected_color,rtol=0,atol=8e-8)
        # Reserved zeros on pre-library meshes retain the old format and colors.
        legacy=pack(a,m,folder/'legacy.bin.gz')
        raw=gzip.decompress((folder/'legacy.bin.gz').read_bytes())
        assert not np.frombuffer(raw[:legacy['vertexBytes']],'<u4').reshape(-1,8)[:,7].any()
    print('PASS',model['id'],len(a),'triangles: approved positions, normals, curvature, PBR, city GLB and neutral legacy tint')

# Nonuniform scale must transform the tangent plane as well as the silhouette.
# This catches leaving old normals on a narrowed or vertically stretched crown.
model=models['spruce'];source=ASSETS/model['file']
pal=palette_for(catalog['materials'],model['foliageColor'])
original,mats,tints,colors=geometry(source,pal,1.)
normals=original[:,:,3:6].astype(float)
tangent_a=np.cross(normals,[1.,0.,0.]);tangent_b=np.cross(normals,[0.,0.,1.])
for axes in ([1.,2.,1.],[2/3,1.,2/3]):
    scaled,m2,t2,c2=geometry(source,pal,1.,axes)
    assert np.allclose(np.linalg.norm(scaled[:,:,3:6],axis=2),1,atol=1e-7)
    for tangent in (tangent_a,tangent_b):
        assert np.abs(np.sum(scaled[:,:,3:6]*(tangent*axes),axis=2)).max()<2e-7
    for axis,factor in enumerate(axes):
        if factor==1:assert np.array_equal(scaled[:,:,axis],original[:,:,axis])
        else:assert np.allclose(scaled[:,:,axis],original[:,:,axis]*factor,rtol=1e-7,atol=1e-6)
    assert np.array_equal(mats,m2) and np.array_equal(tints,t2) and np.array_equal(colors,c2)
print('PASS scene proportions: unchanged axes, tangent-plane normals, materials and curvature tint')
