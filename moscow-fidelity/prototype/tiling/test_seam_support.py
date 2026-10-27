import numpy as np
import shapely as sh
from seam_support import compare

# A vertical border touches x=0 and returns east. Its vertical corner appears
# in the east tile only; no physical surface continues into the west tile.
t=np.array([[[0,0,2],[0,.1,2],[1,0,3]],[[0,0,2],[1,0,1],[0,.1,2]]],float)
corner=sh.LineString([[2,0],[2,.1]])
gap,missing,touched=compare(sh.LineString(),corner,t,0,0)
assert gap==0 and missing==0 and abs(touched-.1)<1e-8
# A genuine cut through a vertical panel requires the same edge on both sides.
cross=np.array([[[-1,0,2],[1,0,2],[1,.1,2]],[[-1,0,2],[1,.1,2],[-1,.1,2]]],float)
assert compare(corner,corner,cross,0,0)==(0.,0.,0.)
try:compare(sh.LineString(),corner,cross,0,0)
except AssertionError:pass
else:raise AssertionError('Lost cross-tile geometry went undetected')
print('Passed: one-sided canonical tangency is legal; a missing genuine cut remains a failure.')
