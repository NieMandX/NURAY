import unittest
from types import SimpleNamespace
import numpy as np
import shapely as sh
from build_scene import Builder, union
from moscow_style import connected_water,ribbon_centerlines,grounds,GREEN_HEIGHT,PEDESTRIAN_HEIGHT
from fence_geometry import resolve,TYPES,DEFAULT

class MoscowStyleContracts(unittest.TestCase):
    def test_channel_connects_river_arms_before_bridge_and_tile_cuts(self):
        extent=sh.box(-100,-100,100,100)
        river=sh.box(-110,-10,-5,10).union(sh.box(5,-10,40,10)).union(sh.LineString([(-7,0),(7,0)]).buffer(2))
        pond=sh.Point(55,10).buffer(8)
        selected,stats=connected_water(river.union(pond).intersection(extent),extent)
        self.assertLess(selected.symmetric_difference(river.intersection(extent)).area,1e-5)
        self.assertEqual(stats['isolatedComponents'],1)
        self.assertEqual(selected.intersection(pond).area,0)
    def test_narrow_ribbon_produces_one_centerline_not_two_outlines(self):
        ribbon=sh.box(0,-.1,20,.1)
        result=list(ribbon_centerlines(ribbon))
        self.assertEqual(len(result),1)
        self.assertAlmostEqual(result[0].length,20)
        self.assertTrue(all(abs(y)<1e-7 for x,y in result[0].coords))
    def test_closed_fence_stays_closed_with_no_diagonals_across_courtyard(self):
        ribbon=sh.box(0,0,20,20).difference(sh.box(.2,.2,19.8,19.8))
        result=union(list(ribbon_centerlines(ribbon)))
        self.assertGreater(result.length,75)
        self.assertLess(result.length,82)
        self.assertLess(result.difference(ribbon).length,1e-7)
    def test_green_step_is_from_pavement_and_border_is_inside_union(self):
        b=Builder.__new__(Builder);b.circle=sh.box(-20,-20,20,20);b.road_curb=sh.Polygon();b.holes=sh.Polygon();b.building_footprint=sh.Polygon()
        b.materials=[dict(name=str(i),color=[.1,.1,.1],roughness=.9) for i in range(40)];b.material=lambda i:i
        b.finished={k:sh.Polygon() for k in ('road','ped','rail','island','parking','water','cemetery','grass','sand','default')}
        b.finished['grass']=sh.box(-10,-10,10,10).difference(sh.box(-1,-20,1,20));b.finished['ped']=sh.box(-1,-20,1,20)
        b.finished['default']=b.circle.difference(union(list(b.finished.values())))
        b.land={};b.terrain=SimpleNamespace(sample=lambda xy:np.zeros(len(xy)));b.add=lambda *args:None;b.boundary_walls=lambda *a,**kw:None
        calls=[];b.surface=lambda g,m,n,offset=0,**kw:calls.append((g,m,offset))
        grounds(b,{'areas':{'Internal_lawn':sh.box(-20,-20,0,20),'Internal_forest_quarter':sh.box(0,-20,20,20)}})
        self.assertAlmostEqual(GREEN_HEIGHT-PEDESTRIAN_HEIGHT,.1)
        self.assertEqual(b.green_band.intersection(b.finished['ped']).area,0)
        self.assertLess(b.green_band.difference(b.finished['grass']).area,1e-6)
        self.assertTrue(all(h==GREEN_HEIGHT for g,m,h in calls if m>=40 and g.area))
    def test_fence_codes_and_missing_material_are_not_guessed(self):
        for code in list(TYPES)+[None,100]:
            resource=TYPES.get(code,DEFAULT)[0]
            rule={'id':'source','type':'model','filter':True,'style':{'modelSrc':resource}}
            r=resolve({'properties':{} if code is None else {'db_fence_type':code},'sourceRecordId':'fixture'},[rule])
            self.assertEqual(r['typeStatus'],'source' if code in TYPES else 'missing' if code is None else 'unknown-code')
            if code not in TYPES:self.assertEqual(r['family'],'neutral')
if __name__=='__main__':unittest.main()
