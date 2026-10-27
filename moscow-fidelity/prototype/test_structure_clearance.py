import unittest
from collections import defaultdict
import numpy as np
import shapely as sh
from overpasses import build
from build import triangulate,z_at,plane
from structure_clearance import reserved_extension,attached_extension


class StructureClearanceTests(unittest.TestCase):
    def test_disconnected_concrete_remnant_is_not_extruded(self):
        source=sh.box(0,0,5,4)
        attached=sh.box(0,4,5,5);orphan=sh.box(6,4,6.002,4.002)
        result,removed=attached_extension(source,sh.union_all([attached,orphan]),1e-5)
        self.assertAlmostEqual(removed,orphan.area)
        self.assertTrue(result.equals(attached))
    def scene(self,peer_height):
        extent=sh.box(-10,-10,20,20);dem=[(extent,np.zeros(3))]
        rows=[dict(owner='bridge',kind='roadbed_overpass',tiers=[1],poly=sh.box(0,0,10,4),plane=np.array([0.,0.,2.]))]
        peer=dict(owner='other-road',kind='roadbed_flat',tiers=[0],poly=sh.box(-2,4.3,12,8),plane=np.array([0.,0.,peer_height]))
        groups=defaultdict(list)
        profiles,_=build(rows+[peer],dem,sh.STRtree([extent]),groups,extent,1e-5,triangulate,z_at,plane,[])
        self.assertTrue(all(p['passed'] for p in profiles))
        return sh.geometry.shape(profiles[0]['deckGeometry']),peer['poly'],groups

    def test_nearby_lower_road_not_obstructed_by_synthetic_overhang(self):
        deck,road,_=self.scene(1.1)
        self.assertLess(deck.intersection(road).area,1e-9)
        self.assertAlmostEqual(deck.intersection(sh.box(0,0,10,4)).area,40)

    def test_high_crossing_retains_its_overhang(self):
        deck,road,_=self.scene(-4.)
        self.assertGreater(deck.intersection(road).area,7)

    def test_other_road_above_parapet_does_not_cut_lower_structure(self):
        deck,road,_=self.scene(8.)
        self.assertGreater(deck.intersection(road).area,7)

    def test_unequal_tiers_do_not_protect_intruding_concrete(self):
        deck,road,_=self.scene(2.)
        self.assertLess(deck.intersection(road).area,1e-9)

    def test_sloped_height_boundary_is_clipped_continuously(self):
        extension=sh.box(0,0,10,1)
        floors=[dict(owner='peer',kind='roadbed_flat',poly=extension,plane=np.zeros(3))]
        cut=reserved_extension(extension,floors,sh.STRtree([extension]),set(),lambda xy:xy[0],1,.7,triangulate,z_at,1e-5)
        self.assertAlmostEqual(cut.area,2.,places=4)
        self.assertTrue(cut.covers(sh.Point(1,0.5)))
        self.assertFalse(cut.covers(sh.Point(3,.5)))
        floors[0]['kind']='roadbed_tunnel'
        self.assertTrue(reserved_extension(extension,floors,sh.STRtree([extension]),set(),lambda xy:xy[0],1,.7,triangulate,z_at,1e-5).is_empty)


if __name__=='__main__':unittest.main()
