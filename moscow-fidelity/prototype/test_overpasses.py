from pathlib import Path
import sys,numpy as np,shapely as sh
from collections import defaultdict
sys.path.insert(0,str(Path(__file__).resolve().parent))
from overpasses import build
from build import triangulate,z_at,plane
height_tolerance=.00002  # Two XY precision-grid units at the inward mouth cut.
extent=sh.box(0,0,12,12);core=sh.box(2,4,12,8);c=np.array([.3,0,-.6]);dem=[];rows=[]
for x in range(0,12,3):
 for y in range(0,12,3):
  for coords in [[(x,y),(x+3,y),(x+3,y+3)],[(x,y),(x+3,y+3),(x,y+3)]]:
   p=sh.Polygon(coords);dem.append((p,np.zeros(3)));g=p.intersection(core)
   if g.area>1e-9:rows.append(dict(kind='roadbed_overpass',tiers=[1],owner='synthetic:ramp',poly=g,plane=c))
groups=defaultdict(list)
profiles,count=build(rows,dem,sh.STRtree([p for p,c in dem]),groups,extent,.00001,triangulate,z_at,plane)
p=profiles[0];assert p['passed'],p
assert p['groundEntrySegments']>0
assert sh.geometry.shape(p['deckGeometry']).bounds==(2.,3.,12.,9.)
para=sh.geometry.shape(p['parapetGeometry'])
assert para.covers(sh.Point(7,3.1)) and not para.covers(sh.Point(7,3.21))
assert not para.covers(sh.Point(2.05,6)), 'Parapet blocks ramp entry'
for t in groups[('overpass_bottom',10)]:assert np.max(abs(t[:,2]-z_at(c,t[:,:2])+1))<height_tolerance
for t in groups[('overpass_shoulder',10)]:assert np.max(abs(t[:,2]-z_at(c,t[:,:2])-.1))<height_tolerance
for t in groups[('parapet_top',10)]:assert np.max(abs(t[:,2]-z_at(c,t[:,:2])-.7))<height_tolerance
assert groups[('overpass_riser',10)]
for t in groups[('overpass_riser',10)]:
 offset=t[:,2]-z_at(c,t[:,:2])
 assert abs(offset.min())<height_tolerance and abs(offset.max()-.1)<height_tolerance
 xy=np.unique(t[:,:2],axis=0);assert len(xy)==2
 assert not sh.LineString(xy).intersects(sh.box(2-.001,4.1,2+.001,7.9)), 'Riser across open mouth'
 normal=np.cross(t[1]-t[0],t[2]-t[0]);normal=normal[:2]/np.linalg.norm(normal[:2])
 assert core.buffer(.0001).covers(sh.Point(t[:,:2].mean(0)+normal*.001)), 'Shoulder riser faces away from road'
for t in groups[('overpass_side',10)]:
 offsets=t[:,2]-z_at(c,t[:,:2]);assert abs(offsets.min()+1)<height_tolerance
 extension=sh.geometry.shape(p['deckGeometry']).difference(core)
 expected=.1 if extension.distance(sh.Point(t[:,:2].mean(0)))<.00001 else 0
 assert abs(offsets.max()-expected)<height_tolerance
for t in groups[('parapet_side',10)]:
 offsets=t[:,2]-z_at(c,t[:,:2]);assert abs(offsets.min()-.1)<height_tolerance and abs(offsets.max()-.7)<height_tolerance
print('Ramp regression passed: shoulder +10 cm, closed inward riser/end/outer faces, underside -1 m, parapet top +70 cm; open entry/crop.')

# A cross-sloping terrain exposes the old outward-projection gap at the mouth.
# Check the actual shoulder triangles on both sides, not just profile metadata.
crossfall=np.array([0,.02,0])
sloped_dem=[(g,d+crossfall) for g,d in dem]
sloped_rows=[{**r,'plane':r['plane']+crossfall} for r in rows]
sloped_groups=defaultdict(list)
sloped_profiles,_=build(sloped_rows,sloped_dem,sh.STRtree([g for g,d in sloped_dem]),sloped_groups,extent,.00001,triangulate,z_at,plane)
assert sloped_profiles[0]['passed'],sloped_profiles
for xy in [[2.00005,3.5],[2.00005,8.5]]:
 point=sh.Point(xy);heights=[]
 for t in sloped_groups[('overpass_shoulder',10)]:
  if sh.Polygon(t[:,:2]).buffer(.000001).covers(point):heights.append(float(z_at(plane(t),xy)))
 assert heights and max(abs(h-(z_at(crossfall,xy)+.10)) for h in heights)<.00001,(xy,heights)
print('Crossfall regression passed: raised shoulders meet raised ground at both mouth ends without a height gap.')

# An oblique side makes the nearest projection of the outer mouth end fall
# partway up the ramp. The end must still meet ground, not that raised point.
oblique=sh.Polygon([(2,4),(12,6),(12,10),(2,8)])
oblique_rows=[]
for g,d in dem:
 piece=g.intersection(oblique)
 if piece.area>1e-9:oblique_rows.append(dict(kind='roadbed_overpass',tiers=[1],owner='synthetic:oblique',poly=piece,plane=c))
oblique_groups=defaultdict(list)
oblique_profiles,_=build(oblique_rows,dem,sh.STRtree([g for g,d in dem]),oblique_groups,extent,.00001,triangulate,z_at,plane)
assert oblique_profiles[0]['passed'],oblique_profiles
point=sh.Point(2.00005,8.5);heights=[]
for t in oblique_groups[('overpass_shoulder',10)]:
 if sh.Polygon(t[:,:2]).buffer(.000001).covers(point):heights.append(float(z_at(plane(t),[2.00005,8.5])))
assert heights and max(abs(h-.10) for h in heights)<.00001,heights
print('Oblique-mouth regression passed: shoulder end matches ground despite nearest-source projection landing up the ramp.')

# A short noded mouth-end segment must use its original inside/outside probe.
# Extending its endpoints before probing used to generate an L-shaped end cap.
noded=[dict(kind='roadbed_overpass',level=[1],mouthGeometry=sh.geometry.mapping(sh.LineString([(2,4),(2,6.5),(2,8)])))]
noded_groups=defaultdict(list)
noded_profiles,_=build(rows,dem,sh.STRtree([g for g,d in dem]),noded_groups,extent,.00001,triangulate,z_at,plane,noded)
assert noded_profiles[0]['passed'],noded_profiles
assert sh.geometry.shape(noded_profiles[0]['deckGeometry']).bounds==(2.,3.,12.,9.), 'Unwanted transverse deck cap at short mouth fragment'
assert not sh.geometry.shape(noded_profiles[0]['parapetGeometry']).intersects(sh.box(1.9,4.01,2.01,7.99)), 'Transverse parapet at noded mouth'
print('Noded-mouth regression passed: no L-shaped deck/parapet end cap at a short mouth segment.')

# Overlay rounding must not turn a one-grid-unit roof remnant into a 10 cm
# wall across the entrance. The numerical cut tolerance resolves that band.
shifted=sh.box(2.00001,4,12,8)
shifted_rows=[{**r,'poly':r['poly'].intersection(shifted)} for r in rows if r['poly'].intersection(shifted).area>1e-9]
shifted_profiles,_=build(shifted_rows,dem,sh.STRtree([g for g,d in dem]),defaultdict(list),extent,.00001,triangulate,z_at,plane,noded)
assert shifted_profiles[0]['passed'],shifted_profiles
assert shifted_profiles[0]['raisedConcreteInEntryPassageM2']<.0001
assert shifted_profiles[0]['shoulderRiserInEntryPassageM']==0
print('Precision regression passed: slightly different mouth/mesh rounding creates no transverse raised remnant.')

# A bent mouth needs joined offsets at every intermediate vertex. Independent
# outside rectangles used to leave a triangular island, subsequently extruded
# into a detached 70 cm parapet even though the driveable gate was clear.
bent_points=[(2,4),(2.1,6.5),(2.2,8)]
bent_core=sh.Polygon([*bent_points,(12,8),(12,4)])
bent_rows=[]
for g,d in dem:
 piece=g.intersection(bent_core)
 if piece.area>1e-9:bent_rows.append(dict(kind='roadbed_overpass',tiers=[1],owner='synthetic:bent-mouth',poly=piece,plane=np.zeros(3)))
bent_connection=[dict(kind='roadbed_overpass',level=[1],mouthGeometry=sh.geometry.mapping(sh.LineString(bent_points)))]
bent_profiles,_=build(bent_rows,dem,sh.STRtree([g for g,d in dem]),defaultdict(list),extent,.00001,triangulate,z_at,plane,bent_connection)
assert bent_profiles[0]['passed'],bent_profiles
deck=sh.geometry.shape(bent_profiles[0]['deckGeometry'])
assert all(part.intersection(bent_core).area>1e-9 for part in sh.get_parts(deck)), 'Detached concrete/parapet island at bent mouth'
assert bent_profiles[0]['detachedConcreteAreaM2']==0
print('Bent-mouth regression passed: continuous joined cut leaves no detached concrete or full-height parapet island.')

# Two decks can have the same drawing tier and lie within the extended mouth
# line while differing by five metres in height. The low ramp must not cut the
# higher neighbour's shoulder or its longitudinal guard.
neighbour=sh.box(0,9.2,12,11.2)
neighbour_rows=[]
for g,d in dem:
 piece=g.intersection(neighbour)
 if piece.area>1e-9:neighbour_rows.append(dict(kind='roadbed_overpass',tiers=[1],owner='synthetic:high-deck',poly=piece,plane=np.array([0.,0.,5.])))
owned_connection=[{**noded[0],'id':'synthetic:low-entry','sourceParents':['synthetic:ramp']}]
neighbour_groups=defaultdict(list)
neighbour_profiles,_=build(rows+neighbour_rows,dem,sh.STRtree([g for g,d in dem]),neighbour_groups,extent,.00001,triangulate,z_at,plane,owned_connection)
assert all(p['passed'] for p in neighbour_profiles),neighbour_profiles
high=next(p for p in neighbour_profiles if 'synthetic:high-deck' in p['sourceParents'])
low=next(p for p in neighbour_profiles if 'synthetic:ramp' in p['sourceParents'])
deck=sh.geometry.shape(high['deckGeometry'])
guard=sh.geometry.shape(high['parapetGeometry'])
assert deck.covers(sh.Point(1,8.5)), 'Another ramp mouth removed the higher deck shoulder'
assert guard.covers(sh.Point(1,8.25)), 'Another ramp mouth cut the higher deck lateral guard'
heights=[]
for t in neighbour_groups[('overpass_shoulder',10)]:
 if sh.Polygon(t[:,:2]).covers(sh.Point(1,8.5)):heights.append(float(z_at(plane(t),[1,8.5])))
assert heights and max(abs(h-5.1) for h in heights)<.00001,heights
assert not sh.geometry.shape(low['parapetGeometry']).intersects(sh.box(1.999,4.1,2.001,7.9)), 'Owning low ramp entry is blocked'
print('Ownership regression passed: a low mouth preserves the neighbouring high deck and guard; its own entry remains open.')

# The two parallel branches reconnect farther away. A connected-component-only
# fix would merge them again and reproduce the low-mouth/high-shoulder bug.
loop_extent=sh.box(0,0,16,14);loop_dem=[(loop_extent,np.zeros(3))]
loop_rows=[dict(kind='roadbed_overpass',tiers=[1],owner=o,poly=g,plane=c) for o,g,c in [
 ('low',sh.box(2,4,12,8),np.array([.5,0.,-1.])),
 ('high',sh.box(0,9.2,12,11.2),np.array([0.,0.,5.])),
 ('join',sh.box(12,4,15,11.2),np.array([0.,0.,5.]))]]
loop_connections=[dict(kind='roadbed_overpass',level=[1],id='loop-entry',sourceParents=['low'],mouthGeometry=sh.geometry.mapping(sh.LineString([(2,4),(2,8)])))]
loop_profiles,_=build(loop_rows,loop_dem,sh.STRtree([loop_extent]),defaultdict(list),loop_extent,.00001,triangulate,z_at,plane,loop_connections)
assert len(loop_profiles)==2 and all(p['passed'] for p in loop_profiles),loop_profiles
low_profile=next(p for p in loop_profiles if 'low' in p['sourceParents'])
high_profile=next(p for p in loop_profiles if 'high' in p['sourceParents'])
assert low_profile is not high_profile
assert sh.geometry.shape(high_profile['deckGeometry']).covers(sh.Point(1,8.5))
joint=sh.box(11.999,9.3,12.001,11.1)
assert all(not sh.geometry.shape(p['parapetGeometry']).intersects(joint) for p in loop_profiles)
print('Reconnecting-branches regression passed: separate height sheets preserve the real open joint farther along the network.')

# A third owner may touch the endpoint of a valid sheet joint at a different
# height. It joins the high branch elsewhere, but must not supply that joint's
# datum merely because its polygon has zero distance to the endpoint.
from overpass_sheets import structural_sheets
corner=sh.Polygon([(12,9.2),(13,8.8),(13,9.2)])
corner_rows=[dict(r) for r in loop_rows]
corner_rows[2]['poly']=corner_rows[2]['poly'].difference(corner)
corner_rows.append(dict(kind='roadbed_overpass',tiers=[1],owner='a-corner',
 poly=corner,plane=np.array([-.01,0.,5.13])))
sheets,connections=structural_sheets(corner_rows,loop_connections,loop_dem,sh.STRtree([loop_extent]),.00001,z_at)
checked=0
for entry in connections:
 if not entry['id'].startswith('structural-sheet-interface:'):continue
 for xy,h in zip(entry['mouthGeometry']['coordinates'],entry['relativeHeightsM']):
  if np.linalg.norm(np.asarray(xy)-[12,9.2])<.00001:
   assert abs(h-5.)<.00001,(xy,h)
   checked+=1
assert checked>=2
print('Joint-datum regression passed: a coincident third owner cannot change the accepted shared-edge height.')

# A ground mouth and an elevated internal seam meet only through their
# extended shoulders. Their common outside corner must have one height, while
# every original source mouth node retains its measured relative height.
from overpass_sheets import joined_portal_datums
originals=[sh.LineString([(0,0),(3,0)]),sh.LineString([(-.75,1.2),(-.75,5.2)])]
datums=[(sh.LineString([(-2,0),(0,0),(3,0),(5,0)]),np.array([0,2,5,7]),np.zeros(4)),
 (sh.LineString([(-.75,-.8),(-.75,1.2),(-.75,5.2),(-.75,7.2)]),np.array([0,2,6,8]),np.array([.18,.18,.78,.78]))]
joined=joined_portal_datums(datums,originals,sh.Polygon(),.00001)
for line,stations,heights in joined:
 assert abs(np.interp(line.project(sh.Point(-.75,0)),stations,heights))<1e-10
line,stations,heights=joined[1]
assert abs(np.interp(line.project(sh.Point(-.75,1.2)),stations,heights)-.18)<1e-10
assert abs(np.interp(line.project(sh.Point(-.75,.6)),stations,heights)-.09)<1e-10
print('Intersecting-shoulders regression passed: shared corner height and continuous interpolation preserve source nodes.')

# Three extensions meet at the same outside corner. Pairwise authority would
# assign the second mouth's height to one pair and the first mouth's to another.
c_original=sh.LineString([(-1.75,1),(-3.75,3)])
c_line=sh.LineString([(-.3357864376269051,-.4142135623730949),(-1.75,1),(-3.75,3),(-5.164213562373095,4.414213562373095)])
c_xy=np.asarray(c_line.coords);c_stations=np.r_[0,np.cumsum(np.linalg.norm(np.diff(c_xy,axis=0),axis=1))]
three=joined_portal_datums([*datums,(c_line,c_stations,np.array([.4,.4,.8,.8]))],[*originals,c_original],sh.Polygon(),.00001)
for line,stations,heights in three:
 assert abs(np.interp(line.project(sh.Point(-.75,0)),stations,heights))<1e-10
print('Three-mouth regression passed: one common corner datum is chosen for all incident extensions.')

from shapely.affinity import translate
shifted_c=translate(c_line,xoff=.00002);shifted_original=translate(c_original,xoff=.00002)
near_corner=joined_portal_datums([*datums,(shifted_c,c_stations,np.array([.4,.4,.8,.8]))],[*originals,shifted_original],sh.Polygon(),.00001)
for line,stations,heights in near_corner:
 assert abs(np.interp(line.project(sh.Point(-.75,0)),stations,heights))<.00001
print('Rounded-corner regression passed: micrometre-separated offset intersections share one physical height node.')

# A drawing-tier change at a fork is not a physical seam. A narrow triangle
# at its nose must join the same sheet, with no independent transverse cap.
fork_extent=sh.box(-10,-10,30,30);fork_dem=[(fork_extent,np.zeros(3))]
fork_rows=[dict(kind='roadbed_overpass',tiers=tiers,owner=owner,poly=poly,plane=np.array([0.,0.,5.]))
 for owner,tiers,poly in [('left',[1],sh.box(0,0,10,10)),
                          ('right',[2],sh.box(10,0,20,10)),
                          ('nose',[2],sh.Polygon([(0,10),(20,10),(10,11)]))]]
fork_entries=[dict(id='drawing-seam',kind='roadbed_overpass',peerKind='roadbed_overpass',
    level=[1],sourceParents=['left'],peerParents=['right'],
    mouthGeometry=sh.geometry.mapping(sh.LineString([(10,0),(10,10)])),
    relativeHeightsM=[5.,5.],atGround=False)]
fork_profiles,_=build(fork_rows,fork_dem,sh.STRtree([fork_extent]),defaultdict(list),fork_extent,
    .00001,triangulate,z_at,plane,fork_entries)
assert len(fork_profiles)==1 and fork_profiles[0]['passed']
assert fork_profiles[0]['level']==[1,2]
assert not sh.geometry.shape(fork_profiles[0]['parapetGeometry']).intersects(sh.box(9.99,1,10.01,9))
print('Mixed-tier fork regression passed: one continuous physical contour and no internal cap.')

# A continuous sloping loop may link two floors with the same XY. Their
# shared connected component must not flatten them into one planar footprint.
stack_rows=[dict(kind='roadbed_overpass',tiers=tiers,owner=owner,poly=poly,plane=c)
 for owner,tiers,poly,c in [('lower',[1],sh.box(0,0,10,10),np.array([0.,0.,5.])),
 ('upper',[2],sh.box(0,0,10,10),np.array([0.,0.,10.])),
 ('ramp',[1],sh.box(10,0,20,10),np.array([.5,0.,0.]))]]
stack_sheets,_=structural_sheets(stack_rows,[],fork_dem,sh.STRtree([fork_extent]),.00001,z_at)
assert not any({'lower','upper'} <= {r['owner'] for r in rs} for level,mode,rs in stack_sheets)
print('Stacked-floor regression passed: a physical crossing remains separate across drawing tiers.')

# The shoulder cut reaches farther than two overhang widths diagonally.
# An elevated neighbour 2.6 m away must not join a low mouth's sheet merely
# because their roads reconnect outside the mouth region.
far_rows=[dict(r) for r in loop_rows]
far_rows[1].update(tiers=[2],poly=sh.box(0,10.6,12,12.6))
far_rows[2].update(poly=sh.box(12,4,15,12.6))
far_sheets,_=structural_sheets(far_rows,loop_connections,loop_dem,sh.STRtree([loop_extent]),.00001,z_at)
assert not any({'low','high'}<={r['owner'] for r in rs} for level,mode,rs in far_sheets)
print('Diagonal mouth reach regression passed: nearby high shoulders cannot be cut by a low entry.')

# Partitioning the mouth owner must not move its cut one owner upstream.
split_rows=[dict(r) for r in loop_rows if r['owner']!='low']
split_rows.extend(dict(loop_rows[0],owner=owner,poly=poly)
                  for owner,poly in [('low',sh.box(2,4,4,8)),('upstream',sh.box(4,4,12,8))])
split_sheets,_=structural_sheets(split_rows,loop_connections,loop_dem,sh.STRtree([loop_extent]),.00001,z_at)
assert not any({'upstream','high'}<={r['owner'] for r in rs} for level,mode,rs in split_sheets)
print('Potential interface regression passed: partition cuts cannot migrate into a different-height neighbour.')

# An extended internal joint can end beside a returning part of the SAME
# continuous slab. Its outside datum must approach that source edge instead
# of making a vertical crease across a millimetre-wide shoulder.
return_extent=sh.box(-5,-4,8,8)
return_rows=[dict(kind='roadbed_overpass',tiers=[1],owner=owner,poly=g,plane=c)
 for owner,g,c in [('main',sh.box(0,0,5,5),np.array([0,.05,2.])),
                   ('return',sh.box(-3,-2,-2.005,4),np.array([-1/15,.05,2.])),
                   ('bend',sh.box(-3,4,0,5),np.array([-1/15,.05,2.]))]]
return_entries=[dict(id='internal-returning-joint',kind='roadbed_overpass',transport='vehicle',
 sourceParents=['main'],mouthGeometry=sh.geometry.mapping(sh.LineString([(0,0),(5,0)])),
 relativeHeightsM=[2.,2.],atGround=False,datumPolicy='source-shared-edge')]
return_groups=defaultdict(list)
return_profiles,_=build(return_rows,[(return_extent,np.zeros(3))],sh.STRtree([return_extent]),return_groups,
 return_extent,1e-5,triangulate,z_at,plane,return_entries,prepartitioned=True)
assert all(p['passed'] for p in return_profiles),return_profiles
print('Returning slab regression passed: shoulder endpoint follows the nearby source edge without a height crease.')

# Agreement along only part of a shared source edge cannot merge the complete
# owners. Preserve the agreeing part as an open joint between separate sheets.
partial_extent=sh.box(-2,-2,12,4);partial_dem=[(partial_extent,np.zeros(3))]
partial_rows=[dict(kind='roadbed_overpass',tiers=[1],owner=owner,poly=poly,plane=c) for owner,poly,c in [
 ('a',sh.box(0,0,5,2),np.zeros(3)),
 ('b',sh.box(5,0,10,1),np.zeros(3)),
 ('b',sh.box(5,1,10,2),np.array([0.,.004,-.004]))]]
partial_sheets,partial_connections=structural_sheets(partial_rows,[],partial_dem,sh.STRtree([partial_extent]),1e-5,z_at)
assert len(partial_sheets)==2, 'A partially agreeing source edge merged incompatible heights'
assert len(partial_connections)==2
for joint in partial_connections:
 assert sh.geometry.shape(joint['mouthGeometry']).equals(sh.LineString([(5,0),(5,1)]))
print('Partial-edge regression passed: incompatible owner heights remain separate while their valid shared interval stays open.')

# An exact boundary node can belong to two source faces whose rounded heights
# differ by 1.5 mm. Their common shoulder node has a minimax error of 0.75 mm;
# the accepted 1 mm join tolerance remains unchanged, independent of row order.
corner_extent=sh.box(0,0,14,12);corner_dem=[(corner_extent,np.zeros(3))]
corner_rows=[dict(kind='roadbed_overpass',tiers=[1],owner='corner',poly=poly,plane=np.array([0.,0.,h]))
             for poly,h in [(sh.box(2,4,7,8),0.),(sh.box(7,4,12,8),.0015)]]
for ordered in (corner_rows,corner_rows[::-1]):
 corner_profiles,_=build(ordered,corner_dem,sh.STRtree([corner_extent]),defaultdict(list),corner_extent,1e-5,triangulate,z_at,plane,[])
 assert all(p['passed'] for p in corner_profiles),corner_profiles
 assert abs(corner_profiles[0]['maxSourceCornerResolutionM']-.00075)<1e-9
 assert corner_profiles[0]['maxAsphaltShoulderHeightMismatchM']<.001
print('Shared-corner regression passed: both source faces meet the common shoulder within the unchanged tolerance.')
