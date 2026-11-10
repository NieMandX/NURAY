"""Analytic regression for a joined road, raised island, and a cropped boundary."""
from collections import defaultdict
import numpy as np
import shapely as sh
from curbs import band,solid_sides

extent=sh.box(0,0,20,10)
road=sh.union_all([sh.box(2,2,10,8),sh.box(10,2,20,8)]).difference(sh.box(7,4,9,6))
curb=band(road,sh.Polygon(),extent,.00001)
groups=defaultdict(list);dem=[(extent,np.zeros(3))]
front,count=solid_sides(curb,road,dem,sh.STRtree([extent]),groups,lambda c,xy:np.zeros(len(xy)),extent)
expected=road.boundary.difference(extent.boundary.buffer(.00005))
assert expected.difference(front.buffer(.00005)).length<.001
assert curb.intersection(road).area<1e-9
assert not front.covers(sh.Point(10,5)), 'Internal source seam became a curb'
assert front.intersection(sh.box(6.9,3.9,9.1,6.1)).length>=7.999
for tri in groups[('curb_front',9)]:
    n=np.cross(tri[1]-tri[0],tri[2]-tri[0]);n=n[:2]/np.linalg.norm(n[:2])
    assert road.covers(sh.Point(tri[:,:2].mean(0)+n*.001))
print('Curb regression passed: shared source seam, island border, cropped road, front winding')

# A transition cut may leave a very narrow end beside the road. Proximity
# alone labels its outward/back face as road-facing, despite opposite winding.
cut_road=sh.box(2,2,10,8)
cut_band=band(cut_road,sh.box(10.0003,2,20,8),extent,.00001)
cut_groups=defaultdict(list)
cut_front,_=solid_sides(cut_band,cut_road,dem,sh.STRtree([extent]),cut_groups,lambda c,xy:np.zeros(len(xy)),extent)
for tri in cut_groups[('curb_front',9)]:
    n=np.cross(tri[1]-tri[0],tri[2]-tri[0]);n=n[:2]/np.linalg.norm(n[:2])
    assert cut_road.covers(sh.Point(tri[:,:2].mean(0)+n*.001)), 'Cut end misclassified as road-facing curb'
assert cut_groups[('curb_back',9)]
assert cut_front.distance(sh.Point(10,5))<.00001
print('Transition curb regression passed: a resolved narrow cut end is classified by its outward direction, not proximity.')

# A fixed 1 mm probe jumps across both banks of this resolved narrow section.
# Its actual faces must remain classified by the immediately adjacent solids.
narrow=sh.box(3,3,3.0008,5)
narrow_band=band(narrow,sh.Polygon(),extent,.00001)
narrow_groups=defaultdict(list)
narrow_front,_=solid_sides(narrow_band,narrow,dem,sh.STRtree([extent]),narrow_groups,lambda c,xy:np.zeros(len(xy)),extent)
assert narrow.boundary.difference(narrow_front.buffer(.00005)).length<.001
print('Narrow curb regression passed: local side probes cannot jump across the road.')

# Expanded Moscow exposed two intact faces labelled as the back of a curb:
# a DEM edge split the sub-millimetre tip of an acute island. Reproduce that
# shape without location-specific rules or changed validation tolerances.
from shapely.affinity import rotate,translate
from coverage import uncovered_length
for angle in (0,37,90):
    for offset in ((0,0),(6937,8201)):
        transform=lambda g:translate(rotate(g,angle,origin=(0,0)),*offset)
        ext=transform(sh.box(-1,-1,1,1))
        island=transform(sh.Polygon([(-.1,-.0008),(0,0),(-.1,.0008)]))
        rd=ext.difference(island)
        cb=band(rd,sh.Polygon(),ext,.00001)
        terrain=[(transform(sh.box(-1,-1,-.001,1)),np.zeros(3)),
                 (transform(sh.box(-.001,-1,1,1)),np.zeros(3))]
        emitted=defaultdict(list)
        fr,_=solid_sides(cb,rd,terrain,sh.STRtree([p for p,c in terrain]),emitted,
                         lambda c,xy:np.zeros(len(xy)),ext)
        expected=rd.boundary.difference(ext.boundary.buffer(.00005))
        assert uncovered_length(expected,fr,.00005)<.001,(angle,offset)
print('Acute island regression passed: DEM cuts do not relabel the intact tip; original, rotated and translated cases retain the 1 mm audit threshold.')
