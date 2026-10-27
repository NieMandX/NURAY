"""Source-class selection, boundary splitting and material-only invariants."""
import tempfile,gzip,json,os,subprocess,struct
from pathlib import Path
import numpy as np
import shapely as sh
from PIL import Image
from pedestrian_materials import RULES,TYPES,FIRST_MATERIAL,materials,make_textures,is_paving
from semantics import classify
from material_remap import remap_many
from prepare_pedestrian_materials import choose_faces
from build import MATERIALS

m=materials(MATERIALS[0][1]);assert len(m)==5
assert np.allclose(m[0]['color'],np.array(MATERIALS[0][1])*1.5)
for layer,r in RULES.items():
    s=classify(layer,{},'polygon')
    assert s['material']==r['material'] and s['styleId']==r['styleId'] and s['rank']==60
    assert is_paving(dict(kind='land',purpose='pedestrian',surfaceType=r['kind'],material=s['material']))
assert classify('Pedestrian_quarter',{},'polygon')['material']==7
assert classify('Roadbed_underpasses',{},'polygon')['material']==7
assert classify('Main_Roadbed',{},'polygon')['material']==0
assert not is_paving(dict(kind='land',purpose='motor-traffic',surfaceType='asphalt',material=0))

v=np.zeros((5,8),'<u4');v.view('<f4')[:,:3]=[[0,0,0],[1,0,0],[0,0,-1],[1,0,-1],[2,0,0]]
v.view('<f4')[:,4:6]=v.view('<f4')[:,[0,2]];v[:,6]=0x80000007
ix=np.array([[0,1,2],[1,3,2],[1,4,3]],'<u4')
raw=v.tobytes()+ix.tobytes();c=dict(vertexBytes=v.nbytes,triangles=3)
rows=[dict(owner='stone',material=7,heightPlane=[0,0,0],geometry=sh.geometry.mapping(sh.Polygon([[0,0],[1,0],[0,1]]))),
      dict(owner='wood',material=7,heightPlane=[0,0,0],geometry=sh.geometry.mapping(sh.Polygon([[1,0],[1,1],[0,1]])))]
labels,area,escape=choose_faces(raw,c,np.zeros(3),rows,{'stone':144,'wood':147})
assert labels.tolist()==[144,147,-1] and escape==0 and area=={144:.5,147:.5}
tail=b'unchanged BVH+lineage'
out,vb,_=remap_many(raw+tail,v.nbytes,ix.nbytes,labels)
u=np.frombuffer(out[:vb],'<u4').reshape(-1,8);j=np.frombuffer(out[vb:vb+ix.nbytes],'<u4').reshape(-1,3)
expected=v[ix].copy();expected[0,:,6]=0x80000090;expected[1,:,6]=0x80000093
assert np.array_equal(u[j],expected) and out[-len(tail):]==tail

with tempfile.TemporaryDirectory() as folder:
    p=Path(folder);textures=make_textures(p);again=make_textures(p/'again');assert textures==again
    for name in textures:
        image=np.array(Image.open(p/name));assert np.array_equal(image[0],image[-1]) and np.array_equal(image[:,0],image[:,-1])
    source=dict(features=[dict(id='a',semantics={'material':7}),dict(id='b',semantics={'material':7})],
                surfaces=[dict(id='a:1',material=7),dict(id='b:1',material=7),dict(id='untouched',material=25)],geometryRevision={'type':'parent'})
    patch=dict(features=[dict(id='a',semantics={'material':144})],surfaces=[dict(id='a:1',material=144,surfaceType='stone',styleId='829125'),dict(id='b:1',material=147,surfaceType='wood',styleId='863950')],geometryRevision={'type':'pedestrian-materials'})
    (p/'input.gz').write_bytes(gzip.compress(json.dumps(source).encode()));(p/'patch.json').write_text(json.dumps(patch))
    subprocess.run([os.environ['NODE'],str(Path(__file__).with_name('restyle_registry.mjs')),str(p/'input.gz'),str(p/'output.gz'),str(p/'patch.json')],check=True)
    result=json.loads(gzip.decompress((p/'output.gz').read_bytes()))
    assert result['surfaces'][0]['material']==144 and result['surfaces'][1]['material']==147
    assert result['surfaces'][2]==source['surfaces'][2] and result['features'][1]==source['features'][1]
print('Passed: five source types, asphalt x1.5, final ownership, shared boundary vertices, exact UV/geometry/BVH preservation, deterministic seamless textures, multi-material registry.')
