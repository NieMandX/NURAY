"""Batch acceptance must be the original exact single-floor shortcut."""
import json
import unittest
from pathlib import Path
import numpy as np
import shapely as sh
from paint_domain import Domain,GAP,HEIGHT_TOLERANCE


class BatchPaintTests(unittest.TestCase):
    def prove(self,domain,triangles,tolerance=HEIGHT_TOLERANCE):
        triangles=np.asarray(triangles,float)
        mask=domain.fully_supported(triangles,tolerance)
        for t,accepted in zip(triangles,mask):
            if accepted:
                self.assertEqual(domain.supported(t,tolerance).wkb,sh.Polygon(t[:,:2]).wkb)
        return mask

    def test_holes_edges_disconnected_floors_and_levels(self):
        floor=sh.box(0,0,10,10).difference(sh.box(3,3,4,4))
        d=Domain([dict(poly=floor,plane=np.zeros(3)),
                  dict(poly=sh.box(10,0,20,10),plane=np.zeros(3)),
                  dict(poly=sh.box(0,0,10,10),plane=np.array([0,0,5]))])
        def tri(xy,z=GAP):return np.column_stack([xy,np.full(3,z)])
        tris=[tri([[0,0],[2,0],[0,2]]),tri([[2,2],[5,2],[2,5]]),
              tri([[9,0],[11,0],[9,1]]),tri([[0,0],[2,0],[0,2]],5+GAP),
              tri([[0,0],[2,0],[0,2]],.1),tri([[0,0],[1,0],[2,0]]),
              tri([[20,0],[21,0],[20,1]])]
        np.testing.assert_array_equal(self.prove(d,tris),[True,False,False,True,False,False,False])
        self.assertAlmostEqual(d.supported(tris[2]).area,1.)

    def test_height_threshold_is_not_relaxed(self):
        xy=np.array([[2400.,10000.],[2400.01,10000.],[2400.,10000.01]])
        plane=np.array([.03,-.02,200.])
        d=Domain([dict(poly=sh.Polygon(xy),plane=plane)])
        tris=[np.column_stack([xy,xy@plane[:2]+plane[2]+GAP+offset])
              for offset in [0,.0019,.0021,-.0021]]
        t=tris[0].copy();t[:,2]+=[-.01,.01,0];tris.append(t)
        np.testing.assert_array_equal(self.prove(d,tris),[True,True,False,False,False])

    def test_source_witnesses_and_serialized_boundary_buffer(self):
        root=Path(__file__).parent/'test_fixtures'
        rows=[]
        for name in ('paint-near-coincident.json','paint-near-coincident-split.json'):
            rows.append(json.loads((root/name).read_text()))
        rows+=json.loads((root/'paint-float32-large-region.json').read_text())['examples']
        for row in rows:
            for margin in (0,.0001,.0004):
                d=Domain([dict(poly=sh.geometry.shape(c['geometry']).buffer(margin),
                               plane=np.array(c['plane'])) for c in row['cells']])
                self.prove(d,[row['triangle']],HEIGHT_TOLERANCE+.00001)

    def test_batch_boundary_and_random_slopes(self):
        rng=np.random.default_rng(2711)
        xy=rng.uniform(-4900,4900,(8200,1,2))+np.array([[[0,0],[.03,0],[0,.07]]])
        plane=np.array([.014,-.027,15.])
        xyz=np.concatenate([xy,(xy@plane[:2]+plane[2]+GAP)[...,None]],axis=2)
        xyz[::7,:,2]+=.1
        d=Domain([dict(poly=sh.box(-5000,-5000,5000,5000),plane=plane)])
        expected=np.ones(len(xyz),bool);expected[::7]=False
        np.testing.assert_array_equal(self.prove(d,xyz),expected)
        np.testing.assert_array_equal(Domain([]).fully_supported(xyz[:3]),[False]*3)


if __name__=='__main__':unittest.main()
