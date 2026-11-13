"""Relocate only conflicting roots inside an explicitly approved review polygon.

Keep source observations and all appearances. Search nearest finished green
surface with a conservative complete Gaussian crown envelope, ground contact,
and root spacing. No IDs or city-specific coordinates enter the algorithm.
"""
import argparse,gzip,hashlib,json,shutil,struct
from pathlib import Path
import numpy as np
import shapely as sh
from shapely import affinity
from canonical_store import copy_asset


def dump(path,value):
    path.write_text(json.dumps(value,ensure_ascii=False,separators=(',',':'))+'\n')


def nearest_green(root,footprint,safe_green,occupied,*,max_move=60.,spacing=3.,step=.5):
    root=np.asarray(root,float)
    grid=np.arange(-max_move,max_move+step*.1,step)
    xx,yy=np.meshgrid(grid,grid,indexing='ij');offsets=np.column_stack((xx.ravel(),yy.ravel()))
    distance=np.einsum('ij,ij->i',offsets,offsets)
    order=np.argsort(distance,kind='stable');order=order[distance[order]<=max_move**2]
    sh.prepare(safe_green)
    for index in order:
        xy=root+offsets[index]
        if len(occupied) and np.linalg.norm(occupied-xy,axis=1).min()<spacing:continue
        if safe_green.covers(affinity.translate(footprint,*xy)):return xy
    raise ValueError('No safe green position within allowed relocation distance')


class LocalGround:
    def __init__(self,base,scene,scope):
        tris=[]
        for c in scene['chunks']:
            if c['name']!='land':continue
            raw=gzip.decompress((base/'canonical/full'/Path(c['file']).name).read_bytes())
            v=np.frombuffer(raw[:c['vertexBytes']],'<f4').reshape(-1,8)[:,:3]
            ix=np.frombuffer(raw[c['vertexBytes']:],'<u4').reshape(-1,3)
            t=v[ix];xy=t[:,:,[0,2]]*[1,-1];lo=xy.min(1);hi=xy.max(1);a,b,d,e=scope.bounds
            keep=(hi[:,0]>=a)&(lo[:,0]<=d)&(hi[:,1]>=b)&(lo[:,1]<=e)
            tris.extend(t[keep])
        self.tris=np.asarray(tris,dtype=float);xz=self.tris[:,:,[0,2]]
        a=xz[:,1]-xz[:,0];b=xz[:,2]-xz[:,0]
        area=np.abs(a[:,0]*b[:,1]-a[:,1]*b[:,0]);self.tris=self.tris[area>1e-8]
        self.tree=sh.STRtree(sh.polygons(self.tris[:,:,[0,2]]))
    def height(self,xy):
        p=np.asarray(xy)*[1,-1];ids=self.tree.query(sh.Point(p),predicate='covered_by')
        heights=[]
        for i in ids:
            t=self.tris[i];a,b,c=t[:,[0,2]];uv=np.linalg.solve(np.column_stack((b-a,c-a)),p-a)
            heights.append(t[0,1]+uv[0]*(t[1,1]-t[0,1])+uv[1]*(t[2,1]-t[0,1]))
        if not heights:raise ValueError('No finished land triangle at destination')
        return float(max(heights))


def apply(base,out,splats,scope_path):
    if out.exists():raise ValueError('Use a new immutable release directory')
    policy=json.loads(scope_path.read_text());scope=sh.Polygon(policy['scopeEastNorth'])
    scene=json.loads((base/'canonical/full/scene.json').read_text());gs=json.loads((splats/'vegetation.json').read_text())
    catalog=json.loads((base/'tileset.json').read_text())
    masks=json.loads(gzip.decompress((base/'placement-masks.json.gz').read_bytes()))
    green=sh.from_wkb(bytes.fromhex(next(r['geometry']for r in masks['finishedGround']if r['kind']=='grass')))
    selection=[i for i in scene['instances']if scene['chunks'][i['mesh']]['name'].startswith('nuray-approved-')
               and scope.covers(sh.Point(i['matrix'][3],-i['matrix'][11]))
               and not green.covers(sh.Point(i['matrix'][3],-i['matrix'][11]).buffer(policy['rootMarginM']))]
    if not selection:raise ValueError('No conflicting roots in selected review area')
    area=scope.buffer(policy['maxMoveM']+35)
    blockers=sh.union_all([sh.from_wkb(bytes.fromhex(g)).intersection(area)for g in masks['root'].values()])
    safe=green.intersection(area).difference(blockers)
    ground=LocalGround(base,scene,area)
    models=[json.loads((splats/name).read_text())for name in gs['models']]
    def key(name,m):return name,np.asarray(m,dtype='<f4')[[3,11]].tobytes()
    splat_by_root={key(i['sourceType'],i['matrix']):i for i in gs['instances']}
    occupied=np.asarray([[i['matrix'][3],-i['matrix'][11]]for i in scene['instances']if scene['chunks'][i['mesh']]['name'].startswith('nuray-approved-')])
    records=[]
    for inst in selection:
        name=scene['chunks'][inst['mesh']]['name'];g=splat_by_root[key(name,inst['matrix'])]
        b=models[g['model']]['bounds'];matrix=np.asarray(g['matrix']).reshape(3,4)
        corners=np.array([[x,0,z]for x in (b['min'][0],b['max'][0])for z in (b['min'][2],b['max'][2])])@matrix[:,:3].T
        envelope=sh.MultiPoint(corners[:,[0,2]]*[1,-1]).convex_hull.buffer(policy['crownMarginM'])
        original=list(inst['matrix']);root=np.array([original[3],-original[11]])
        xy=nearest_green(root,envelope,safe,occupied,max_move=policy['maxMoveM'],spacing=policy['rootSpacingM'])
        height=ground.height(xy);updated=list(original);updated[3],updated[7],updated[11]=float(xy[0]),height,float(-xy[1])
        occupied[np.argmin(np.linalg.norm(occupied-root,axis=1))]=xy
        records.append(dict(id=inst['id'],sourceType=name,sourceInstance=g['sourceInstance'],sourceDraw=g['sourceDraw'],
            originalMatrix=original,matrix=updated,originalEastNorth=root.tolist(),eastNorth=xy.tolist(),
            shiftM=float(np.linalg.norm(xy-root)),envelopeWKB=envelope.wkb_hex,
            originalSplatMatrix=g['matrix'],splatModel=gs['models'][g['model']]))
        inst['matrix']=updated
        east=int((xy[0]+catalog['origin'][0]-catalog['boundsMSK'][0])//catalog['tileSizeM'])
        north=int((xy[1]+catalog['origin'][1]-catalog['boundsMSK'][1])//catalog['tileSizeM'])
        if not (0<=east<catalog['grid']['columns'] and 0<=north<catalog['grid']['rows']):raise ValueError('Destination outside scene')
        inst['tileId']=f'{east}-{north}'
    # Independent copy-on-write release; old public assets remain immutable.
    shutil.copytree(base,out,copy_function=copy_asset,ignore=shutil.ignore_patterns('merged','meshes.pack','mesh-pack.json','delivery-*','.DS_Store'))
    dump(out/'canonical/full/scene.json',scene)
    audit=json.loads(gzip.decompress((out/'plant-placement-audit.json.gz').read_bytes()));changed={r['id']:r for r in records}
    for row in audit['acceptedPoints']:
        if row['id']in changed:
            r=changed[row['id']];row['originalSourceEastNorth']=row['eastNorth'];row['originalMatrix']=row['matrix']
            row['eastNorth']=r['eastNorth'];row['matrix']=r['matrix'];row['placementReason']='user-approved-local-green-relocation'
    with gzip.open(out/'plant-placement-audit.json.gz','wt')as f:json.dump(audit,f,separators=(',',':'))
    appearance=json.loads((out/'vegetation-appearance.json').read_text())
    for row in appearance['records']:
        if row.get('id')in changed:row['matrix']=changed[row['id']]['matrix'];row['eastNorth']=changed[row['id']]['eastNorth']
    dump(out/'vegetation-appearance.json',appearance)
    revision=dict(version='local-green-relocation-1',parent=base.name,changedPlantCount=len(records))
    for name in ('transport-metadata.json','urban-model.json'):
        path=out/'canonical'/name;data=json.loads(path.read_text());data['geometryRevision']=revision;dump(path,data)
    dump(out/'plant-relocation-patch.json',dict(changedChunks=sorted({i['mesh']for i in selection}),geometryRevision=revision))
    report=dict(version=1,parent=base.name,policy=policy,scopeSha256=hashlib.sha256(scope_path.read_bytes()).hexdigest(),
        plantCount=gs['coverage']['sourcePlants'],moved=len(records),records=records,
        sourceObservationsPreserved=True,geometryUnchanged=True)
    dump(out/'plant-relocation.json',report)
    dump(out/'validation.json',dict(passed=False,pending='Validate relocated plants and matching transport',parent=base.name))
    print(json.dumps({'moved':len(records),'shiftsM':[round(r['shiftM'],2)for r in records]}),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--base',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--splats',type=Path,required=True);p.add_argument('--scope',type=Path,required=True)
    a=p.parse_args();apply(a.base,a.output,a.splats,a.scope)
