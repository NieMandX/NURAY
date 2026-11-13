from pathlib import Path
import json,struct,hashlib,shutil,numpy as np
from canonical_store import copy_asset
import argparse
p=argparse.ArgumentParser(description='Rebind splat roots to a verified local relocation, retaining every other matrix.')
for key in ('city','parent-city','splats','output'):p.add_argument('--'+key,type=Path,required=True)
a=p.parse_args();city=a.city;oldcity=a.parent_city;prior=a.splats;out=a.output
assert not out.exists();shutil.copytree(prior,out,copy_function=copy_asset)
gs=json.loads((out/'vegetation.json').read_text());report=json.loads((city/'plant-relocation.json').read_text())
with (city/'merged/model.glb').open('rb')as f:
 f.seek(12);size,_=struct.unpack('<II',f.read(8));header=f.read(size);doc=json.loads(header);meta=doc['extras']['nuray'];view=doc['bufferViews'][meta['transformsView']];f.seek(28+size+view['byteOffset']);matrices=np.frombuffer(f.read(view['byteLength']),'<f4').reshape(-1,12)
byinst={r['sourceInstance']:r for r in report['records']};count=0
for inst in gs['instances']:
 if inst['sourceInstance']not in byinst:continue
 r=byinst[inst['sourceInstance']];m=matrices[inst['sourceInstance']]
 np.testing.assert_array_equal(m,np.array(r['matrix'],dtype='<f4'))
 assert inst['sourceDraw']==r['sourceDraw'] and inst['matrix']==r['originalSplatMatrix']
 for j in (3,7,11):inst['matrix'][j]=float(m[j])
 count+=1
assert count==report['moved']
gs['sourceHeaderSha256']=hashlib.sha256(header).hexdigest();gs['placement']='Approved source placements except user-requested nearest-green relocations; original observations preserved in city plant-relocation.json. Same sourceInstance/sourceDraw identity, type, crown scale, yaw and appearance.'
gs['relocation']={'city':city.name,'parent':prior.name,'moved':count};(out/'vegetation.json').write_text(json.dumps(gs,separators=(',',':'))+'\n')
a=json.loads((city/'merged/validation.json').read_text());b=json.loads((oldcity/'merged/validation.json').read_text());assert a['batches']==b['batches'];print('GS rebind',count,'unchanged mesh batches',len(a['batches']),'total',len(gs['instances']))
