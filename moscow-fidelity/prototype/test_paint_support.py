import numpy as np
import shapely as sh
from paint_support import audit
road=dict(id='r',kind='roadbed_flat',material=0,poly=sh.box(0,0,10,10),purpose='motor-traffic')
triangle=np.array([[1.,1.,.003],[2,1,.003],[1,2,.003]])
assert audit([(triangle,np.zeros(3),'r')],[road],.00005)['passed']
bad=triangle.copy();bad[:,0]+=9
assert not audit([(bad,np.zeros(3),'r')],[road],.00005)['passed']
assert not audit([(triangle,np.zeros(3),'r')],[dict(road,kind='land',material=7)],.00005)['passed']
assert not audit([(triangle,np.zeros(3),'absent')],[road],.00005)['passed']
print('Passed: paint must be inside an existing asphalt support; off-road, sidewalk and missing support fail.')
