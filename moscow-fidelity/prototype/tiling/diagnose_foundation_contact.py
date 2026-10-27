"""Extract a local, serialized contact witness without loading the whole city."""
import argparse, gzip, json
from pathlib import Path
import ijson
import numpy as np
import shapely as sh
from street_placement import SurfaceSampler, GROUND_NAMES
from adaptive_foundations import BURIAL


def diagnose(root, oid, out):
    with gzip.open(root/'objects.json.gz', 'rb') as f:
        record=next(r for r in ijson.items(f, 'objectLayer.foundations.buildings.item', use_float=True) if r['id']==oid)
    points=np.array([p['top'] for p in record['panels']])[:,:,[0,2]].reshape(-1,2)
    lo,hi=points.min(axis=0)-.1,points.max(axis=0)+.1
    scene=json.loads((root/'canonical/full/scene.json').read_text())
    tris=[];refs=[]
    for c in scene['chunks']:
        if c['name'] not in GROUND_NAMES:continue
        raw=gzip.decompress((root/'canonical/full'/Path(c['file']).name).read_bytes())
        vertices=np.frombuffer(raw[:c['vertexBytes']],'<f4').reshape(-1,8)[:,:3].astype(float)
        indices=np.frombuffer(raw[c['vertexBytes']:],'<u4').reshape(-1,3)
        t=vertices[indices];xz=t[:,:,[0,2]]
        a=xz[:,1]-xz[:,0];b=xz[:,2]-xz[:,0]
        keep=(np.abs(a[:,0]*b[:,1]-a[:,1]*b[:,0])>1e-8)&(xz.max(axis=1)>=lo).all(axis=1)&(xz.min(axis=1)<=hi).all(axis=1)
        ids=np.flatnonzero(keep);tris.extend(t[ids]);refs.extend((c['id'],int(i)) for i in ids)
    sampler=object.__new__(SurfaceSampler);sampler.tris=np.asarray(tris);sampler.refs=refs
    sampler.polys=sh.polygons(sampler.tris[:,:,[0,2]]);sampler.tree=sh.STRtree(sampler.polys)
    failures=[]
    for i,p in enumerate(record['panels']):
        bottom=np.array(p['bottom']);offset=np.array(p['groundOffsetM'])
        for s in [.1,.5,.9]:
            q=bottom[0]+s*(bottom[1]-bottom[0]);xz=q[[0,2]]+offset
            hit=sampler.ground(*xz)
            if hit and abs(q[1]+BURIAL-hit['height'])<.0002:continue
            point=sh.Point(xz);nearest=int(sampler.tree.nearest(point));declared=refs.index(tuple(p['ground']))
            failures.append(dict(panel=i,station=s,point=xz.tolist(),bottom=q.tolist(),hit=hit,nearest=nearest,
                distance=float(point.distance(sampler.polys[nearest])),declared=declared,
                declaredDistance=float(point.distance(sampler.polys[declared]))))
    out.mkdir(parents=True,exist_ok=True)
    result=dict(object=oid,record=record,triangles=sampler.tris.tolist(),refs=refs,failures=failures)
    (out/'contact-witness.json').write_text(json.dumps(result,ensure_ascii=False))
    print(json.dumps(dict(panels=len(record['panels']),triangles=len(tris),failures=failures),ensure_ascii=False),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);p.add_argument('object');p.add_argument('out',type=Path)
    a=p.parse_args();diagnose(a.root,a.object,a.out)
