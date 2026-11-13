"""Selectively update the paint of a crossfall release from its parent."""
import argparse,json
from pathlib import Path
import numpy as np
from apply_crossfall import RoadField,unpack,reproject_paint
from object_geometry import pack
from build_scene import dump

def run(root,base):
    full=root/'canonical/full';scene=json.loads((full/'scene.json').read_text());parent=json.loads((base/'canonical/full/scene.json').read_text());field=RoadField(root/'canonical/road-height-field.npz');reports=[]
    for c in scene['chunks']:
        if c['name']!='paint':continue
        t,m,tint=unpack(base/'canonical/full',parent['chunks'][c['id']]);t,m,tint,r=reproject_paint(t,m,tint,field)
        c.update(pack(t,m,full/c['file'],tints=None if not np.any(tint) else np.maximum(tint,1e-6)));reports.append(r);print('PAINT',r,flush=True)
    stats=dict(uniqueTriangles=sum(c['triangles'] for c in scene['chunks']),expandedTriangles=sum(scene['chunks'][i['mesh']]['triangles'] for i in scene['instances']));scene['stats']=stats;dump(full/'scene.json',scene)
    report=json.loads((root/'road-crossfall.json').read_text());report['paintConformsToProfile']=reports;dump(root/'road-crossfall.json',report)
    city=json.loads((root/'canonical/urban-model.json').read_text());city['roadCrossfall']=report;dump(root/'canonical/urban-model.json',city)
    for name in ('canonical/validation.json','build-audit.json'):
        audit=json.loads((root/name).read_text());audit.update(stats=stats,roadCrossfall=report);dump(root/name,audit)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);p.add_argument('base',type=Path);a=p.parse_args();run(a.root,a.base)
