import unittest
import numpy as np
from survey_fairing import fair_heights,TerrainNormals,suspect_spots
from build_scene import Terrain


class SurveyFairingTests(unittest.TestCase):
    def grid(self):
        return np.stack(np.meshgrid(np.arange(9.),np.arange(9.)),axis=-1).reshape(-1,2)

    def test_isolated_interior_spike_is_flagged_without_mutating_input(self):
        xy=self.grid()*3;h=170+xy[:,0]*.2;h[40]+=25
        marks=np.column_stack([xy,h]);prior=marks.copy()
        self.assertEqual([r['index'] for r in suspect_spots(marks)],[40])
        np.testing.assert_array_equal(marks,prior)

    def test_slope_and_supported_upper_terrace_are_not_outliers(self):
        xy=self.grid()*3;h=170+xy[:,0]*.8+np.where(xy[:,1]>12,12,0)
        self.assertEqual(suspect_spots(np.column_stack([xy,h])),[])

    def test_planar_survey_and_boundary_remain_planar(self):
        xy=self.grid();h=180+xy[:,0]*.1-xy[:,1]*.04
        fixed=np.flatnonzero((xy.min(1)==0)|(xy.max(1)==8))
        faces,z,report=fair_heights(xy,h,fixed,h[fixed],np.column_stack([xy[::10],h[::10]]))
        np.testing.assert_allclose(z,h,atol=1e-9)
        terrain=Terrain(np.concatenate([xy[faces],z[faces][:,:,None]],axis=2))
        n=TerrainNormals(terrain).sample([[2.3,4.1],[6.2,7.6]])
        expected=np.array([-.1,1,-.04]);expected/=np.linalg.norm(expected)
        np.testing.assert_allclose(n,np.tile(expected,(2,1)),atol=1e-9)

    def test_unmeasured_spike_removed_but_spot_and_collar_exact(self):
        xy=self.grid();plane=170+xy[:,0]*.15;initial=plane.copy()
        initial[(xy==[4,4]).all(1)]+=8
        fixed=np.flatnonzero((xy.min(1)==0)|(xy.max(1)==8)|((xy==[3,4]).all(1)))
        faces,z,report=fair_heights(xy,initial,fixed,plane[fixed],np.empty((0,3)))
        np.testing.assert_array_equal(z[fixed],plane[fixed])
        self.assertLess(abs(z-plane).max(),.03)
        self.assertLess(report['gradientJumpEnergyAfter'],report['gradientJumpEnergyBefore']*.01)

    def test_measured_height_cannot_be_erased_by_contour(self):
        xy=self.grid();h=np.full(len(xy),180.);i=np.flatnonzero((xy==[4,4]).all(1))[0]
        fixed=np.r_[np.flatnonzero((xy.min(1)==0)|(xy.max(1)==8)),i];h[i]=181.
        faces,z,report=fair_heights(xy,np.full(len(xy),180.),fixed,h[fixed],[[4,4,179.]])
        self.assertEqual(z[i],181.)
        self.assertEqual(report['fixedHeightMaxErrorM'],0.)

    def test_sharp_terrace_crease_does_not_invert_smoothed_normals(self):
        # Two steep opposing sides must keep separate corner normals even
        # at their shared ridge instead of smoothing through the other side.
        triangles=np.array([[[0,0,0],[1,0,5],[0,1,0]],[[1,0,5],[1,1,0],[0,1,0]]],float)
        terrain=Terrain(triangles);n=TerrainNormals(terrain).for_triangles(triangles[:,:,:2])
        face=np.column_stack([-terrain.planes[:,0],np.ones(2),terrain.planes[:,1]])
        face/=np.linalg.norm(face,axis=1,keepdims=True)
        self.assertTrue(np.all((n*face[:,None]).sum(2)>.25))

if __name__=='__main__':unittest.main()
