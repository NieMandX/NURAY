import unittest
import numpy as np
import shapely as sh
from profiles import RoadHeightModel

class SparseProfiles(unittest.TestCase):
    def test_equivalent_height_and_constraints(self):
        bounds=[0,0,100,100];dem=[]
        for y in range(0,100,20):
            for x in range(0,100,20):
                xy=np.array([[x,y],[x+20,y],[x+20,y+20],[x,y+20]],dtype=float)
                z=5+np.sin(xy[:,0]/70)+np.cos(xy[:,1]/60)
                for ids in [[0,1,2],[0,2,3]]:
                    t=xy[ids];dem.append((sh.Polygon(t),np.linalg.solve(np.c_[t,np.ones(3)],z[ids])))
        road=sh.box(35,0,65,100)
        records=[dict(id='axis',layer='Main_road',geometryType='polyline',properties={},coordinates=[[50,0,0],[50,100,0]])]
        a=RoadHeightModel(dem,records,road,bounds,sparse_fit=False)
        b=RoadHeightModel(dem,records,road,bounds,sparse_fit=True)
        xy=np.random.default_rng(42).uniform(0,100,(200,2))
        self.assertLess(float(np.max(np.abs(a.height(xy)-b.height(xy)))),1e-8)
        expected=sh.distance(sh.points(xy),road)
        raw,smooth=b.raw(xy),b.smooth(xy);t=np.clip(expected/20,0,1);w=1-(3*t*t-2*t*t*t)
        self.assertTrue(np.allclose(b.height(xy),raw*(1-w)+smooth*w,rtol=0,atol=1e-10))
        self.assertEqual(a.report['longitudinalBendingConstraints'],b.report['longitudinalBendingConstraints'])
        grid=b.grid();self.assertAlmostEqual(sum(g.area for g,c in grid),10000)
        for g,c in grid[::71]:
            points=np.asarray(g.exterior.coords)[:3,:2]
            self.assertTrue(np.allclose(points@c[:2]+c[2],b.height(points),atol=1e-9))
        adaptive=b.adaptive_grid()
        self.assertAlmostEqual(sum(g.area for g,c in adaptive),10000,places=6)
        self.assertAlmostEqual(sh.union_all([g for g,c in adaptive]).area,10000,places=6)
        # Every interior edge must have an exact opposite partner; T-junctions
        # would leave two short edges against one unsplit long edge.
        from collections import Counter
        edges=Counter()
        for g,c in adaptive:
            coords=list(g.exterior.coords)
            for x,y in zip(coords,coords[1:]):edges[tuple(sorted((tuple(x),tuple(y))))]+=1
        for edge,count in edges.items():
            on_boundary=any(abs(edge[0][axis]-value)<1e-9 and abs(edge[1][axis]-value)<1e-9 for axis in (0,1) for value in (0,100))
            self.assertEqual(count,1 if on_boundary else 2)

if __name__=='__main__':unittest.main()
