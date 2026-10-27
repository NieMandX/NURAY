import numpy as np
import shapely as sh
from collections import defaultdict
from semantics import classify
from source_styles import load
from tunnel_walls import build
from build import triangulate,z_at,plane,SOURCE

ped=classify('Roadbed_underpasses',{'db_road_part':'roadbed_tunnel_descent','db_tiers':[-1],'db_is_staircase':1},'polygon')
assert ped['purpose']=='pedestrian' and ped['construction']=='descent' and ped['material']==7
car=classify('Main_Roadbed',{'db_road_part':'roadbed_tunnel','db_tiers':[-1]},'polygon')
assert car['purpose']=='motor-traffic' and car['construction']=='underground' and car['material']==0
unknown=classify('New_Roadbed_surprise',{'db_road_part':'roadbed_flat'},'polygon')
assert unknown['material'] is None and unknown['status']=='unsupported-surface'
assert classify('Immersive_park_polygon_pedestrian_asphalt',{},'polygon')['purpose']=='pedestrian'
assert classify('Transport_Roadbed',{},'polygon')['material']!=0
assert classify('Administrative_house',{'db_road_part':'roadbed_flat'},'polygon')['status']=='deferred'
assert classify('Underpass_entrance',{'db_road_part':'roadbed_tunnel'},'polygon')['purpose']=='building'

extent=sh.box(-3,-3,13,7);core=sh.box(0,0,10,4);floor=np.array([-.3,0,0])
surfaces=[dict(kind='roadbed_tunnel_descent',poly=core,plane=floor,owner='source:descent',tiers=[-1])]
records=[]
for y in [0,4]:
    records.append(dict(id=f'source:side:{y}',layer='Roadbed_outline',coordinates=[[0,y,0],[10,y,-3]],properties={'db_road_part':'border_tunnel_descent','db_tiers':[-1]}))
records.append(dict(id='source:arch',layer='Roadbed_outline',coordinates=[[10,0,0],[10,4,0]],properties={'db_road_part':'tunnel_arch'}))
connections=[dict(kind='roadbed_tunnel_descent',sourceParents=['source:descent'],mouthGeometry=sh.geometry.mapping(sh.LineString([(0,0),(0,4)])))]
dem=[(extent,np.zeros(3))];tree=sh.STRtree([extent]);style=load(SOURCE/'source/style_flat.json')
groups=defaultdict(list)
count,report=build(surfaces,records,dem,tree,groups,extent,1e-5,connections,style,triangulate,z_at,plane)
assert report['passed'],report
r=report['groups'][0];assert len(r['matchedSourceBorders'])==2 and r['fallbackBoundaryM']<.001
band=sh.geometry.shape(r['bandGeometry'])
assert band.intersection(core).area==0
assert not band.intersects(sh.box(-.01,.01,.01,3.99)) and not band.intersects(sh.box(9.99,.01,10.01,3.99))
for t in groups[('tunnel_wall_top',6)]:assert np.max(abs(t[:,2]-1.1))<1e-8
assert r['uncoveredSolidSidesM']<.001
wrong=[{**r,'coordinates':[[x,y,z+2] for x,y,z in r['coordinates']]} for r in records]
_,rejected=build(surfaces,wrong,dem,tree,defaultdict(list),extent,1e-5,connections,style,triangulate,z_at,plane)
assert not rejected['groups'][0]['matchedSourceBorders']
assert rejected['groups'][0]['fallbackBoundaryM']>19
print('Passed: independent purpose/structure/material, unknown road rejection; source-matched solid walls, open mouth/arch, closed sides, ground guard height; wrong-height contours rejected and fallback reported.')

# Oblique source borders split across independent terrain triangles must not
# lose side faces when their top-cell boundaries are snapped independently.
angle=np.radians(37);rotation=np.array([[np.cos(angle),-np.sin(angle)],[np.sin(angle),np.cos(angle)]])
def rotated(xyz):
    xyz=np.asarray(xyz,dtype=float).copy();xyz[:,:2]=xyz[:,:2]@rotation.T
    return xyz
rot_core=sh.set_precision(sh.Polygon(np.asarray(core.exterior.coords)@rotation.T),1e-5)
rot_floor=plane(rotated([[0,0,0],[10,0,-3],[0,4,0]]))
rot_rows=[dict(surfaces[0],poly=rot_core,plane=rot_floor)]
rot_records=[dict(r,coordinates=rotated(r['coordinates']).tolist()) for r in records]
rot_connections=[dict(connections[0],mouthGeometry=sh.geometry.mapping(sh.LineString(np.array([[0,0],[0,4]])@rotation.T)))]
large=sh.box(-10,-10,20,20)
terrain=[(sh.Polygon([(-10,-10),(20,-10),(20,20)]),np.zeros(3)),(sh.Polygon([(-10,-10),(20,20),(-10,20)]),np.zeros(3))]
_,oblique=build(rot_rows,rot_records,terrain,sh.STRtree([p for p,c in terrain]),defaultdict(list),large,1e-5,rot_connections,style,triangulate,z_at,plane)
assert oblique['passed'],oblique
assert oblique['groups'][0]['uncoveredSolidSidesM']<.001
print('Passed: rotated retaining-wall footprint remains closed across independently quantized terrain cells.')

oblique_core=sh.Polygon([(0,0),(10,0),(11,4),(0,4)])
peer=sh.Polygon([(10,0),(11,4),(11,5),(16,5),(16,-1),(9,-1)])
joined_rows=[dict(surfaces[0],poly=oblique_core),dict(kind='roadbed_tunnel',poly=peer,plane=floor,owner='source:peer',tiers=[-1])]
joined_sources=[dict(id='source:low',layer='Roadbed_outline',coordinates=[[0,0,0],[10,0,-3]],properties={'db_road_part':'border_tunnel_descent','db_tiers':[-1]}),dict(id='source:high',layer='Roadbed_outline',coordinates=[[0,4,0],[11,4,-3.3]],properties={'db_road_part':'border_tunnel_descent','db_tiers':[-1]})]
joined_connections=[connections[0],dict(kind='roadbed_tunnel_descent',sourceParents=['source:descent'],peerParents=['source:peer'],mouthGeometry=sh.geometry.mapping(sh.LineString([(10,0),(11,4)])))]
large=sh.box(-3,-3,20,8);terrain=[(large,np.zeros(3))]
_,joined=build(joined_rows,joined_sources,terrain,sh.STRtree([large]),defaultdict(list),large,1e-5,joined_connections,style,triangulate,z_at,plane)
assert joined['passed'],joined
assert sh.geometry.shape(joined['groups'][0]['bandGeometry']).intersection(peer).area<1e-8
unrelated=[joined_connections[0],dict(joined_connections[1],peerParents=[])]
_,unjoined=build(joined_rows,joined_sources,terrain,sh.STRtree([large]),defaultdict(list),large,1e-5,unrelated,style,triangulate,z_at,plane)
assert sh.geometry.shape(unjoined['groups'][0]['bandGeometry']).intersection(peer).area>.05
print('Passed: walls respect a widening connected peer at an oblique mouth; an unconnected overlapping floor does not delete walls.')

# Proximity alone used to accept tiny perpendicular returns at the ground
# entrance. Their single-sided buffer then projected a full wall width beyond
# the entrance. Reject those fragments without trimming legitimate side ends.
tip_groups=defaultdict(list)
_,tips=build(surfaces,records,dem,tree,tip_groups,extent,1e-5,[],style,triangulate,z_at,plane)
tip=tips['groups'][0];tip_band=sh.geometry.shape(tip['bandGeometry'])
assert tip['rejectedTransverseMatches']>0
assert tip_band.bounds[0]>=-1e-5 and tip_band.bounds[2]<=10.00001
assert tip_band.intersection(sh.box(-1,-2,0,6)).area<1e-9
assert tip['sourceMatchedBoundaryM']>19.89

# A deep portal needs a short roof fascia, never a floor-height transverse wall.
header=r['portalHeaders'];assert header['count']==1 and header['passed']
assert header['minPassageHeightM']>2
for name in ['portal_guard_top','portal_guard_bottom','portal_guard_side']:
    assert groups[(name,6)]
    vertices=np.asarray(groups[(name,6)]).reshape(-1,3)
    assert vertices[:,0].min()>9.99, 'Entrance must remain open'
    assert vertices[:,2].min()>=-.40001, 'Fascia must not reach the passage floor'
    assert vertices[:,2].max()<=1.10001

# Reversed/split source arches and a misleading arch at zero depth do not
# change geometry or grow an entrance guard; this is also the tile-seam case.
split=[r for r in records if r['properties']['db_road_part']!='tunnel_arch']
for i,(a,b) in enumerate([([10,0,0],[10,2,0]),([10,4,0],[10,2,0]),([0,0,0],[0,4,0])]):
    split.append(dict(id=f'arch:{i}',layer='Roadbed_outline',coordinates=[a,b],properties={'db_road_part':'tunnel_arch'}))
_,split_result=build(surfaces,split,dem,tree,defaultdict(list),extent,1e-5,connections,style,triangulate,z_at,plane)
other=split_result['groups'][0]['portalHeaders']
assert other['count']==1 and other['skipped']
assert sh.geometry.shape(header['bandGeometry']).symmetric_difference(sh.geometry.shape(other['bandGeometry'])).area<1e-8

# Pedestrian floors are raised to meet the same sidewalk; their higher guard
# must still be gray concrete, and their below-ground surface is beige paving.
ped_rows=[dict(surfaces[0],transport='pedestrian',plane=floor+[0,0,.1])]
ped_records=[dict(r,layer='Roadbed_outline_underpasses') for r in records]
ped_groups=defaultdict(list)
_,ped_result=build(ped_rows,ped_records,dem,tree,ped_groups,extent,1e-5,connections,style,triangulate,z_at,plane)
assert ped_result['passed'] and ped_result['groups'][0]['portalHeaders']['count']==1
assert all(material==6 for name,material in ped_groups if ped_groups[(name,material)])
for t in ped_groups[('portal_guard_top',6)]:assert abs(t[:,2]-1.1).max()<1e-8
print('Passed: no perpendicular-buffer ears; deep portal has a short header with free passage; ground entrance stays open; split/reversed arches are invariant; pedestrian concrete and paving are distinct.')
