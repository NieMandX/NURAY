"""Batched fence prisms must preserve the former face-by-face surface."""
import unittest
import numpy as np
from street_library import Mesh
from fence_geometry import prism


class FaceByFaceMesh(Mesh):
    def face_batch(self,triangles,mat):
        for triangle in triangles:self.face(triangle,mat)


class FenceBatchTests(unittest.TestCase):
    def test_sloped_prisms_preserve_positions_winding_uv_and_material(self):
        rng=np.random.default_rng(749)
        for _ in range(120):
            a=rng.uniform(-2500,2500,2);b=a+rng.uniform(-30,30,2)
            h0,h1=rng.uniform(-25,25,2);material=int(rng.integers(0,16))
            old,new=FaceByFaceMesh(),Mesh()
            args=(a,b,h0,h1,-.02,float(rng.uniform(.1,3)),float(rng.uniform(.02,.4)),material)
            prism(old,*args);prism(new,*args)
            before,bm=old.arrays();after,am=new.arrays()
            np.testing.assert_array_equal(before[:,:,:3],after[:,:,:3])
            np.testing.assert_allclose(before,after,atol=2e-13,rtol=2e-15)
            np.testing.assert_array_equal(bm,am)
            self.assertEqual(len(after),12)

    def test_degenerate_faces_and_small_valid_faces_match(self):
        triangles=np.array([[[0,0,0],[1,0,0],[0,0,1]],
                            [[0,0,0],[0,0,0],[0,0,0]],
                            [[0,0,0],[1e-5,0,0],[0,0,1e-5]],
                            [[0,0,0],[1e-6,0,0],[0,0,1e-6]],
                            [[0,0,0],[0,0,1],[-1,0,0]]])
        old,new=FaceByFaceMesh(),Mesh()
        old.face_batch(triangles,7);new.face_batch(triangles,7)
        np.testing.assert_allclose(old.arrays()[0],new.arrays()[0],atol=1e-15)
        np.testing.assert_array_equal(old.arrays()[1],new.arrays()[1])


if __name__=='__main__':unittest.main()
