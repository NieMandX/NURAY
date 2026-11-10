import json,unittest
from pathlib import Path
import shapely as sh
from shapely.affinity import rotate,translate
from passage_space import connected_approach,ground_approach,walking_reserve,ground_landings


class ConnectedApproachTests(unittest.TestCase):
    def test_saved_bent_entry_and_rotated_copy(self):
        fixture=json.loads((Path(__file__).with_name('fixtures')/'disconnected-ground-approach.json').read_text())
        c=fixture['connection'];mouth=sh.geometry.shape(c['mouthGeometry'])
        landing=sh.geometry.shape(c['landingGeometry']);orphan=sh.geometry.shape(fixture['orphan']['geometry'])
        for angle in (0,37,146):
            m=rotate(mouth,angle,origin=(0,0));g=rotate(landing,angle,origin=(0,0));o=rotate(orphan,angle,origin=(0,0))
            result=connected_approach(m,g)
            self.assertLess(result.intersection(o).area,1e-8)
            self.assertLess(result.symmetric_difference(g.difference(o)).area,1e-7)
        expected=connected_approach(mouth,landing)
        # The combined reserve has always used the canonical 10-micron grid.
        self.assertLess(sh.symmetric_difference(walking_reserve([c]),expected,grid_size=1e-5).area,1e-9)
        floors=ground_landings([c],[],1e-5)
        self.assertEqual(len(floors),1)
        self.assertLess(floors[0]['poly'].intersection(orphan).area,1e-8)

    def test_builder_discards_area_behind_a_separating_floor(self):
        mouth=sh.LineString([(0,0),(10,0)])
        floor=sh.union_all([sh.box(0,-10,10,0),sh.box(0,.4,10,.6)])
        result=ground_approach(mouth,floor)
        self.assertLess(result.symmetric_difference(sh.box(0,0,10,.4)).area,1e-9)

    def test_connected_thin_and_point_connected_parts_survive(self):
        mouth=sh.LineString([(0,0),(1,0)])
        landing=sh.union_all([sh.box(0,0,1,.0001),sh.box(1,.0001,2,1)])
        result=connected_approach(mouth,landing)
        self.assertEqual(sh.to_wkb(result),sh.to_wkb(landing))

    def test_size_does_not_make_an_unconnected_island_a_landing(self):
        mouth=sh.LineString([(0,0),(1,0)])
        near=sh.box(0,0,1,1);far=sh.box(2,0,20,20)
        result=connected_approach(mouth,sh.union_all([near,far]))
        self.assertTrue(result.equals(near))
        self.assertTrue(connected_approach(mouth,far).is_empty)

    def test_empty_and_translated_touching_area(self):
        mouth=sh.LineString([(0,0),(1,0)]);empty=sh.Polygon()
        self.assertTrue(connected_approach(mouth,empty).is_empty)
        area=sh.box(0,0,1,1)
        self.assertTrue(connected_approach(translate(mouth,10000,-4000),translate(area,10000,-4000)).equals(translate(area,10000,-4000)))


if __name__=='__main__':unittest.main()
