"""Append accepted survey plant instances; all parent meshes stay immutable."""
import argparse
import collections
import gzip
import hashlib
import json
import shutil
from pathlib import Path
import numpy as np
from build_scene import dump
from canonical_store import copy_asset


def apply(base,output,plan_path):
    assert not output.exists() and base.resolve()!=output.resolve()
    report=json.loads(plan_path.read_text());assert report['parent']==base.name and not report['appliedToScene']
    scene=json.loads((base/'canonical/full/scene.json').read_text())
    city=json.loads((base/'canonical/urban-model.json').read_text())
    old_instances=list(scene['instances'])
    plants=json.loads(gzip.decompress((base/'plant-placement-audit.json.gz').read_bytes()))
    output.mkdir(parents=True)
    for name in ('canonical','textures'):shutil.copytree(base/name,output/name,copy_function=copy_asset)
    for p in base.iterdir():
        if p.is_file() and p.suffix in ('.json','.gz') and p.name not in ('validation.json','objects.json.gz','tileset.json'):
            copy_asset(p,output/p.name)
    library={c['name'].removeprefix('nuray-approved-'):c for c in scene['chunks'] if c['name'].startswith('nuray-approved-')}
    for r in report['records']:
        if r['status']!='accepted':continue
        x,n=r['eastNorth'];assert np.hypot(x,n)<3000
        inst=dict(id=r['id'],objectId=r['id'],mesh=library[r['model']]['id'],matrix=r['matrix'],
                  tileId=f'{min(23,max(0,int((x+3000)//250)))}-{min(23,max(0,int((n+3000)//250)))}')
        scene['instances'].append(inst);r['renderInstance']=inst
        plants['acceptedPoints'].append({k:r[k] for k in ('id','eastNorth','model','matrix')})
    assert scene['instances'][:len(old_instances)]==old_instances
    deferred=[r for r in report['records'] if r['status']=='deferred']
    plants['rejectedPoints'].extend(dict(id=r['id'],eastNorth=r['eastNorth'],model=r['model'],
                                        conflicts=['survey:'+r['reason']],source='DWG') for r in deferred)
    plants['source']+=report['source'];plants['accepted']+=report['accepted'];plants['rejected']+=len(deferred)
    plants['byModel']=dict(collections.Counter(r['model'] for r in plants['acceptedPoints']))
    plants['byConflict']=dict(collections.Counter(k for r in plants['rejectedPoints'] for k in r['conflicts']))
    plants['surveySupplement']={k:report[k] for k in ('source','accepted','deferredByReason','policy')}
    scene['stats']=dict(uniqueTriangles=sum(c['triangles'] for c in scene['chunks']),
                        expandedTriangles=sum(scene['chunks'][i['mesh']]['triangles'] for i in scene['instances']))
    # The review camera is derived from the densest accepted neighbourhood,
    # never a coordinate exception in the placement algorithm.
    accepted=[r for r in report['records'] if r['status']=='accepted']
    xy=np.array([r['eastNorth'] for r in accepted]);density=((xy[:,None]-xy[None,:])**2).sum(2)<60**2
    center=accepted[int(np.argmax(density.sum(1)))];x,n=center['eastNorth']
    scene.setdefault('witnessViews',{})['survey-plants-review']=dict(yaw=.45,pitch=.65,distance=120,target=[x,center['matrix'][7]+5,-n])
    scene.setdefault('witnessViewLabels',{})['survey-plants-review']='Топосъёмка · восстановленные посадки'
    report.update(appliedToScene=True,sourcePlanSha256=hashlib.sha256(plan_path.read_bytes()).hexdigest(),
                  existingInstancesPreserved=True,parentInstanceCount=len(old_instances))
    city['surveyPlants']={k:v for k,v in report.items() if k!='records'}
    city['geometryRevision']=dict(version='yandex-survey-plants-9',parent=base.name)
    city['objectLayer']['stats']['vegetationInstances']=plants['accepted']
    city['limitations'].append('Survey vegetation supplements only unoccupied mapped green surfaces. Tree size/yaw use deterministic display defaults; unknown conifers and conflicting points are deferred. Existing plants are unchanged.')
    dump(output/'canonical/full/scene.json',scene);dump(output/'canonical/urban-model.json',city);dump(output/'survey-plants.json',report)
    with gzip.open(output/'plant-placement-audit.json.gz','wt') as f:json.dump(plants,f,separators=(',',':'))
    for name in ('canonical/validation.json','build-audit.json'):
        d=json.loads((output/name).read_text());d.update(stats=scene['stats'],surveyPlants=city['surveyPlants'],
            plants={k:v for k,v in plants.items() if not k.endswith('Points')});dump(output/name,d)
    print('SURVEY PLANTS COMPLETE',report['accepted'],scene['stats'],flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser()
    for n in ('base','output','plan'):p.add_argument('--'+n,type=Path,required=True)
    a=p.parse_args();apply(a.base,a.output,a.plan)
