import unittest
import numpy as np
import shapely as sh
from transport_planting import layout,partition
from landscape import GREEN_CURB_WIDTH,GREEN_RAISE
from landscape import sides
from build import triangulate,z_at

class TransportPlantingTests(unittest.TestCase):
    def test_new_mouth_lowers_lawn_and_rebuilds_its_inset_border(self):
        green=sh.box(0,0,10,10)
        band=green.difference(green.buffer(-GREEN_CURB_WIDTH,join_style='mitre',mitre_limit=2))
        before=dict(raisedGeometry=sh.geometry.mapping(green),
                    curbGeometry=sh.geometry.mapping(band),
                    railApronGeometry=sh.geometry.mapping(sh.Polygon()))
        reserve=sh.box(4,-2,6,4)
        plan,patch,lowered=layout(before,reserve,sh.box(-20,-20,20,20))
        plan['railMaterial']=210
        self.assertAlmostEqual(lowered.area,8)
        self.assertLess(plan['raised'].intersection(reserve).area,1e-9)
        self.assertTrue(plan['band'].covers(sh.Point(3.95,2)))
        self.assertFalse(plan['band'].covers(sh.Point(5,2)))
        self.assertLess(plan['band'].symmetric_difference(band).difference(patch).area,1e-9)
        original=[]
        for role,p in [('green',green.difference(band)),('curb',band)]:
            original.append(dict(id=role,owner='source-lawn',kind='land',
                landscapeRole=role,geometry=sh.geometry.mapping(p),
                heightPlane=[.01,.02,.2],material=2 if role=='green' else 9))
        removed,rows,mask=partition(original,plan,patch,{'Internal_lawn':2},
                                    {'source-lawn':{'layer':'Internal_lawn'}})
        self.assertEqual(removed,{'green','curb'})
        self.assertAlmostEqual(mask.area,100)
        apron=[r for r in rows if r['landscapeRole']=='railway_apron']
        self.assertTrue(apron)
        self.assertAlmostEqual(sum(sh.geometry.shape(r['geometry']).area for r in apron),8)
        for r in rows:
            self.assertTrue(np.allclose(r['heightPlane'],[.01,.02,.1 if r in apron else .2]))
        self.assertAlmostEqual(sum(sh.geometry.shape(r['geometry']).area for r in rows),100)
        terrain=[(sh.box(-20,-20,20,20),np.zeros(3))]
        walls=sides(plan,terrain,sh.STRtree([terrain[0][0]]),sh.box(-20,-20,20,20),
                    triangulate,z_at,region=patch)
        self.assertTrue(walls)
        for t in walls:
            for point in t:
                self.assertLess(plan['raised'].boundary.distance(sh.Point(point[:2])),1e-8)
                self.assertTrue(any(abs(point[2]-z)<1e-9 for z in (.1,.2)))

    def test_unchanged_reservation_preserves_all_cells(self):
        green=sh.box(0,0,10,10);reserve=sh.box(-5,-5,-1,10)
        band=green.difference(green.buffer(-GREEN_CURB_WIDTH,join_style='mitre',mitre_limit=2))
        before=dict(raisedGeometry=sh.geometry.mapping(green),curbGeometry=sh.geometry.mapping(band),
                    railApronGeometry=sh.geometry.mapping(reserve))
        plan,patch,lowered=layout(before,reserve,sh.box(-20,-20,20,20))
        self.assertTrue(patch.is_empty)
        self.assertTrue(lowered.is_empty)
        self.assertTrue(plan['raised'].equals(green))
        self.assertTrue(plan['band'].equals(band))

    def test_resolved_border_difference_outside_patch_is_rejected(self):
        green=sh.box(0,0,10,10)
        band=green.difference(green.buffer(-GREEN_CURB_WIDTH,join_style='mitre',mitre_limit=2))
        band=band.union(sh.box(8,5,8.02,7))
        before=dict(raisedGeometry=sh.geometry.mapping(green),curbGeometry=sh.geometry.mapping(band),
                    railApronGeometry=sh.geometry.mapping(sh.Polygon()))
        with self.assertRaises(AssertionError):
            layout(before,sh.box(4,-2,6,4),sh.box(-20,-20,20,20))

if __name__=='__main__':unittest.main()
