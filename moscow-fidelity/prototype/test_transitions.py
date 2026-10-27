"""Analytic regressions for open grade connections, independent of Moscow XY."""
from pathlib import Path
from collections import defaultdict
import sys,numpy as np,shapely as sh
sys.path.insert(0,str(Path(__file__).resolve().parent))
from transitions import discover,terrain_cut,below
from overpasses import build as decks
from curbs import band
from build import triangulate,z_at,plane

precision=.00001;extent=sh.box(0,0,12,12)
ground=sh.box(0,4,2,8);ramp=sh.box(2,4,12,8)
dem=[]
for x in range(0,12,3):
 for y in range(0,12,3):
  for xy in [[(x,y),(x+3,y),(x+3,y+3)],[(x,y),(x+3,y+3),(x,y+3)]]:
   dem.append((sh.Polygon(xy),np.zeros(3)))
tree=sh.STRtree([p for p,c in dem])
def source(poly,c,part,level,owner):
 return dict(id=owner,kind='road',part=part,tiers=[level],poly=poly,patches=[(poly,c)])
flat=source(ground,np.zeros(3),'roadbed_flat',0,'test:ground')
for kind,sign in [('roadbed_overpass',1),('roadbed_tunnel_descent',-1)]:
 c=np.array([sign*.3,0,-sign*.6])
 raw=source(ramp,c,kind,sign,'test:ramp')
 connections,connectors=discover([flat,raw],ground,extent,precision,z_at)
 assert len(connections)==1 and not connectors,connections
 mouth=sh.geometry.shape(connections[0]['mouthGeometry'])
 assert abs(mouth.length-4)<1e-8 and mouth.distance(sh.LineString([(2,4),(2,8)]))<1e-8
 if sign==1:
  rows=[]
  for p,base in dem:
   g=p.intersection(ramp)
   if g.area>1e-9:rows.append(dict(kind=kind,tiers=[sign],owner='test:ramp',poly=g,plane=c))
  groups=defaultdict(list)
  profiles,_=decks(rows,dem,tree,groups,extent,precision,triangulate,z_at,plane,connections)
  cut=terrain_cut(profiles,rows,dem,tree,connections,.10,1.,precision)
  # At slope .3, the 1 m thick deck clears the 10 cm raised land at x=2+1.1/.3.
  assert cut.covers(sh.Point(2.01,6)) and cut.covers(sh.Point(5.6,3.5))
  assert not cut.covers(sh.Point(5.8,6)) and not cut.covers(sh.Point(9,6))
  assert abs(cut.bounds[2]-(2+1.1/.3))<precision
  para=sh.geometry.shape(profiles[0]['parapetGeometry'])
  assert not para.intersects(sh.box(2.001,4.1,2.1,7.9)), 'Transverse parapet at mouth'
 else:cut=ramp
 old_curb=band(ground,sh.Polygon(),extent,precision)
 new_curb=band(ground,cut,extent,precision)
 gate=sh.box(2.001,4.1,2.05,7.9)
 assert old_curb.intersects(gate) and not new_curb.intersects(gate),'Ground curb blocks passage'
 land=extent.difference(sh.union_all([ground,cut]))
 assert not land.intersects(gate),'Raised land blocks passage'

# Small source gap gets asphalt, rather than becoming an invented empty trench.
short_ground=sh.box(0,4,1.75,8)
connections,connectors=discover([source(short_ground,np.zeros(3),'roadbed_flat',0,'gap:ground'),
 source(ramp,np.array([.3,0,-.6]),'roadbed_overpass',1,'gap:ramp')],short_ground,extent,precision,z_at)
assert len(connections)==len(connectors)==1 and abs(connectors[0][1].area-1)<1e-8
assert sh.union_all([short_ground,connectors[0][1],ramp]).covers(sh.Point(1.9,6))

# An XY crossing five metres above ground establishes no at-grade mouth.
connections,_=discover([flat,source(ramp,np.array([0,0,5.]),'roadbed_overpass',1,'high:ramp')],
 ground,extent,precision,z_at)
assert not connections
c=np.array([.3,0,-.6]);saved=c.copy()
assert abs(below(ramp,c,1.1).area-(1.1/.3)*4)<1e-8
assert np.array_equal(c,saved),'Height clipping mutated a source plane'
print('Grade regressions passed: up/down ramps, open curb/land, continuous concrete shoulders, retained ground under high spans, recorded gap connector, no XY-only connection.')

# A structural-sheet split is an internal joint, not the end of the ground cut.
# Continue the low-volume cut across the joint until the slab clears terrain.
split_rows=[dict(kind='roadbed_overpass',tiers=[1],owner=o,poly=g,plane=c) for o,g,c in [
 ('start',sh.box(2,4,4,8),np.array([.2,0.,-.4])),
 ('next',sh.box(4,4,12,8),np.array([.2,0.,-.4])),
 ('high',sh.box(2,8,12,10),np.array([0.,0.,5.]))]]
split_profiles=[dict(level=[1],transport='vehicle',sourceParents=[r['owner']],deckDepthM=1.,extensionHeightCells=[]) for r in split_rows]
entry=[dict(kind='roadbed_overpass',level=[1],transport='vehicle',atGround=True,sourceParents=['start'],mouthGeometry=sh.geometry.mapping(sh.LineString([(2,4),(2,8)])))]
cut=terrain_cut(split_profiles,split_rows,[(extent,np.zeros(3))],sh.STRtree([extent]),entry,.1,1.,precision)
assert cut.covers(sh.Point(6,6)) and not cut.covers(sh.Point(10,6))
assert not cut.covers(sh.Point(6,9))
print('Split-profile regression passed: ground cut continues through the real low joint, and clear elevated spans retain ground.')
