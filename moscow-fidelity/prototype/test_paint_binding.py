import unittest
import numpy as np
import shapely as sh
from paint_binding import bind,floor_overlaps

def road(z,tier=1,x0=0,x1=10,material=0):
    return dict(poly=sh.box(x0,0,x1,10),plane=np.array([0.,0.,z]),
                tiers=[tier],kind='roadbed_overpass',material=material)

class SourcePaintBindingTests(unittest.TestCase):
    def run_bind(self,cells,source_floor=True,tiers=(1,)):
        return bind(sh.box(1,1,9,2),np.array([0.,0.,.05]),tiers,cells,
                    sh.STRtree([s['poly'] for s in cells]),source_floor=source_floor)
    def test_zero_height_bridge_marking_uses_tier(self):
        pairs,left=self.run_bind([road(0,0),road(8)])
        self.assertEqual([i for i,p in pairs],[1]);self.assertAlmostEqual(left.area,0)
    def test_tunnel_marking_uses_negative_tier(self):
        pairs,left=self.run_bind([road(0,0),road(-6,-1)],tiers=(-1,))
        self.assertEqual([i for i,p in pairs],[1]);self.assertAlmostEqual(left.area,0)
    def test_legacy_absolute_height_is_still_checked(self):
        self.assertFalse(self.run_bind([road(8)],source_floor=False)[0])
    def test_same_tier_stacked_roads_are_not_guessed(self):
        pairs,left=self.run_bind([road(5),road(9)])
        self.assertFalse(pairs);self.assertAlmostEqual(left.area,8)
    def test_adjacent_and_duplicate_same_height_cells(self):
        pairs,left=self.run_bind([road(5,x1=5),road(5,x0=5),road(5,x0=5)])
        self.assertAlmostEqual(sum(p.area for i,p in pairs),8);self.assertAlmostEqual(left.area,0)
    def test_rail_and_sidewalk_do_not_receive_paint(self):
        self.assertFalse(self.run_bind([road(5,material=12),road(5,material=7)])[0])
    def test_long_line_does_not_compare_distant_floor_cells(self):
        polygons=[sh.box(i,0,i+1,1) for i in range(1000)]
        pairs=list(floor_overlaps(sh.box(0,.4,1000,.6),polygons))
        self.assertLess(len(pairs),2000)
        self.assertFalse(any(piece.area>=1e-10 for _,_,piece in pairs))
    def test_index_preserves_exact_conflicts_and_order(self):
        rng=np.random.default_rng(71)
        for precision in (0,1e-5):
            polygons=[sh.set_precision(sh.box(x,y,x+w,y+h),precision)
                for x,y,w,h in rng.uniform([0,0,.001,.001],[50,5,6,2],(80,4))]
            polygons.extend([polygons[3],polygons[12]])
            geometry=sh.set_precision(sh.Polygon([(0,.5),(50,1.3),(50,3),(0,4)]),precision)
            expected=[(k,j,geometry.intersection(a).intersection(b).wkb)
                for k,a in enumerate(polygons) for j,b in enumerate(polygons) if j>k
                and geometry.intersection(a).intersection(b).area>=1e-10]
            actual=[(k,j,p.wkb) for k,j,p in floor_overlaps(geometry,polygons) if p.area>=1e-10]
            self.assertEqual(actual,expected)
    def test_stacked_conflict_on_long_marking_is_retained(self):
        cells=[road(5,x0=i,x1=i+1) for i in range(100)]
        cells.append(road(9,x0=40.25,x1=42.75))
        pairs,left=bind(sh.box(0,1,100,2),np.zeros(3),[1],cells,
            sh.STRtree([s['poly'] for s in cells]),source_floor=True)
        self.assertAlmostEqual(left.area,2.5)
        self.assertAlmostEqual(sum(p.area for _,p in pairs),97.5)

if __name__=='__main__':unittest.main()
