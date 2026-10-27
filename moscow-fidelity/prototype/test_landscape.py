"""Regression witnesses for network-first landscape geometry."""
import json
from pathlib import Path
import numpy as np
import shapely as sh
from landscape import plan,split_cell,sides,ground_path,area_only,physical_green
from build import triangulate,z_at
from railway_surfaces import confirmed_owners

def path(id,coords,tier=0,layer='Pedestrian_road'):
    return dict(id=id,layer=layer,geometryType='polyline',coordinates=coords,
                properties={'db_tiers':[tier],'db_segment_level':tier})

extent=sh.box(0,0,20,20);green=extent;walk=sh.Polygon()
f=path('path',[[0,10,0],[10,10,0],[20,10,0]])
bad=path('buried',[[0,5,0],[20,5,0]],-1)
bridge=path('bridge',[[0,15,0],[20,15,0]],1)
layout,report=plan([f,bad,bridge],green,walk,extent,sh.Polygon())
assert not ground_path(bad) and not ground_path(bridge)
assert layout['paths'].intersection(sh.LineString([[0,10],[20,10]])).length==20
assert not layout['raised'].intersects(sh.LineString([[0,10],[20,10]]))
assert layout['raised'].covers(sh.Point(10,5)) and layout['raised'].covers(sh.Point(10,15))
assert layout['band'].intersection(sh.LineString([[10,1],[10,8]])).length==0, 'No curb on source-feature seams'
assert layout['band'].intersection(extent.boundary).length==0, 'No crop borders'
assert layout['band'].intersection(layout['paths']).area==0, 'Do not narrow pedestrian paths'
# Whole canonical partition and two independently split terrain cells have
# equal area/height; a storage cut never changes the generated green outline.
pieces=[];total=0
for cell in [sh.box(0,0,10,20),sh.box(10,0,20,20)]:
    for kind,g,c in split_cell(cell,np.array([.02,-.01,.1]),layout):
        total+=g.area
        assert abs(c[2]-(.1 if kind=='path' else .2))<1e-12
        if kind=='green':pieces.append(g)
assert abs(total-extent.area)<1e-9
assert sh.union_all(pieces).symmetric_difference(layout['raised'].difference(layout['band'])).area<1e-9
dem=[(extent,np.array([.02,-.01,0.]))];faces=sides(layout,dem,sh.STRtree([extent]),extent,triangulate,z_at)
assert faces
for t in faces:
    rel=t[:,2]-z_at(dem[0][1],t[:,:2])
    assert abs(rel.min()-.1)<1e-10 and abs(rel.max()-.2)<1e-10
    assert not np.allclose(t[:,0],10), 'No wall at an internal tile cut'
# A detailed 1 m polygon path keeps its width even if the centreline default is 2 m.
walk=sh.box(0,9.5,20,10.5)
exact,_=plan([f],extent.difference(walk),walk,extent,sh.Polygon())
assert exact['raised'].symmetric_difference(extent.difference(walk)).area<1e-9
# Same source curve split or reversed must not make a curb across its junction.
split=[path('a',[[0,10,0],[10,10,0]]),path('b',[[20,10,0],[10,10,0]])]
other,_=plan(split,extent,sh.Polygon(),extent,sh.Polygon())
assert other['raised'].symmetric_difference(layout['raised']).area<1e-8
# Unsnappped terrain-cell intersections must not create fine, bright paving
# streaks in a lawn merely because the whole-region union used a fixed grid.
g=sh.box(0,0,10,10);empty,_=plan([],g,sh.Polygon(),g,sh.Polygon())
triangles=[sh.Polygon([[0,0],[10,0],[10,10.000003]]),sh.Polygon([[0,0],[10,10.000003],[0,10]])]
for cell in triangles:
    paved=next(p for kind,p,c in split_cell(cell,np.array([0,0,.1]),empty) if kind=='path')
    assert paved.is_empty,'Terrain seam became a pedestrian path'
# Micrometre holes/notches from the old terrain partition must not acquire a
# 15 cm concrete outline. A real 20 cm opening and explicit paving stay open.
slit=sh.box(4,3,4.00001,7);real=sh.box(7,3,7.2,7)
fixed,fix=plan([],extent.difference(sh.union_all([slit,real])),sh.Polygon(),extent,sh.Polygon())
assert fixed['raised'].covers(slit) and not fixed['band'].intersects(slit)
assert fixed['raised'].intersection(real).area<1e-9
explicit,_=plan([],extent.difference(slit),slit,extent,sh.Polygon())
assert explicit['raised'].intersection(slit).area<1e-9
collapsed=sh.Polygon([[0,9],[3,12],[3.000001,12]])
assert list(split_cell(collapsed,np.array([0,0,.1]),layout))==[], 'Below-grid repairs must not become degenerate surfaces'
# A large source union can retain boundary-only contacts. They must neither
# crash fixed-precision overlays nor acquire an invented buffer/curb width.
mixed=sh.GeometryCollection([sh.box(0,0,6,20),sh.LineString([[8,0],[8,20]]),sh.Point(9,9)])
assert area_only(mixed).equals(sh.box(0,0,6,20))
assert area_only(sh.GeometryCollection([sh.LineString([[0,0],[1,1]]),sh.Point(2,2)])).is_empty
protected=sh.GeometryCollection([sh.box(2,3,4,7),sh.LineString([[5,0],[5,20]]),sh.Point(1,1)])
mixed_walk=sh.GeometryCollection([sh.box(0,9.5,6,10.5),sh.LineString([[3,0],[3,8]])])
clean,_=plan([f],sh.box(0,0,6,20),sh.box(0,9.5,6,10.5),extent,sh.box(2,3,4,7))
normalized,_=plan([f],mixed,mixed_walk,extent,protected)
for key in ('raised','band','cut','paths','filled'):
    assert normalized[key].geom_type in ('Polygon','MultiPolygon'),key
    assert normalized[key].symmetric_difference(clean[key]).area<1e-9,key
assert not normalized['raised'].intersects(sh.Point(8,10)), 'Zero-area contacts became planting'
# Thin boolean leftovers must not become ten-centimetre-high vertical fins.
# A real narrow island and an explicit narrow paved gap remain resolved.
needle=sh.box(12,2,12.00001,8);island=sh.box(14,2,14.002,8)
resolved,_=plan([],sh.union_all([sh.box(1,1,9,9),needle,island]),sh.Polygon(),extent,sh.Polygon())
assert resolved['raised'].intersection(needle).is_empty
assert resolved['discarded'].covers(needle)
assert resolved['raised'].covers(island), 'A resolved 2 mm island was removed'
edge_faces=sides(resolved,dem,sh.STRtree([extent]),extent,triangulate,z_at)
assert all(not needle.buffer(.0001).covers(sh.Point(t[:,:2].mean(0))) for t in edge_faces), 'Numerical remnant became an extruded wall'
narrow_gap=sh.box(4,0,4.002,10)
with_gap,_=plan([],sh.box(1,1,9,9).difference(narrow_gap),narrow_gap,extent,sh.Polygon())
assert with_gap['raised'].intersection(narrow_gap).area<1e-12
case=json.loads((Path(__file__).parent/'fixtures/landscape-numeric-remnants.json').read_text())
raw=sh.geometry.shape(case['rawRaised']);packed=sh.geometry.shape(case['serializedRaised'])
cleaned=physical_green(raw,case['gridM'])
assert raw.difference(packed.buffer(.001)).area>.001, 'The real regression no longer reproduces'
assert cleaned.difference(packed.buffer(.001)).area<.0001
assert raw.difference(cleaned).area>0
assert cleaned.difference(raw).area<1e-9, 'Cleanup expanded planting into another surface'
fixed_cleaned=physical_green(sh.set_precision(raw,case['gridM']),case['gridM'])
assert fixed_cleaned.difference(packed.buffer(.001)).area<.0001, 'Fixed-grid metadata prevented numeric cleanup'
assert fixed_cleaned.difference(raw).area<1e-9, 'Fixed-grid cleanup expanded the original footprint'
# A line on another tier cannot recolor a bridge; a short transverse crossing
# of a long transport slab cannot claim it either.
slab=dict(id='slab',layer='Transport_Roadbed',geometryType='polygon',
          properties={'db_tiers':[1],'db_road_part':'roadbed_overpass'},
          coordinates=[[0,0,5],[0,8,5],[100,0,5],[100,8,5]])
rail=path('rail',[[0,4,0],[100,4,0]],1,'Railroad_line')
assert [r['source'] for r in confirmed_owners([slab,rail])]==['slab']
assert not confirmed_owners([slab,path('wrong-tier',[[0,4,0],[100,4,0]],0,'Railroad_line')])
assert not confirmed_owners([slab,path('crossing',[[50,-10,0],[50,20,0]],1,'Railroad_line')])
print('Passed: ground-only paths, detailed paving priority, green height, inset curbs, no feature/crop/tile caps, reversed/split network continuity and tier-aware railway bases.')
