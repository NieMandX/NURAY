import unittest
import numpy as np
import shapely as sh
from paint_domain import accepts,Domain,GAP,paint_projection_mask


def cell(p,z=0):return dict(poly=p,plane=np.array([0,0,z],float))
def tri(xy,z=GAP):return np.column_stack([xy,np.full(3,z)])


class PaintTests(unittest.TestCase):
    def test_float32_projection_collapse_is_removed_even_with_3d_area(self):
        ordinary=[[2500,1,0],[2501,1,0],[2500,1,1]]
        collapsed=[[2500,1,0],[2501,1,0],[2501.00001,1.00001,0]]
        thin_but_real=[[2500,1,0],[2501,1,0],[2500,1,.00001]]
        packed=np.asarray([ordinary,collapsed,thin_but_real],dtype=np.float32)
        self.assertGreater(np.linalg.norm(np.cross(packed[1,1]-packed[1,0],packed[1,2]-packed[1,0])),0)
        np.testing.assert_array_equal(paint_projection_mask(packed),[True,False,True])

    def test_sloping_small_marking_at_large_coordinates(self):
        xy=np.array([[2400.,10000.],[2400.01,10000.],[2400.,10000.01]])
        slope=np.array([.03,-.02,200.])
        t=np.column_stack([xy,xy@slope[:2]+slope[2]+GAP])
        p=sh.Polygon(xy);domain=Domain([dict(poly=p,plane=slope)])
        self.assertAlmostEqual(domain.supported(t).area,p.area,places=12)

    def test_semantics(self):
        base=dict(kind='roadbed_flat',purpose='motor-traffic',material=0)
        self.assertTrue(accepts(base))
        for props in (dict(kind='land'),dict(purpose='pedestrian'),dict(purpose='railway'),dict(purpose='traffic-separator'),dict(material=9),dict(transport='pedestrian')):
            self.assertFalse(accepts(dict(base,**props)))
        self.assertTrue(accepts(dict(base,purpose=None)))

    def test_edge(self):
        d=Domain([cell(sh.box(0,0,1,1))]);t=tri([[.5,.25],[1.5,.25],[.5,.75]])
        got=d.supported(t)
        self.assertLess(got.area,sh.Polygon(t[:,:2]).area)
        self.assertLess(got.difference(sh.box(0,0,1,1)).area,1e-12)

    def test_island(self):
        road=sh.box(0,0,10,10).difference(sh.box(3,3,4,4))
        t=tri([[0,0],[10,0],[0,10]]);got=Domain([cell(road)]).supported(t)
        self.assertAlmostEqual(got.area,49)
        self.assertEqual(got.intersection(sh.box(3,3,4,4)).area,0)

    def test_levels(self):
        d=Domain([cell(sh.box(0,0,2,2)),cell(sh.box(1,0,3,2),5)])
        t=tri([[1.5,0],[2.5,0],[1.5,1]])
        self.assertAlmostEqual(d.supported(t).area,.375)
        self.assertAlmostEqual(d.supported(t+[0,0,5]).area,.5)
        self.assertEqual(d.supported(t+[0,0,.1]).area,0)

    def test_entire_triangle_height(self):
        d=Domain([cell(sh.box(0,0,10,10))]);t=tri([[0,0],[10,0],[0,10]])
        t[:,2]+=[-.1,.1,0]
        got=d.supported(t)
        self.assertGreater(got.area,0)
        self.assertLess(got.area,2)

    def test_disconnected_roads_do_not_bridge(self):
        d=Domain([cell(sh.box(0,0,1,1)),cell(sh.box(2,0,3,1))]);t=tri([[0,0],[3,0],[0,1]])
        got=d.supported(t)
        self.assertEqual(got.intersection(sh.box(1,0,2,1)).area,0)

    def test_cell_seam_has_no_cut(self):
        d=Domain([cell(sh.box(0,0,1,2)),cell(sh.box(1,0,2,2))]);t=tri([[0,0],[2,0],[0,2]])
        self.assertAlmostEqual(d.supported(t).area,2)

    def test_repeated_floor_queries_keep_height_clips_independent(self):
        cells=[cell(sh.box(0,0,1,2)),cell(sh.box(1,0,2,2))]
        d=Domain(cells);flat=tri([[0,0],[2,0],[0,2]])
        for t in (flat,flat,flat+np.array([[0,0,-.01],[0,0,.01],[0,0,0]]),
                  flat+np.array([[0,0,0],[0,0,-.01],[0,0,.01]]),flat):
            expected=Domain(cells).supported(t)
            self.assertEqual(d.supported(t).wkb,expected.wkb)
        self.assertAlmostEqual(d.supported(flat).area,2)

    def test_unsupported_has_no_visible_fallback(self):
        self.assertTrue(Domain([]).supported(tri([[0,0],[1,0],[0,1]])).is_empty)

    def test_nearly_coincident_exported_edges_do_not_invent_holes(self):
        import json
        from pathlib import Path
        for name in ('paint-near-coincident.json','paint-near-coincident-split.json'):
            f=json.loads((Path(__file__).parent/'test_fixtures'/name).read_text())
            t=np.array(f['triangle']);p=sh.Polygon(t[:,:2])
            for margin in (0,.0001):
                cells=[dict(poly=sh.geometry.shape(c['geometry']).buffer(margin),plane=np.array(c['plane'])) for c in f['cells']]
                self.assertLess(p.difference(Domain(cells).supported(t)).area,1e-10)

    def test_source_generator_never_binds_to_land_or_preserves_unbound_mesh(self):
        import build as b
        import tempfile
        from unittest.mock import patch
        from pathlib import Path
        from collections import defaultdict
        names=('DIAG','B','records','groups','old_groups','shading_flags','relationships','unresolved','surfaces')
        with tempfile.TemporaryDirectory() as tmp, patch.multiple(b,**{k:getattr(b,k) for k in names}):
            b.DIAG=Path(tmp);(b.DIAG/'corrected').mkdir()
            b.B=[0,0,3,3];b.records=[];b.groups=defaultdict(list);b.old_groups=defaultdict(list)
            b.shading_flags=defaultdict(list);b.relationships=[];b.unresolved=[]
            road=sh.box(0,0,1,3)
            b.surfaces=[dict(id='road',kind='roadbed_flat',material=0,purpose='motor-traffic',poly=road,plane=np.zeros(3),tiers=[0],owner='r'),
                        dict(id='land',kind='land',material=7,purpose='pedestrian',poly=sh.box(1,0,3,3),plane=np.array([0,0,.1]),tiers=[0],owner='l')]
            np.savez(b.DIAG/'corrected/a.npz',triangles=[tri([[0,0],[2,0],[0,2]])],material_indices=[0],polygon_indices=[0])
            b.legacy_and_paint({'objects':[dict(hidden=False,file='a.npz',name='line',materials=['white'],categories=['Road_markings'])]})
            self.assertTrue(b.groups[('paint',3)])
            self.assertFalse(any(k[0]=='unbound-paint' for k in b.groups))
            self.assertTrue(b.unresolved)
            self.assertTrue(all(r['parent']=='road' for r in b.relationships))
            for t in b.groups[('paint',3)]:self.assertLess(sh.Polygon(t[:,:2]).difference(road).area,1e-10)

if __name__=='__main__':unittest.main()
