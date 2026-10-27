import sys,pickle,json
from pathlib import Path
from collections import defaultdict
import shapely as sh
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'prototype'))
from overpasses import build
from build import triangulate,z_at,plane
for path in map(Path,sys.argv[1:]):
 w=pickle.load(path.open('rb'));groups=defaultdict(list)
 for r in w['connections']:
  if r.get('id','').startswith('structural-sheet-interface:'):r['datumPolicy']='source-shared-edge'
 profiles,count=build(w['surfaces'],w['dem'],sh.STRtree([p for p,c in w['dem']]),groups,w['extent'],.00001,triangulate,z_at,plane,w['connections'],prepartitioned=True)
 result=[{k:v for k,v in p.items() if 'Geometry' not in k and k not in ('sourceParents','extensionHeightCells')} for p in profiles]
 print(path.name,result,flush=True)
 path.with_suffix('.v7.json').write_text(json.dumps(result,indent=2))
 assert all(p['passed'] for p in profiles)
