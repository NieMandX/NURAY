"""Read-only local geometry witnesses for failed region checks."""
import sys,json,pickle
from pathlib import Path
import numpy as np
import shapely as sh
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'prototype'),str(ROOT/'prototype/tiling')]
import build as b
from region_checkpoint import restore
from spatial_mask import LinearMask
from coverage import lines,gap_core_area

source=ROOT/'source/2gis-live-20261019'
opening,road,*_=restore(b,source/'canonical-checkpoint-v2.pkl')
report=json.loads((b.DATA/'validation.json').read_text())
print('RESTORED',len(b.surfaces),flush=True)
tree=sh.STRtree([s['poly'] for s in b.surfaces])
out={'connections':[],'curbs':[],'holes':[]}
bad={r['id'] for r in report['gradeConnections']['connections'] if not r['passed']}
for conn in b.grade_connections:
    if conn['id'] not in bad:continue
    line=sh.geometry.shape(conn['mouthGeometry']);near=[b.surfaces[int(i)] for i in tree.query(line.buffer(2))]
    samples=[]
    for position in np.linspace(.05,line.length-.05,max(3,int(np.ceil(line.length))+1)):
        pt=line.interpolate(position);xy=np.asarray(pt.coords)[0]
        matches=[dict(kind=s['kind'],owner=s['owner'],tiers=s['tiers'],distance=s['poly'].distance(pt),height=float(b.z_at(s['plane'],xy)),material=s['material']) for s in near if s['poly'].distance(pt)<.02]
        samples.append(dict(xy=xy.tolist(),surfaces=matches))
    out['connections'].append(dict(connection=conn,samples=samples))
    print('MOUTH',conn['id'],[(list(dict.fromkeys(s['kind'] for s in p['surfaces']))) for p in samples],flush=True)
    with (source/(conn['id'].replace(':','-')+'.witness.pkl')).open('wb') as f:pickle.dump((conn,near),f)
border=road.boundary.difference(b.union([opening,b.transition_cut]).buffer(b.GRID*3)).difference(b.EXTENT.boundary.buffer(.00005))
front=LinearMask(b.curb_front)
for chain in lines(border):
    xy=list(chain.coords)
    for a,c in zip(xy,xy[1:]):
        edge=sh.LineString([a,c]);missing=edge.difference(front.near(edge.buffer(.00005)).buffer(.00005))
        if missing.length>.005:out['curbs'].append(dict(length=missing.length,geometry=sh.geometry.mapping(missing)))
out['curbs'].sort(key=lambda r:-r['length'])
print('CURBS',len(out['curbs']),sum(r['length'] for r in out['curbs']),flush=True)
for r in out['curbs'][:30]:
    g=sh.geometry.shape(r['geometry']);pt=g.interpolate(.5,normalized=True)
    r['nearby']=[dict(kind=s['kind'],owner=s['owner'],material=s['material'],distance=s['poly'].distance(pt)) for i in tree.query(pt.buffer(.01)) if (s:=b.surfaces[int(i)])['poly'].distance(pt)<.01]
    r['bandDistance']=b.curb_band.distance(pt)
    print('CURB',r,flush=True)
for h in report['roadQuality']['current']['thinEnclosedSlits']:
    box=sh.box(*h['bounds']).buffer(.01)
    local=[b.surfaces[int(i)] for i in tree.query(box)];land=b.union([s['poly'] for s in local if s['kind'] in ['land','curb_top']])
    r=dict(**h,landArea=land.intersection(box).area,landOwners=sorted(set(s['owner'] for s in local if s['kind'] in ['land','curb_top'])))
    out['holes'].append(r)
flat=b.union([s['poly'] for s in b.surfaces if s['kind']=='roadbed_flat']);land=b.union([s['poly'] for s in b.surfaces if s['kind'] in ['land','curb_top']]);overlap=flat.intersection(land)
out['overlap']=dict(area=overlap.area,core=gap_core_area(overlap,b.GRID*5))
(source/'canonical-diagnostics.json').write_text(json.dumps(out,indent=2))
print('DIAG COMPLETE',out['overlap'],flush=True)
