"""Inspect actual curb-boundary witnesses without a city-sized mesh reload."""
import sys,pickle,json,time
from pathlib import Path
import numpy as np
import shapely as sh
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'prototype'))
from coverage import physical_land_boundary,lines
from spatial_mask import LinearMask
p=Path(sys.argv[1])
while not p.exists():time.sleep(3)
with p.open('rb') as f:s=pickle.load(f)
road=s['road'];band=s['curb_band'];tol=.00005
expected=physical_land_boundary(road,s['opening'].union(s['transition_cut']),s['EXTENT'],tol)
print('EXPECTED',expected.length,flush=True)
front=LinearMask(s['curb_front']);sides=LinearMask(band.boundary);out=[];padded={}
sh.prepare(road);sh.prepare(band)
for chain in lines(expected):
    xy=list(chain.coords)
    for a,b in zip(xy,xy[1:]):
        edge=sh.LineString([a,b]);x0,y0,x1,y1=edge.bounds
        for i in front.tree.query(sh.box(x0-tol,y0-tol,x1+tol,y1+tol)):
            i=int(i)
            if i not in padded:padded[i]=front.segments[i].buffer(tol)
            edge=edge.difference(padded[i])
            if edge.is_empty:break
        for missing in lines(edge):
            if missing.length<=2*tol:continue
            mid=missing.interpolate(.5,normalized=True);x=np.asarray(mid.coords)[0]
            coords=np.asarray(missing.coords);n=coords[-1]-coords[0];n=np.array([-n[1],n[0]])/np.linalg.norm(n)
            d=sides.segments[int(sides.tree.nearest(mid))].distance(mid)
            probes={str(t):dict(road=[bool(road.covers(sh.Point(x+n*t*sign))) for sign in [-1,1]],
                               curb=[bool(band.covers(sh.Point(x+n*t*sign))) for sign in [-1,1]]) for t in [.00001,.0001,.001,.01]}
            out.append(dict(length=missing.length,geometry=sh.geometry.mapping(missing),distanceToBandBoundary=d,probes=probes))
out.sort(key=lambda r:-r['length'])
report=dict(count=len(out),length=sum(r['length'] for r in out),
    onBandBoundaryM=sum(r['length'] for r in out if r['distanceToBandBoundary']<tol),witnesses=out)
p.with_suffix('.coverage.json').write_text(json.dumps(report,indent=2))
print({k:v for k,v in report.items() if k!='witnesses'},flush=True)
for row in out[:20]:print(row,flush=True)
