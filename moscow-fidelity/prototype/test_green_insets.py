import unittest
import numpy as np
import shapely as sh
from green_insets import recover,strip_polygon,areal
from landscape import plan,split_cell
from semantics import classify

def feature(i,layer,xy):
    return dict(id=i,layer=layer,geometryType='polygon',coordinates=[[*p,0] for p in xy],properties={})
def row(i,owner,g,**kw):
    return dict(id=i,owner=owner,poly=g,plane=np.array([.02,0,1.1]),kind='land',material=7,**kw)

class GreenInsetsTests(unittest.TestCase):
    def test_district_is_background_but_detailed_paving_has_priority(self):
        rank=lambda s:classify(s,{},'polygon')['rank']
        self.assertLess(rank('Pedestrian_quarter'),rank('Flowerbed_quarter'))
        self.assertGreater(rank('Immersive_park_polygon_pedestrian_stone'),rank('Flowerbed_quarter'))
        self.assertGreater(rank('Main_Roadbed'),rank('Flowerbed_quarter'))
    def test_source_coordinates_are_a_triangle_strip_not_a_ring(self):
        p=strip_polygon([[0,0,0],[10,0,0],[0,10,0],[10,10,0]])
        self.assertEqual(p.area,100)
    def test_green_is_restored_only_inside_generic_walk(self):
        fs=[feature('q','Pedestrian_quarter',[]),feature('g','Flowerbed_quarter',[[1,1],[9,1],[1,9],[9,9]])]
        # The central strip is detailed paving; the right edge is a road.
        rows=[row('a','q',sh.box(0,0,4,10)),row('b','q',sh.box(6,0,8,10)),row('c','detail',sh.box(4,0,6,10))]
        _,greens,report=recover(rows,fs)
        g=sh.union_all([r['poly'] for r in greens])
        self.assertAlmostEqual(g.area,40)
        self.assertEqual(g.intersection(sh.box(4,0,6,10)).area,0)
        self.assertEqual(g.intersection(sh.box(8,0,10,10)).area,0)
        self.assertAlmostEqual(report['recoveredAreaM2'],40)
    def test_repeated_source_polygons_do_not_duplicate_green(self):
        fs=[feature('q','Pedestrian_quarter',[])]+[feature(i,'Internal_lawn',[[1,1],[9,1],[1,9],[9,9]]) for i in ['g1','g2']]
        _,greens,_=recover([row('a','q',sh.box(0,0,10,10))],fs)
        self.assertEqual(sum(r['poly'].area for r in greens),64)
    def test_paths_and_border_follow_restored_green(self):
        source=dict(id='path',layer='Pedestrian_road',geometryType='polyline',properties={},coordinates=[[0,5,0],[10,5,0]])
        g=sh.box(1,1,9,9);layout,_=plan([source],g,sh.Polygon(),sh.box(0,0,10,10),sh.Polygon())
        self.assertEqual(layout['raised'].intersection(sh.box(0,4,10,6)).area,0)
        pieces=list(split_cell(g,np.array([.02,0,1.1]),layout))
        self.assertTrue(any(role=='curb' and p.area>0 for role,p,c in pieces))
        for role,p,c in pieces:
            self.assertAlmostEqual(c[2],1.2 if role in {'green','curb'} else 1.1)
    def test_mixed_dimension_contact_does_not_enter_boolean_overlay(self):
        g=sh.GeometryCollection([sh.box(0,0,2,2),sh.LineString([[2,2],[3,3]])])
        self.assertEqual(areal(g).area,4)
        self.assertEqual(areal(g).geom_type,'Polygon')

if __name__=='__main__':unittest.main()
