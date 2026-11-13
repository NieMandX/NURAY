import unittest
import numpy as np
import shapely as sh
from ravine_plants import plan

class InfillTests(unittest.TestCase):
    def test_repeatable_scoped_collision_safe_infill(self):
        green=sh.box(0,0,70,70);masks={'road':sh.box(0,28,70,35),'water':sh.box(0,0,15,25),'building':sh.box(40,40,50,50)}
        zones=[dict(id='test',polygon=[[0,0],[60,0],[60,60],[0,60]])]
        crowns={'compact':[10,10],'growth':[4.8,5],'bush':[7.36,-.57]};existing=[[20,20],[25,25]]
        args=(zones,existing,green,masks,crowns,[(masks['building'],40)],lambda x,n:.1*x+.2*n,0)
        a=plan(*args);self.assertEqual(a,plan(*args));accepted=[r for r in a if r['status']=='accepted'];self.assertGreater(len(accepted),30)
        for r in accepted:
            x,n=r['eastNorth'];p=sh.Point(x,n);self.assertTrue(green.buffer(-2.5).covers(p));self.assertLessEqual(x,60);self.assertLessEqual(n,60)
            self.assertAlmostEqual(r['matrix'][7],.1*x+.2*n)
            self.assertGreaterEqual(min(np.linalg.norm(np.array(existing)-[x,n],axis=1)),r['separationM'])
            footprint=p.buffer(r['clearanceM'],quad_segs=4)
            self.assertFalse(any(g.intersects(footprint) for g in masks.values()))
        self.assertTrue(any(r.get('reason')=='surface-conflict' for r in a))
    def test_empty_green_has_no_invented_positions(self):
        self.assertEqual(plan([dict(id='a',polygon=[[0,0],[10,0],[10,10],[0,10]])],[],sh.Polygon(),{}, {},[],lambda x,n:0,0),[])

if __name__=='__main__':unittest.main()
