import unittest
import numpy as np
import shapely as sh
from waterfront import wall_geometry
from waterfront_parapet import parapet_geometry,HEIGHT,WIDTH

class ParapetTests(unittest.TestCase):
 def fixture(self,water,bounds,origin=[0,0,0]):
  _,_,banks=wall_geometry(water,np.array([water],object),np.array([[0,0,3.]]),[],bounds,origin)
  return banks,parapet_geometry(banks,origin,water,bounds)
 def test_landward_height_and_metric_joints(self):
  water=sh.box(0,0,10,4);banks,(tri,joints,stats)=self.fixture(water,[-1,-1,11,5])
  self.assertTrue(np.isfinite(tri).all());self.assertEqual(len(tri),len(joints));self.assertTrue(joints.any())
  self.assertAlmostEqual(tri[:,:,1].max(),3+HEIGHT);self.assertAlmostEqual(tri[:,:,1].min(),2.975)
  self.assertFalse(sh.contains(water.buffer(-.0001),sh.points(np.column_stack([tri[:,:,0].ravel(),-tri[:,:,2].ravel()]))).any())
  self.assertLessEqual(stats['maxJoinOffsetM'],WIDTH*2+1e-8)
  # Interior of a long slab is full height; its centre joint is recessed.
  upper=tri[tri[:,:,1].max(1)>3.9,:,:3].reshape(-1,3)
  self.assertTrue(np.any((abs(upper[:,0]-2)<.02)&(abs(upper[:,1]-3.988)<1e-6)))
 def test_no_wall_on_acquisition_cut(self):
  water=sh.box(0,0,10,4);banks,(tri,_,stats)=self.fixture(water,[0,-1,10,5])
  self.assertEqual(stats['closedEnds'],4)
  # Only tiny end caps, not a parapet across either open water boundary.
  at_cut=(abs(tri[:,:,0])<1e-8).all(1)
  self.assertTrue((np.ptp(tri[at_cut,:,2],axis=1)<=WIDTH+1e-8).all())
 def test_concave_bank_and_island_remain_finite(self):
  water=sh.box(0,0,20,12).difference(sh.box(3,3,6,5)).difference(sh.box(10,7,21,13))
  banks,(tri,flags,stats)=self.fixture(water,[-1,-1,21,13],[10,10,1])
  self.assertTrue(np.isfinite(tri).all());self.assertTrue(np.allclose(np.linalg.norm(tri[:,:,3:6],axis=2),1))
  self.assertAlmostEqual(tri[:,:,1].max(),3.)
  self.assertEqual(stats['sourceBankSegments'],len(banks['a']))
if __name__=='__main__':unittest.main()
