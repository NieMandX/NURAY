import sys,pickle
from pathlib import Path
import shapely as sh
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'prototype'))
from overpass_sheets import structural_sheets
from build import z_at
root=Path(sys.argv[1]);w=pickle.load((root/'failed-overpass-rebuild.pkl').open('rb'))
tree=sh.STRtree([p for p,c in w['dem']]);_,connections=structural_sheets(w['surfaces'],w['connections'],w['dem'],tree,.00001,z_at)
for i,p in enumerate(w['profiles']):
 if p['passed']:continue
 parents=set(p['sourceParents']);rows=[r for r in w['surfaces'] if r['owner'] in parents and r['tiers']==p['level'] and r.get('transport','vehicle')==p['transport']]
 reach=sh.geometry.shape(p['deckGeometry']).buffer(3.)
 dem=[w['dem'][int(i)] for i in sorted(tree.query(reach,predicate='intersects'))]
 entries=[r for r in connections if r['kind']=='roadbed_overpass' and r['level']==p['level'] and r.get('transport','vehicle')==p['transport'] and parents.intersection(r['sourceParents'])]
 path=root/f'overpass-failure-{i}.input.pkl'
 with path.open('wb') as f:pickle.dump(dict(surfaces=rows,dem=dem,connections=entries,extent=w['extent']),f)
 print('EXTRACTED',path,len(rows),len(dem),flush=True)
