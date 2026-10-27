import sys,pickle,json,time
from pathlib import Path
from collections import defaultdict
import shapely as sh
import numpy as np
root=Path(sys.argv[1]);w=pickle.load((root/'overpass-witness.pkl').open('rb'))
rows=[r for r in w['surfaces'] if r['tiers']==[1] and r.get('transport','vehicle')=='vehicle']
tree=sh.STRtree([r['poly'] for r in rows]);owners=sorted({r['owner'] for r in rows});parent={o:o for o in owners};links=[]
def find(o):
 while parent[o]!=o:parent[o]=parent[parent[o]];o=parent[o]
 return o
for i,a in enumerate(rows):
 for j in tree.query(a['poly'],predicate='intersects'):
  j=int(j)
  if j<=i:continue
  b=rows[j]
  if find(a['owner'])==find(b['owner']):continue
  edge=a['poly'].intersection(b['poly'])
  if edge.length<.0001 or edge.area>1e-8:continue
  xy=sh.get_coordinates(edge)
  difference=(np.c_[xy,np.ones(len(xy))]@(a['plane']-b['plane']))
  if len(xy) and np.max(abs(difference))<.001:
   links.append((a['owner'],b['owner']));parent[find(b['owner'])]=find(a['owner'])
 if i%20000==0:print('ROW',i,'LINKS',len(links),flush=True)
groups=defaultdict(list)
for owner in owners:groups[find(owner)].append(owner)
out={owner:find(owner) for owner in owners}
(root/'overpass-owner-components.json').write_text(json.dumps(out,indent=2))
print('COMPONENTS',len(groups),sorted(map(len,groups.values()),reverse=True),flush=True)
for issue in json.loads((root/'overpass-join-diagnostic.json').read_text()):
 names=issue['connection']['sourceParents']+[r['owner'] for r in issue['nearestRoads'][:4]]
 print(issue['xy'],[(o,out.get(o)) for o in dict.fromkeys(names)],flush=True)
