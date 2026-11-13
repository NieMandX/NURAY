"""Append shared survey lamp models without rebuilding the inherited city."""
import argparse
import collections
import hashlib
import json
import shutil
from pathlib import Path

import numpy as np
from build_scene import dump
from canonical_store import copy_asset
from object_geometry import pack
from street_library import MATERIALS, model


def apply(base, output, plan_path):
    assert not output.exists() and base.resolve()!=output.resolve()
    plan = json.loads(plan_path.read_text())
    assert plan['parent']==base.name and not plan['appliedToScene']
    scene = json.loads((base/'canonical/full/scene.json').read_text())
    city = json.loads((base/'canonical/urban-model.json').read_text())
    parent_instances = list(scene['instances'])
    output.mkdir(parents=True)
    for name in ('canonical','textures'):
        shutil.copytree(base/name,output/name,copy_function=copy_asset)
    for p in base.iterdir():
        if p.is_file() and p.suffix in ('.json','.gz') and p.name not in ('validation.json','objects.json.gz','tileset.json'):
            copy_asset(p,output/p.name)
    full = output/'canonical/full'
    library = {}
    for name in sorted(plan['acceptedByModel']):
        t,m = model(name).arrays()
        material_ids = {}
        for i in np.unique(m):
            value = MATERIALS[int(i)]
            if value not in scene['materials']: scene['materials'].append(value)
            material_ids[i] = scene['materials'].index(value)
        mapped = np.array([material_ids[i] for i in m],dtype=np.uint32)
        filename = 'survey-lamp-'+name+'.bin.gz'
        meta = pack(t,mapped,full/filename)
        idx = len(scene['chunks'])
        chunk = dict(id=idx,name='street-'+name,category='street',file=filename,
                     streetGeometry=True,objectGeometry=True,instanced=True,**meta)
        scene['chunks'].append(chunk)
        library[name] = dict(mesh=idx,triangles=chunk['triangles'],bounds=chunk['bounds'],
                             dimensions='Shared NURAY display default, not measured in DWG')
    for r in plan['records']:
        if r['status']!='accepted': continue
        x,n=r['eastNorth']
        assert np.hypot(x,n)<3000
        inst = dict(id=r['sourceId'],objectId=r['sourceId'],mesh=library[r['model']]['mesh'],matrix=r['matrix'],
                    tileId=f'{min(23,max(0,int((x+3000)//250)))}-{min(23,max(0,int((n+3000)//250)))}')
        scene['instances'].append(inst)
        r['renderInstance']=inst
    assert scene['instances'][:len(parent_instances)]==parent_instances
    scene['stats'] = dict(uniqueTriangles=sum(c['triangles'] for c in scene['chunks']),
                         expandedTriangles=sum(scene['chunks'][i['mesh']]['triangles'] for i in scene['instances']))
    labels = {'lamppost1':'металлические опоры','lamppost2':'двойные фонари','lamppost-concrete1':'железобетонные опоры'}
    for name in library:
        r=min((r for r in plan['records'] if r['status']=='accepted' and r['model']==name),key=lambda r:np.linalg.norm(r['eastNorth']))
        x,n=r['eastNorth'];key='survey-'+name+'-review'
        scene.setdefault('witnessViews',{})[key]=dict(yaw=r['yawRadians']+.8,pitch=.45,distance=34,target=[x,r['surface']['height']+2,-n])
        scene.setdefault('witnessViewLabels',{})[key]='Топосъёмка · '+labels[name]
    plan.update(appliedToScene=True,library=library,parentInstancesPreserved=True,
                sourcePlanSha256=hashlib.sha256(plan_path.read_bytes()).hexdigest())
    city['surveyLamps']={k:v for k,v in plan.items() if k!='records'}
    city['geometryRevision']=dict(version='yandex-survey-lamps-8',parent=base.name)
    city['limitations'].append('Survey lamp points are physical INSERTs; raw Z/scale/rotation are cartographic. Model dimensions and road-facing orientation are display estimates. Conflicting points are deferred, never relocated.')
    dump(full/'scene.json',scene);dump(output/'canonical/urban-model.json',city)
    dump(output/'survey-lamps.json',plan)
    for name in ('canonical/validation.json','build-audit.json'):
        report=json.loads((output/name).read_text());report.update(stats=scene['stats'],surveyLamps=city['surveyLamps']);dump(output/name,report)
    print('SURVEY LAMPS COMPLETE',plan['accepted'],scene['stats'],flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser()
    for n in ('base','output','plan'):p.add_argument('--'+n,type=Path,required=True)
    a=p.parse_args();apply(a.base,a.output,a.plan)
