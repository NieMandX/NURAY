import unittest
import numpy as np
import shapely as sh
from relocate_green_plants import nearest_green

class GreenRelocationTests(unittest.TestCase):
    def test_full_crown_fits_beyond_pavement(self):
        lawn=sh.box(3,-8,15,8);crown=sh.box(-2,-2,2,2)
        xy=nearest_green([0,0],crown,lawn,np.empty((0,2)),max_move=10)
        np.testing.assert_equal(xy,[5,0])
    def test_keeps_hole_and_existing_roots_clear(self):
        lawn=sh.box(2,-8,15,8).difference(sh.box(3,-1,7,1))
        crown=sh.Point(0,0).buffer(1)
        args=([0,0],crown,lawn,np.array([[3,-2],[3,2]]))
        a=nearest_green(*args,max_move=10,spacing=3)
        b=nearest_green(*args,max_move=10,spacing=3)
        np.testing.assert_equal(a,b)
        self.assertGreaterEqual(np.linalg.norm(np.array([[3,-2],[3,2]])-a,axis=1).min(),3)
        self.assertTrue(lawn.covers(sh.Point(a).buffer(1)))
    def test_no_silent_removal_or_distant_relocation(self):
        with self.assertRaises(ValueError):nearest_green([0,0],sh.Point(0,0).buffer(2),sh.box(50,50,100,100),np.empty((0,2)),max_move=10)

if __name__=='__main__':unittest.main()
