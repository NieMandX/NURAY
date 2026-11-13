"""Reconsider source plants blocked solely by a superseded square envelope."""
import argparse, collections, gzip, hashlib, json, math
from pathlib import Path
import numpy as np
import shapely as sh
from scipy.spatial import cKDTree
from build_scene import BASE_SCALE, dump
from street_placement import SurfaceSampler

def recover(root,source):
    stage=json.loads((root/'paved-grade.json').read_text());base=root.parent/stage['parent']
    masks=json.loads(gzip.decompress((root/'placement-masks.json.gz').read_bytes()))
    prior=json.loads(gzip.decompress((base/'placement-masks.json.gz').read_bytes()))
    covers=lambda m,k:sh.from_wkb(bytes.fromhex(next(r['geometry'] for r in m['finishedGround'] if r['kind']==k)))
    restored=covers(masks,'grass').difference(covers(prior,'grass'))
    plants=json.loads(gzip.decompress((source/'supplement-2gis/vegetation.json.gz').read_bytes()))
    audit=json.loads(gzip.decompress((root/'plant-placement-audit.json.gz').read_bytes()))
    rejected={p['id']:p for p in audit['rejectedPoints']};scene=json.loads((root/'canonical/full/scene.json').read_text())
    existing=np.array([p['eastNorth'] for p in audit['acceptedPoints']]);tree=cKDTree(existing)
    blockers={k:sh.from_wkb(bytes.fromhex(wkb)) for k,wkb in masks['root'].items()}
    for g in blockers.values():sh.prepare(g)
    buildings=sh.STRtree([sh.from_wkb(bytes.fromhex(p)) for p,h in masks['buildings']]);tops=np.array([h for p,h in masks['buildings']])
    sampler=SurfaceSampler(root,scene,{'land','road-curbs','green-curbs','curbs'});added=[];deferred=[]
    for p in plants:
        if p['id'] not in rejected or not restored.contains(sh.Point(p['eastNorth'])):continue
        xy=p['eastNorth'];model=p['approvedModel'];scale=BASE_SCALE[model]*p['scale'];radius,low=np.array(masks['crowns'][model])*scale
        footprint=sh.Point(xy).buffer(max(.22,radius if low<2.5 else .22),quad_segs=4)
        reasons=[k for k,g in blockers.items() if g.intersects(footprint)]
        hit=sampler.ground(xy[0],-xy[1]);assert hit is not None
        near=buildings.query(sh.Point(xy).buffer(radius,quad_segs=8),predicate='intersects')
        if len(near) and np.any(tops[near]>hit['height']+scene['origin'][2]+low):reasons.append('buildingCanopy')
        if tree.query(xy)[0]<1. or any(np.linalg.norm(np.array(xy)-r['eastNorth'])<1 for r in added):reasons.append('existingPlant')
        if reasons:deferred.append(dict(id=p['id'],conflicts=reasons));continue
        angle=p['yawRadians'];c,s=math.cos(angle)*scale,math.sin(angle)*scale
        matrix=[c,0,s,xy[0],0,scale,0,hit['height'],-s,0,c,-xy[1]]
        mesh=next(c['id'] for c in scene['chunks'] if c['name']=='nuray-approved-'+model)
        scene['instances'].append(dict(id=p['id'],objectId=p['id'],mesh=mesh,matrix=matrix,tileId=f'{min(23,max(0,int((xy[0]+3000)//250)))}-{min(23,max(0,int((xy[1]+3000)//250)))}'))
        row=dict(id=p['id'],eastNorth=xy,model=model,matrix=matrix);added.append(row);audit['acceptedPoints'].append(row)
    ids={p['id'] for p in added};audit['rejectedPoints']=[p for p in audit['rejectedPoints'] if p['id'] not in ids]
    audit['accepted']+=len(added);audit['rejected']-=len(added)
    audit['byModel']=dict(collections.Counter(p['model'] for p in audit['acceptedPoints']))
    audit['byConflict']=dict(collections.Counter(k for p in audit['rejectedPoints'] for k in p['conflicts']))
    scene['stats']['expandedTriangles']=sum(scene['chunks'][i['mesh']]['triangles'] for i in scene['instances'])
    dump(root/'canonical/full/scene.json',scene)
    with gzip.open(root/'plant-placement-audit.json.gz','wt') as f:json.dump(audit,f,separators=(',',':'))
    sourcefile=source/'supplement-2gis/vegetation.json.gz'
    result=dict(policy='Recover retained 2GIS coordinates only on restored source lawn, with current exclusions and one-metre duplicate guard',
      sourceFile=str(sourcefile.resolve().relative_to(Path(__file__).resolve().parents[3])),sourceSha256=hashlib.sha256(sourcefile.read_bytes()).hexdigest(),
      records=added,deferred=deferred,accepted=len(added))
    dump(root/'recovered-square-plants.json',result);print('RECOVERED',len(added),'DEFERRED',len(deferred),flush=True)
    city=json.loads((root/'canonical/urban-model.json').read_text())
    city['objectLayer']['stats']['vegetationInstances']=audit['accepted']
    city['recoveredSquarePlants']={k:v for k,v in result.items() if k not in ('records','deferred')}
    dump(root/'canonical/urban-model.json',city)
    for name in ('canonical/validation.json','build-audit.json'):
        data=json.loads((root/name).read_text());data['stats']=scene['stats'];data['recoveredSquarePlants']=city['recoveredSquarePlants'];dump(root/name,data)
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);p.add_argument('source',type=Path);a=p.parse_args();recover(a.root,a.source)
