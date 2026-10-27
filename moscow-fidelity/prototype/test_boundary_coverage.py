import shapely as sh
from shapely.geometry import LineString,MultiLineString
from shapely.affinity import rotate
from coverage import uncovered_length
boundary=LineString([(0,0),(5,0),(5,4)])
for emitted in [boundary,MultiLineString([[(0,0),(2,0)],[(2,0),(5,0)],[(5,0),(5,4)]]),MultiLineString([[(0,0),(2,0)],[(2.002,0),(5,0)],[(5,0),(5,3)]])]:
    for angle in [0,37]:
        a=rotate(boundary,angle);b=rotate(emitted,angle)
        expected=a.difference(b.buffer(.00005)).length
        assert abs(uncovered_length(a,b,.00005)-expected)<1e-9
long=LineString([(0,0),(1000,0)])
fragments=MultiLineString([[(i/10,0),((i+1)/10-.000001,0)] for i in range(10000)])
assert uncovered_length(long,fragments,.00005)<1e-9
assert uncovered_length(boundary,LineString(),.00005)==9
print('Passed: indexed coverage equals union-buffer coverage, rotated boundaries, real gaps, empty emission and 10,000 adjacent fragments.')
from coverage import gap_core_area
assert gap_core_area(sh.box(0,0,10000,.00001),.00005)==0
assert gap_core_area(sh.box(0,0,.02,.02),.00005)>.00039
assert gap_core_area(sh.GeometryCollection(),.00005)==0
print('Passed: long micron-scale overlay drift does not fail by accumulated area; a real 2 cm hole is still rejected.')

from coverage import physical_land_boundary
extent=sh.box(-5,-5,25,25)
numeric=sh.box(9,1,9.00002,19)
real=sh.box(12,1,12.02,19)
road=sh.box(0,0,20,20).difference(sh.union_all([numeric,real]))
boundary=physical_land_boundary(road,sh.Polygon(),extent,.00005)
assert boundary.intersection(numeric.buffer(.00001)).length<.001
assert boundary.intersection(real.buffer(.00001)).length>35
assert uncovered_length(boundary,boundary.difference(sh.box(-1,4,1,5)),.00005)>.99
print('Passed: curb expectation excludes only unresolved isolated slivers; a 2 cm island and a 1 m missing curb remain required.')

from tiling.seam_validation import passage_gates,check_passages
import numpy as np
road=sh.box(0,0,10,4)
city={'originMSK':[0,0,0],'groundRoadGeometry':sh.geometry.mapping(road),
      'surfaces':[{'kind':'roadbed_flat','geometry':sh.geometry.mapping(sh.box(0,-.01,10,4))}],
      'roadSeamRepairs':[{'type':'two-sided-road-seam','sourceParents':['a','b'],'geometry':sh.geometry.mapping(sh.box(4,-.003,6,.003))}]}
gates=passage_gates(city)
assert gates[0][1].intersection(sh.LineString([(4,0),(6,0)])).is_empty
asphalt=np.array([[[0,0,0],[10,0,0],[10,0,-4]],[[0,0,0],[10,0,-4],[0,0,-4]]],dtype=float)
barrier=np.array([[[4,0,-.002],[6,0,-.002],[6,.1,-.002]]],dtype=float)
assert check_passages(gates,[('roadbed_flat',asphalt)])['passed']
assert not check_passages(gates,[('roadbed_flat',asphalt),('curb_front',barrier)])['passed']
print('Passed: the agreed contour, not a re-union of mesh cells, defines seam gates; a real transverse face remains detectable.')
