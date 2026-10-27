import sys,pickle,json
from pathlib import Path
import numpy as np
import shapely as sh
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'prototype'))
from overpass_sheets import structural_sheets,sheet_entries
from overpasses import parts
from build import z_at
root=Path(sys.argv[1]);w=pickle.load((root/'failed-overpass-rebuild.pkl').open('rb'))
dem=w['dem'];dt=sh.STRtree([p for p,c in dem])
_,connections=structural_sheets(w['surfaces'],w['connections'],dem,dt,.00001,z_at)
result=[]
for profile_index,profile in enumerate(w['profiles']):
 if profile['passed']:continue
 parents=set(profile['sourceParents']);footprint=sh.geometry.shape(profile['asphaltGeometry'])
 records=sheet_entries([r for r in connections if r['kind']=='roadbed_overpass' and r['level']==profile['level'] and r.get('transport','vehicle')==profile['transport'] and parents.intersection(r['sourceParents'])],footprint,.00001)
 portals=[]
 for r in records:
  xy=np.asarray(sh.geometry.shape(r['mouthGeometry']).coords)[:,:2];ends=xy.copy();width=profile['sideOverhangM']
  ends[0]-=(xy[1]-xy[0])/np.linalg.norm(xy[1]-xy[0])*2*width;ends[-1]+=(xy[-1]-xy[-2])/np.linalg.norm(xy[-1]-xy[-2])*2*width
  extended=np.vstack([ends[0],xy,ends[-1]]);values=r.get('relativeHeightsM',[0.]*len(xy))
  portals.append((sh.LineString(extended),np.r_[0,np.cumsum(np.linalg.norm(np.diff(extended,axis=0),axis=1))],np.r_[values[0],values,values[-1]]))
 pt=sh.STRtree([p[0] for p in portals]);supports=[(sh.geometry.shape(r['geometry']),np.asarray(r['heightPlane'])) for r in profile['extensionHeightCells']]
 st=sh.STRtree([p for p,c in supports]);ground=sh.geometry.shape(profile['groundShoulderConnectionGeometry']);bad=[]
 for line in parts(ground,'LineString'):
  for j in st.query(line.buffer(.00003),predicate='intersects'):
   poly,c=supports[int(j)]
   for piece in parts(line.intersection(poly.buffer(.00003)),'LineString'):
    for di in dt.query(piece,predicate='intersects'):
     for edge in parts(piece.intersection(dem[int(di)][0]),'LineString'):
      for xy in np.asarray(edge.coords)[:,:2]:
       point=sh.Point(xy);pi=int(pt.nearest(point));hits=dt.query(point,predicate='covered_by');d=int(hits[0]) if len(hits) else int(dt.nearest(point))
       p,stations,values=portals[pi];expected=float(z_at(dem[d][1],xy)+np.interp(p.project(point),stations,values));actual=float(z_at(c,xy));error=abs(actual-expected)
       if error>.001:bad.append(dict(error=error,xy=xy.tolist(),actual=actual,expected=expected,support=int(j),cellArea=poly.area,distanceFromCell=poly.distance(point),plane=c.tolist(),portal=pi,distanceFromPortal=p.distance(point),connection=records[pi]))
 unique={tuple(np.round(r['xy'],5)):r for r in sorted(bad,key=lambda r:r['error'])};bad=sorted(unique.values(),key=lambda r:-r['error'])
 result.append(dict(profile=profile_index,bad=bad));print('PROFILE',profile_index,'BAD',len(bad),flush=True)
 for r in bad[:5]:print({k:v for k,v in r.items() if k!='connection'},'entry',r['connection']['id'],'heights',r['connection']['relativeHeightsM'],flush=True)
(root/'overpass-sheet-diagnostic.json').write_text(json.dumps(result,indent=2))
