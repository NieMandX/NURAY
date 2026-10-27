"""Land-use priority, shared vertices and lossless sparse registry rewriting."""
import gzip,json,os,subprocess,tempfile
from pathlib import Path
import numpy as np
from semantics import classify,GREEN
from build import MATERIALS
from cemetery_cover import LAYER,MATERIAL_INDEX,owns_surface,color
from material_remap import remap

cem=classify(LAYER,{'db_road_part':'roadbed_flat'},'polygon')
assert cem['material']==MATERIAL_INDEX<len(MATERIALS)
assert cem['purpose']=='land-cover' and LAYER not in GREEN and cem['rank']==20
assert color()[1]>color()[0]>color()[2]
for layer in ('Pedestrian_quarter','Immersive_park_polygon_pedestrian_stone',
              'Immersive_park_polygon_blue','Internal_lawn','Main_Roadbed','Water_area'):
    assert classify(layer,{},'polygon')['rank']>cem['rank']
assert owns_surface(dict(kind='land',owner='cem'),{'cem'})
assert not owns_surface(dict(kind='land',owner='path'),{'cem'})
assert not owns_surface(dict(kind='curb_top',owner='cem'),{'cem'})

v=np.zeros((4,8),'<u4');v.view('<f4')[:,:3]=[[0,0,0],[1,0,0],[0,0,1],[1,0,1]]
v[:,6]=0x80000001;ix=np.array([[0,1,2],[1,3,2]],'<u4');tail=b'unchanged BVH and lineage'
raw=v.tobytes()+ix.tobytes()+tail
out,vb,splits=remap(raw,v.nbytes,ix.nbytes,np.array([True,False]),142)
assert splits==2 and out[-len(tail):]==tail
u=np.frombuffer(out[:vb],'<u4').reshape(-1,8)
j=np.frombuffer(out[vb:vb+ix.nbytes],'<u4').reshape(-1,3)
assert np.all(u[j[0],6]==0x8000008e) and np.array_equal(u[j[1]],v[ix[1]])
assert remap(raw,v.nbytes,ix.nbytes,np.array([False,False]),142)[0]==raw

with tempfile.TemporaryDirectory() as folder:
    root=Path(folder)
    row=dict(id='surface:1',owner='cem',kind='land',material=1,
             geometry={'type':'Polygon','coordinates':[[[0,0],[1,0],[0,1],[0,0]]]})
    data=dict(name='escaped \\" braces } [',features=[dict(id='cem',semantics={'material':1}),dict(id='path',semantics={'material':7})],
              geometryRevision={'type':'parent'},surfaces=[row,dict(row,id='surface:2',owner='path',material=7)],
              extra={'nested':[{'id':'cem','material':1}]})
    patch=dict(material=142,features=[dict(id='cem',semantics=dict(cem,material=142))],surfaceIds=['surface:1'],geometryRevision={'type':'cemetery-cover'})
    (root/'in.gz').write_bytes(gzip.compress(json.dumps(data).encode()))
    (root/'patch.json').write_text(json.dumps(patch))
    subprocess.run([os.environ.get('NODE','node'),str(Path(__file__).with_name('restyle_registry.mjs')),
                    str(root/'in.gz'),str(root/'out.gz'),str(root/'patch.json')],check=True)
    result=json.loads(gzip.decompress((root/'out.gz').read_bytes()))
    data['features'][0]['semantics']=patch['features'][0]['semantics']
    data['surfaces'][0].update(material=142,surfaceType='cemetery-cover',styleId=None)
    data['geometryRevision']=patch['geometryRevision']
    assert data==result
print('Passed: cemetery priority, paving/planting exclusion, unchanged geometry, shared-vertex material split, sparse registry update.')
