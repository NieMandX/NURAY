import unittest
import numpy as np
import shapely as sh
from prepare_railway_entries import near_passages


class PassageBroadphaseTests(unittest.TestCase):
    def test_index_matches_original_inclusive_bounds(self):
        rng=np.random.default_rng(18)
        triangles=rng.uniform(-5,5,(2000,3,3))
        # Include boundary contacts and degenerate projections explicitly.
        triangles[:3]=[[[0,0,0],[0,1,0],[0,2,0]],[[1,0,0],[1,1,1],[1,2,0]],[[2,0,2],[2,1,2],[2,2,2]]]
        boxes=[sh.box(0,0,1,1),sh.box(-4,-4,-3,-3)]
        volumes=[({'id':str(i)},[(b,[])]) for i,b in enumerate(boxes)]
        lo=triangles[:,:,[0,2]].min(1);hi=triangles[:,:,[0,2]].max(1);keep=np.zeros(len(triangles),bool)
        for b in boxes:
            x0,y0,x1,y1=b.bounds
            keep|=(lo[:,0]<=x1)&(hi[:,0]>=x0)&(lo[:,1]<=y1)&(hi[:,1]>=y0)
        actual=list(near_passages([('wall',triangles)],volumes))
        np.testing.assert_array_equal(actual[0][1],triangles[keep])
        self.assertEqual(list(near_passages([('wall',triangles)],[])),[])


if __name__=='__main__':unittest.main()
