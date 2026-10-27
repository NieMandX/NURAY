"""Locate a failed shoulder join in this run's extracted source witness."""
import sys,pickle,json
from pathlib import Path
import numpy as np
import shapely as sh
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'prototype'))
from overpasses import parts

root=Path(sys.argv[1]);w=pickle.load((root/'overpass-witness.pkl').open('rb'))
dem=w['dem'];dt=sh.STRtree([p for p,c in dem]);bad=[]
for profile in w['profiles']:
 rows=[r for r in w['surfaces'] if r['tiers']==profile['level'] and r.get('transport','vehicle')==profile['transport']]
 rt=sh.STRtree([r['poly'] for r in rows])
 records=[r for r in w['connections'] if r['kind']=='roadbed_overpass' and r['level']==profile['level'] and r.get('transport','vehicle')==profile['transport']]
 portals=[]
 for r in records:
  xy=np.asarray(sh.geometry.shape(r['mouthGeometry']).coords)[:,:2];ends=xy.copy();width=profile['sideOverhangM']
  ends[0]-=(xy[1]-xy[0])/np.linalg.norm(xy[1]-xy[0])*2*width
  ends[-1]+=(xy[-1]-xy[-2])/np.linalg.norm(xy[-1]-xy[-2])*2*width
  extended=np.vstack([ends[0],xy,ends[-1]]);values=r.get('relativeHeightsM',[0.]*len(xy))
  portals.append((sh.LineString(extended),np.r_[0,np.cumsum(np.linalg.norm(np.diff(extended,axis=0),axis=1))],np.r_[values[0],values,values[-1]]))
 pt=sh.STRtree([p[0] for p in portals]);supports=[(sh.geometry.shape(r['geometry']),np.asarray(r['heightPlane'])) for r in profile['extensionHeightCells']]
 st=sh.STRtree([p for p,c in supports]);ground=sh.geometry.shape(profile['groundShoulderConnectionGeometry'])
 for line in parts(ground,'LineString'):
  for j in st.query(line.buffer(.00003),predicate='intersects'):
   poly,c=supports[int(j)]
   for piece in parts(line.intersection(poly.buffer(.00003)),'LineString'):
    for di in dt.query(piece,predicate='intersects'):
     for edge in parts(piece.intersection(dem[int(di)][0]),'LineString'):
      for xy in np.asarray(edge.coords)[:,:2]:
       point=sh.Point(xy);ids,dist=pt.query_nearest(point,return_distance=True);pi=min(zip(map(int,ids),dist),key=lambda a:(a[1],a[0]))[0]
       hits=dt.query(point,predicate='covered_by');d=int(hits[0]) if len(hits) else int(dt.nearest(point))
       p,stations,values=portals[pi];expected=float(dem[d][1]@np.r_[xy,1]+np.interp(p.project(point),stations,values));actual=float(c@np.r_[xy,1]);error=abs(actual-expected)
       if error>.001:
        source=[dict(owner=rows[int(k)]['owner'],height=float(rows[int(k)]['plane']@np.r_[xy,1]),distance=rows[int(k)]['poly'].distance(point)) for k in rt.query(point.buffer(2),predicate='intersects')]
        bad.append(dict(error=error,xy=xy.tolist(),actual=actual,expected=expected,support=int(j),portal=pi,connection=records[pi],nearestRoads=source[:12]))
 unique={tuple(np.round(r['xy'],5)):r for r in sorted(bad,key=lambda r:r['error'])}
 result=sorted(unique.values(),key=lambda r:-r['error'])
 (root/'overpass-join-diagnostic.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
 print('BAD',len(result),flush=True)
 for r in result[:10]:
  print({k:v for k,v in r.items() if k!='connection'},'connection', {k:r['connection'].get(k) for k in ('id','atGround','peerKind','relativeHeightsM','sourceParents','peerParents')},flush=True)
