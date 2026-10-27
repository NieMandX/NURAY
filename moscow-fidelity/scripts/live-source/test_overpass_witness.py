"""Rebuild small, source-backed neighbourhoods around failed structural joins."""
import sys,pickle,json
from pathlib import Path
from collections import defaultdict
import shapely as sh
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'prototype'))
from overpasses import build
from build import triangulate,z_at,plane

root=Path(sys.argv[1]);cache=root/'overpass-local-inputs.pkl'
if cache.exists():w=pickle.load(cache.open('rb'))
else:
    w=pickle.load((root/'overpass-witness.pkl').open('rb'))
    extent=sh.union_all([sh.box(r['xy'][0]-30,r['xy'][1]-30,r['xy'][0]+30,r['xy'][1]+30)
                        for r in json.loads((root/'overpass-join-diagnostic.json').read_text())])
    dt=sh.STRtree([g for g,c in w['dem']]);rt=sh.STRtree([r['poly'] for r in w['surfaces']])
    w={**w,'dem':[w['dem'][int(i)] for i in dt.query(extent,predicate='intersects')],
       'surfaces':[w['surfaces'][int(i)] for i in rt.query(extent,predicate='intersects')]}
    w.pop('profiles',None)
    with cache.open('wb') as f:pickle.dump(w,f)
dt=sh.STRtree([g for g,c in w['dem']]);rt=sh.STRtree([r['poly'] for r in w['surfaces']]);done=set();results=[]
for issue in json.loads((root/'overpass-join-diagnostic.json').read_text()):
    key=issue['connection']['id']
    if key in done:continue
    done.add(key);x,y=issue['xy'];extent=sh.box(x-30,y-30,x+30,y+30).intersection(w['extent'])
    records=[r for r in w['connections'] if r['kind']=='roadbed_overpass' and extent.covers(sh.geometry.shape(r['mouthGeometry']))]
    rows=[]
    for i in rt.query(extent,predicate='intersects'):
        r=w['surfaces'][int(i)];g=r['poly'].intersection(extent)
        if g.area>1e-9:rows.append({**r,'poly':g})
    dem=[w['dem'][int(i)] for i in dt.query(extent,predicate='intersects')]
    print('CASE',key,len(rows),len(dem),flush=True)
    groups=defaultdict(list)
    profiles,count=build(rows,dem,sh.STRtree([g for g,c in dem]),groups,extent,.00001,triangulate,z_at,plane,records)
    compact=[{k:v for k,v in p.items() if 'Geometry' not in k and k not in ('extensionHeightCells','sourceParents')} for p in profiles]
    results.append(dict(id=key,profiles=compact));print('RESULT',key,'profiles',len(profiles),'failed',sum(not p['passed'] for p in profiles),flush=True)
(root/'overpass-local-regression.json').write_text(json.dumps(results,indent=2))
assert all(p['passed'] for r in results for p in r['profiles']),'See overpass-local-regression.json for failed checks'
