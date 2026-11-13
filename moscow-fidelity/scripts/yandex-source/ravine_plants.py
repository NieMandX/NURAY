"""Deterministic, evidence-scoped woodland infill on existing green surfaces.

Zones describe approximate cover seen in dated panoramas, not measured trees.
All existing data is immutable; candidates never snap into roads or buildings.
"""
import argparse, collections, gzip, hashlib, json, math, shutil
from pathlib import Path
import numpy as np
import shapely as sh
from scipy.spatial import cKDTree
from build_scene import dump
from canonical_store import copy_asset
from prepare_supplement import Terrain

POLICY=dict(version=1,seed=461113,cellM=3.6,greenEdgeClearanceM=2.5,
            treeRootSeparationM=3.8,understorySeparationM=2.3,
            source='Approximate cover inferred from Yandex aerial panoramas captured in 2021; not surveyed tree coordinates',
            dimensions='Approved proxy library, variable display scale; not measured heights',
            conflicts='Reject candidates; preserve every previous instance and all terrain meshes')
TYPES=[('compact','ravine-broad',.35),('growth','ravine-young',.31),('bush','ravine-thicket',.26)]

def randoms(key):
    return np.frombuffer(hashlib.sha256(key.encode()).digest(),'<u4').astype(float)/2**32

def plan(zones, existing_xy, green, masks, crowns, buildings, sample, origin):
    old=cKDTree(existing_xy) if len(existing_xy) else None
    btree=sh.STRtree([g for g,h in buildings]);tops=np.array([h for g,h in buildings])
    inner=green.buffer(-POLICY['greenEdgeClearanceM']);sh.prepare(inner)
    for g in masks.values():sh.prepare(g)
    accepted=[];rows=[]
    for zone in zones:
        area=sh.Polygon(zone['polygon']).intersection(inner)
        if area.is_empty:continue
        x0,n0,x1,n1=area.bounds;cell=POLICY['cellM']
        candidates=[]
        for ix in range(math.floor(x0/cell),math.ceil(x1/cell)+1):
            for iz in range(math.floor(n0/cell),math.ceil(n1/cell)+1):
                identity=f"ravine-plant:{zone['id']}:{ix}:{iz}";v=randoms(identity)
                x=(ix+.15+.7*v[0])*cell;n=(iz+.15+.7*v[1])*cell
                p=sh.Point(x,n)
                if not area.covers(p):continue
                # Broad uneven patches and occasional gaps, without rows.
                cover=.66+.16*math.sin(x/19+n/31)+.12*math.cos(n/13-x/37)
                if v[2]>cover:continue
                candidates.append((v[7],identity,v,x,n))
        for _,identity,v,x,n in sorted(candidates):
            typeid=0 if v[3]<.60 else 1 if v[3]<.87 else 2
            model,appearance,base_scale=TYPES[typeid];scale=base_scale*(.82+.36*v[4]);yaw=v[5]*math.tau
            p=sh.Point(x,n);radius,low=np.array(crowns[model])*scale
            separation=POLICY['treeRootSeparationM'] if typeid==0 else POLICY['understorySeparationM']
            r=dict(id=identity,eastNorth=[x,n],model=model,appearance=appearance,scale=scale,
                   zone=zone['id'],separationM=separation,crownRadiusM=float(radius),crownBottomM=float(low))
            reason=None
            if old and old.query([x,n])[0]<separation:reason='near-existing-plant'
            if reason is None and any(math.hypot(x-a,n-b)<max(separation,s) for a,b,s in accepted):reason='near-added-plant'
            clearance=max(.22,radius if low<2.5 else .22)
            footprint=p.buffer(clearance,quad_segs=4)
            hits=[key for key,g in masks.items() if g.intersects(footprint)]
            if hits:reason='surface-conflict';r['conflicts']=hits
            height=sample(x,n)
            if height is None or not math.isfinite(height):reason='no-ground'
            else:
                near=btree.query(p.buffer(radius,quad_segs=8),predicate='intersects')
                if len(near) and np.any(tops[near]>height+origin+low+1e-6):reason='building-canopy'
            if reason:r.update(status='deferred',reason=reason)
            else:
                c,s=math.cos(yaw)*scale,math.sin(yaw)*scale
                r.update(status='accepted',matrix=[c,0,s,x,0,scale,0,height,-s,0,c,-n],clearanceM=clearance)
                accepted.append((x,n,separation))
            rows.append(r)
    return rows

def create_plan(base,config,output):
    scene=json.loads((base/'canonical/full/scene.json').read_text())
    m=json.loads(gzip.decompress((base/'placement-masks.json.gz').read_bytes()))
    masks={k:sh.from_wkb(bytes.fromhex(v)) for k,v in m['root'].items()}
    green=sh.union_all([sh.from_wkb(bytes.fromhex(g['geometry'])) for g in m['finishedGround'] if g['kind'] in ('grass','cemetery')])
    previous=json.loads(gzip.decompress((base/'plant-placement-audit.json.gz').read_bytes()))
    terrain=Terrain(np.load(base/'canonical/terrain.npz')['triangles'])
    ground=[(sh.from_wkb(bytes.fromhex(g['geometry'])),g['offsetM']) for g in m['finishedGround']]
    def sample(x,n):
        p=sh.Point(x,n);offset=0
        for g,h in ground:
            if g.covers(p):offset=h
        return float(terrain.sample([[x,n]])[0])+offset-scene['origin'][2]
    zones=json.loads(config.read_text())
    rows=plan(zones['zones'],[p['eastNorth'] for p in previous['acceptedPoints']],green,masks,m['crowns'],
              [(sh.from_wkb(bytes.fromhex(g)),h) for g,h in m['buildings']],sample,scene['origin'][2])
    report=dict(parent=base.name,policy=POLICY,evidence=zones,appliedToScene=False,source=len(rows),
                accepted=sum(r['status']=='accepted' for r in rows),records=rows,
                acceptedByModel=dict(collections.Counter(r['model'] for r in rows if r['status']=='accepted')),
                deferredByReason=dict(collections.Counter(r['reason'] for r in rows if r['status']=='deferred')))
    dump(output,report);print(json.dumps({k:v for k,v in report.items() if k not in ('records','evidence')},ensure_ascii=False))

def apply(base,output,plan_path):
    assert not output.exists()
    report=json.loads(plan_path.read_text());assert report['parent']==base.name and not report['appliedToScene']
    output.mkdir(parents=True)
    for name in ('canonical','textures'):shutil.copytree(base/name,output/name,copy_function=copy_asset)
    for p in base.iterdir():
        if p.is_file() and p.suffix in ('.json','.gz') and p.name not in ('validation.json','objects.json.gz','tileset.json'):copy_asset(p,output/p.name)
    scene=json.loads((base/'canonical/full/scene.json').read_text());city=json.loads((base/'canonical/urban-model.json').read_text())
    plants=json.loads(gzip.decompress((base/'plant-placement-audit.json.gz').read_bytes()));old=len(scene['instances'])
    library={c['name'].removeprefix('nuray-approved-'):c for c in scene['chunks'] if c['name'].startswith('nuray-approved-')}
    for r in report['records']:
        if r['status']!='accepted':continue
        x,n=r['eastNorth'];assert math.hypot(x,n)<3000
        scene['instances'].append(dict(id=r['id'],objectId=r['id'],mesh=library[r['model']]['id'],matrix=r['matrix'],tileId=f'{int((x+3000)//250)}-{int((n+3000)//250)}'))
        plants['acceptedPoints'].append({k:r[k] for k in ('id','eastNorth','model','matrix')})
    deferred=[r for r in report['records'] if r['status']=='deferred']
    plants['rejectedPoints'].extend(dict(id=r['id'],eastNorth=r['eastNorth'],model=r['model'],conflicts=['ravine:'+r['reason']],source='panorama-infill') for r in deferred)
    plants['source']+=report['source'];plants['accepted']+=report['accepted'];plants['rejected']+=len(deferred)
    plants['byModel']=dict(collections.Counter(r['model'] for r in plants['acceptedPoints']));plants['byConflict']=dict(collections.Counter(k for r in plants['rejectedPoints'] for k in r['conflicts']))
    report.update(appliedToScene=True,parentInstanceCount=old,sourcePlanSha256=hashlib.sha256(plan_path.read_bytes()).hexdigest())
    scene['stats']=dict(uniqueTriangles=sum(c['triangles'] for c in scene['chunks']),expandedTriangles=sum(scene['chunks'][i['mesh']]['triangles'] for i in scene['instances']))
    accepted=[r for r in report['records'] if r['status']=='accepted'];p=min(accepted,key=lambda r:math.dist(r['eastNorth'],[360,160]));x,n=p['eastNorth']
    scene.setdefault('witnessViews',{})['ravine-plants-review']=dict(yaw=6.2,pitch=.70,distance=280,target=[x,p['matrix'][7]+8,-n])
    scene.setdefault('witnessViewLabels',{})['ravine-plants-review']='Сонина · зелёные склоны'
    city['ravinePlants']={k:v for k,v in report.items() if k!='records'};city['geometryRevision']=dict(version='yandex-ravine-infill-10',parent=base.name)
    city['objectLayer']['stats']['vegetationInstances']=plants['accepted']
    city['limitations'].append(POLICY['source'])
    dump(output/'canonical/full/scene.json',scene);dump(output/'canonical/urban-model.json',city);dump(output/'ravine-plants.json',report)
    with gzip.open(output/'plant-placement-audit.json.gz','wt') as f:json.dump(plants,f,separators=(',',':'))
    for name in ('canonical/validation.json','build-audit.json'):
        d=json.loads((output/name).read_text());d.update(stats=scene['stats'],ravinePlants=city['ravinePlants'],plants={k:v for k,v in plants.items() if not k.endswith('Points')});dump(output/name,d)
    print('RAVINE INFILL COMPLETE',report['accepted'],scene['stats'],flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['plan','apply']);p.add_argument('--base',type=Path,required=True);p.add_argument('--config',type=Path);p.add_argument('--plan',type=Path);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    if a.action=='plan':create_plan(a.base,a.config,a.output)
    else:apply(a.base,a.output,a.plan)
