import sys,pickle,json
from pathlib import Path
from collections import defaultdict
import numpy as np
import shapely as sh
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'prototype'))
from overpasses import build,parts
from build import triangulate,z_at,plane
path=Path(sys.argv[1]);w=pickle.load(path.open('rb'));groups=defaultdict(list)
profiles,count=build(w['surfaces'],w['dem'],sh.STRtree([p for p,c in w['dem']]),groups,w['extent'],.00001,triangulate,z_at,plane,w['connections'],prepartitioned=True)
emitted=[]
for (kind,material),faces in groups.items():
 if kind!='parapet_side':continue
 for t in faces:
  xy=np.unique(t[:,:2],axis=0)
  if len(xy)==2:emitted.append(sh.LineString(xy))
emitted=sh.union_all(emitted);result=[]
for p in profiles:
 expected=sh.geometry.shape(p['parapetGeometry']).boundary.difference(w['extent'].boundary.buffer(.00005))
 missing=expected.difference(emitted.buffer(.00005))
 result.append(dict(metrics={k:v for k,v in p.items() if 'Geometry' not in k and k not in ('sourceParents','extensionHeightCells')},
   missingGeometry=sh.geometry.mapping(missing),parapetGeometry=p['parapetGeometry'],emittedGeometry=sh.geometry.mapping(emitted)))
 print('MISSING',missing.length,'pieces',[(g.length,g.bounds) for g in parts(missing,'LineString')],flush=True)
path.with_suffix('.diagnostic.json').write_text(json.dumps(result,indent=2))
