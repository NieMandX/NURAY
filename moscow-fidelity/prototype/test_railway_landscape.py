import json,unittest
from pathlib import Path
import numpy as np
import shapely as sh
from railway_landscape import reserve_interfaces,green_intrusion,low_slab
from landscape import plan,split_cell


def example(at_ground=True):
    feature=dict(id='slab',coordinates=[[-15,0,0],[15,0,0],[-15,20,4],[15,20,4]])
    interface=dict(id='test',atGround=at_ground,mouthGeometry=sh.geometry.mapping(sh.LineString([[-15,0],[15,0]])),
                   ends=[dict(kind='roadbed_overpass',parents=['slab']),dict(kind='railway_ground',parents=['axis'])])
    return [feature],[interface],sh.box(-30,-20,30,30)


class RailwayLandscape(unittest.TestCase):
    def test_entire_multitrack_mouth_and_both_sides_are_reserved(self):
        features,interfaces,extent=example();reserve=reserve_interfaces(features,interfaces,extent)
        for x in (-14.9,0,14.9):
            self.assertTrue(reserve.covers(sh.Point(x,-1.05)))
            self.assertTrue(reserve.covers(sh.Point(x,1.05)))
        self.assertFalse(reserve.covers(sh.Point(0,-1.2)))
        self.assertFalse(reserve.covers(sh.Point(15.1,0)))

    def test_non_ground_structure_does_not_cut_surface_planting(self):
        self.assertTrue(reserve_interfaces(*example(False)).is_empty)

    def test_lowered_approach_is_paved_without_raised_curb_across_mouth(self):
        features,interfaces,extent=example();reserve=reserve_interfaces(features,interfaces,extent)
        green=sh.box(-20,-5,20,0)
        layout,_=plan([],green,sh.Polygon(),extent,reserve)
        mouth=sh.LineString([[-14.95,0],[14.95,0]]).buffer(.001)
        self.assertLess(layout['raised'].intersection(mouth).area,1e-10)
        self.assertLess(layout['band'].intersection(mouth).area,1e-10)
        pieces=list(split_cell(green,np.array([0.,0.,.1]),layout))
        paths=[(g,c) for role,g,c in pieces if role=='path']
        self.assertTrue(paths)
        self.assertTrue(all(c[2]==.1 for g,c in paths))
        self.assertTrue(layout['raised'].covers(sh.Point(0,-2)))

    def test_live_snapshot_wide_mouths(self):
        data=json.loads((Path(__file__).parent/'fixtures/railway-landscape-mouths.json').read_text())
        extent=sh.box(*data['boundsMSK'])
        reserved=reserve_interfaces(data['features'],data['interfaces'],extent)
        self.assertEqual(len(data['interfaces']),2)
        for interface in data['interfaces']:
            mouth=sh.geometry.shape(interface['mouthGeometry'])
            self.assertGreater(mouth.length,30.)
            self.assertLess(mouth.buffer(.001,cap_style='flat').difference(reserved).area,1e-7)
        self.assertLess(reserved.area,400.)

    def test_gentle_ramp_is_reserved_until_clear_of_raised_planting(self):
        features,interfaces,extent=example()
        features[0]['coordinates']=[[-15,0,0],[15,0,0],[-15,20,1],[15,20,1]]
        reserve=reserve_interfaces(features,interfaces,extent)
        self.assertTrue(reserve.covers(sh.Point(14,3.9)))
        self.assertFalse(reserve.covers(sh.Point(14,5)))
        layout,_=plan([],extent,sh.Polygon(),extent,reserve,rail_apron=reserve)
        pieces=list(split_cell(sh.box(13,3,14,4),np.array([0.,0.,.1]),layout))
        apron=[(p,c) for role,p,c in pieces if role=='railway_apron' and not p.is_empty]
        self.assertAlmostEqual(sum(p.area for p,c in apron),1)
        self.assertTrue(all(c[2]==.1 for p,c in apron))
        self.assertTrue(layout['raised'].covers(sh.Point(14,5)))

    def test_live_low_slabs_are_entirely_reserved(self):
        data=json.loads((Path(__file__).parent/'fixtures/railway-landscape-mouths.json').read_text())
        reserve=reserve_interfaces(data['features'],data['interfaces'],sh.box(*data['boundsMSK']))
        for f in data['features']:
            low=low_slab(f['coordinates'])
            self.assertLess(low.difference(reserve).area,1e-8)

    def test_live_grid_rounding_at_reserve_boundary(self):
        data=json.loads((Path(__file__).parent/'fixtures/railway-reserve-grid-boundary.json').read_text())
        result=green_intrusion(sh.geometry.shape(data['overlap']),sh.geometry.shape(data['reserve']))
        self.assertGreater(result['rawOverlapM2'],.00001)
        self.assertEqual(result['resolvedOverlapM2'],0)
        self.assertTrue(result['passed'])

    def test_real_small_interior_obstruction_is_rejected(self):
        reserve=sh.box(0,0,10,10)
        self.assertFalse(green_intrusion(sh.box(5,5,5.0001,5.01),reserve)['passed'])
        self.assertFalse(green_intrusion(sh.box(-1,2,.002,8),reserve)['passed'])
        self.assertTrue(green_intrusion(sh.box(-1,2,.00001,8),reserve)['passed'])


if __name__=='__main__':unittest.main()
