"""Regression cases for source contour cracks, rather than transport tile cuts."""
import json
import unittest
from pathlib import Path
import shapely as sh
from shapely.affinity import rotate, translate
from shapely.geometry import shape
from road_seams import reconcile
from curbs import band
from tiling.seam_validation import check_passages
from road_quality import quality
import numpy as np

GRID = .00001


def road(poly, owner, tier=0):
    return dict(poly=poly, id=owner, layer='Main_Roadbed', kind='road',
                part='roadbed_flat', tiers=[tier], material=0, rank=100)


def land(poly, owner='lawn', layer=68):
    return dict(poly=poly, id=owner, layer='Internal_lawn', kind='land',
                material=2, rank=30), dict(id=owner, layer='Internal_lawn',
                properties={'db_layer': layer}, coordinates=[])


class RoadSeamTests(unittest.TestCase):
    def setUp(self):
        self.extent = sh.box(-5, -5, 30, 85)
        self.rows = [road(sh.box(0, 0, 10, 80), 'a'),
                     road(sh.box(10.04, 0, 20, 80), 'b')]
        self.raw = sh.union_all([r['poly'] for r in self.rows])
        self.gap = sh.box(10, 0, 10.04, 80)

    def run_rule(self, rows=None, records=None, extent=None):
        rows = self.rows if rows is None else rows
        raw = sh.union_all([r['poly'] for r in rows if r['kind'] == 'road' and r['part'] == 'roadbed_flat'])
        return reconcile(raw, rows, records or [], extent or self.extent, GRID)

    def test_long_open_crack_and_idempotence(self):
        fixed, repairs, report = self.run_rule()
        self.assertGreater(sum(r['areaM2'] for r in repairs), 3)
        self.assertLess(self.gap.difference(fixed).area, 1e-8)
        curb = band(fixed, sh.Polygon(), self.extent, GRID)
        self.assertLess(curb.intersection(self.gap.buffer(-.001)).area, 1e-8)
        again, extra, _ = reconcile(fixed, self.rows, [], self.extent, GRID)
        self.assertFalse(extra)
        self.assertLess(again.symmetric_difference(fixed).area, 1e-8)
        self.assertEqual(report['repairs'], len(repairs))

    def test_rotated_translated_open_crack_without_public_road_id(self):
        transform = lambda g: translate(rotate(g, 27.3, origin=(0, 0)), 2000.123, 8000.456)
        rows = [{**r, 'poly': transform(r['poly'])} for r in self.rows]
        fixed, repairs, _ = self.run_rule(rows, extent=transform(self.extent))
        self.assertTrue(repairs)
        self.assertLess(transform(self.gap).difference(fixed).area, .001)
        self.assertEqual(repairs[0]['sourceRoadObjectIds'], [])
        self.assertEqual(repairs[0]['sourceParents'], ['a', 'b'])

    def test_different_physical_tiers_stay_separate(self):
        rows = [self.rows[0], {**self.rows[1], 'tiers': [1]}]
        fixed, repairs, report = self.run_rule(rows)
        self.assertFalse(repairs)
        self.assertFalse(fixed.covers(sh.Point(10.02, 40)))
        self.assertTrue(report['rejected'])

    def test_gap_above_width_tolerance_stays_open(self):
        rows = [self.rows[0], road(sh.box(10.06, 0, 20, 80), 'b')]
        fixed, repairs, _ = self.run_rule(rows)
        self.assertFalse(repairs)
        self.assertFalse(fixed.covers(sh.Point(10.03, 40)))

    def test_buried_tunnel_does_not_cut_surface_asphalt_but_open_descent_does(self):
        for part, expected in [('roadbed_tunnel', True), ('roadbed_tunnel_descent', False)]:
            with self.subTest(part=part):
                underground = {**road(self.gap, 'below', -1), 'part':part}
                fixed, repairs, _ = self.run_rule([*self.rows, underground])
                self.assertEqual(bool(repairs), expected)
                self.assertEqual(fixed.covers(sh.Point(10.02, 40)), expected)

    def test_repair_preserves_unambiguous_source_tier(self):
        rows = [{**r, 'tiers':[1]} for r in self.rows]
        _, repairs, _ = self.run_rule(rows)
        self.assertEqual(repairs[0]['tiers'], [1])
        ambiguous = [*self.rows, *[{**r, 'id':r['id']+'-upper'} for r in rows]]
        _, repairs, report = self.run_rule(ambiguous)
        self.assertFalse(repairs)
        self.assertTrue(report['rejected'])

    def test_independent_narrow_lawn_is_protected_even_if_coarse(self):
        for layer in [49, 68]:
            with self.subTest(layer=layer):
                lawn, record = land(self.gap, layer=layer)
                fixed, repairs, report = self.run_rule([*self.rows, lawn], [record])
                self.assertFalse(repairs)
                self.assertFalse(fixed.covers(sh.Point(10.02, 40)))
                self.assertGreater(report['protectedAreaM2'], 3)

    def test_painted_safety_island_does_not_create_physical_land(self):
        island = dict(id='island', layer='LinearMarking_save_island_contour',
                      properties={}, coordinates=list(self.gap.exterior.coords))
        fixed, repairs, _ = self.run_rule(records=[island])
        self.assertTrue(repairs)
        self.assertTrue(fixed.covers(sh.Point(10.02, 40)))

    def test_physical_ground_curb_outline_is_protected(self):
        curb = dict(id='physical-curb', layer='Roadbed_outline',
                    properties={'db_road_part':'border_flat'},coordinates=[(10.02,0),(10.02,80)])
        fixed, repairs, _ = self.run_rule(records=[curb])
        self.assertFalse(repairs)
        self.assertFalse(fixed.covers(sh.Point(10.02, 40)))

    def test_quality_distinguishes_explicit_thin_island_from_missing_asphalt(self):
        island = sh.box(10, 10, 10.04, 20)
        poly = sh.box(0, 0, 20, 80).difference(island)
        surface = dict(kind='roadbed_flat', poly=poly, plane=np.zeros(3))
        unknown = quality([surface])
        known = quality([surface], island)
        self.assertEqual(len(unknown['thinEnclosedSlits']), 1)
        self.assertFalse(known['thinEnclosedSlits'])
        self.assertEqual(len(known['protectedThinIslands']), 1)

    def test_coarse_cover_remnant_does_not_turn_into_a_curb(self):
        # One coarse source polygon spans under asphalt. Clipping splits a tiny
        # seam remnant from its large real lawn. A detailed physical polygon
        # with the same geometry must instead retain the explicit narrow strip.
        cover = sh.union_all([sh.box(-4, -4, 0, 84), sh.box(0, 20, 10.04, 60)])
        for layer, should_repair in [(49, True), (68, False)]:
            with self.subTest(layer=layer):
                lawn, record = land(cover, layer=layer)
                fixed, repairs, report = self.run_rule([*self.rows, lawn], [record])
                self.assertEqual(fixed.covers(sh.Point(10.02, 40)), should_repair)
                self.assertEqual(bool(report['coverRemnants']), should_repair)
                self.assertFalse(fixed.covers(sh.Point(-2, 40)))

    def test_one_sided_exterior_corner_is_not_rounded_off(self):
        # Closing would fill this tiny concave notch; there is no opposite bank.
        notch = sh.box(0, 0, 20, 20).difference(sh.box(9.99, 19.98, 10.01, 21))
        fixed, repairs, report = self.run_rule([road(notch, 'one')])
        self.assertFalse(repairs)
        self.assertFalse(fixed.covers(sh.Point(10, 19.99)))
        self.assertTrue(report['rejected'])

    def test_observed_moscow_access_road(self):
        data = json.loads((Path(__file__).parent / 'fixtures/road-seam-access.json').read_text())
        rows = [{**r, 'poly': shape(r['geometry'])} for r in data['candidates']]
        extent = sh.box(*data['boundsMSK'])
        raw = sh.union_all([r['poly'] for r in rows if r['kind'] == 'road' and r['part'] == 'roadbed_flat']).intersection(extent)
        fixed, repairs, report = reconcile(raw, rows, data['records'], extent, GRID)
        witness = sh.Point(data['witnessMSK'])
        self.assertFalse(raw.covers(witness))
        self.assertTrue(fixed.covers(witness))
        matching = [r for r in repairs if shape(r['geometry']).covers(witness)]
        self.assertTrue(matching)
        self.assertIn('4504338361749809', matching[0]['sourceRoadObjectIds'])
        gate = shape(matching[0]['geometry']).buffer(GRID*5).intersection(fixed.buffer(-.001))
        self.assertLess(band(fixed, sh.Polygon(), extent, GRID).intersection(gate).area, 1e-7)
        self.assertTrue(report['coverRemnants'])

    def test_serialized_passage_check_detects_real_vertical_barrier(self):
        gate = sh.box(10.01, 10, 10.03, 70)
        metadata = dict(sourceParents=['a', 'b'])
        asphalt = np.array([[[0, 0, 0], [20, 0, 0], [20, 0, 80]],
                            [[0, 0, 0], [20, 0, 80], [0, 0, 80]]], dtype=float)
        meshes = [('roadbed_flat', asphalt)]
        self.assertTrue(check_passages([(metadata, gate)], meshes)['passed'])
        barrier = np.array([[[10.02, 0, 20], [10.02, 0, 60], [10.02, .1, 60]],
                            [[10.02, 0, 20], [10.02, .1, 60], [10.02, .1, 20]]])
        result = check_passages([(metadata, gate)], [*meshes, ('curb_front', barrier)])
        self.assertFalse(result['passed'])
        self.assertAlmostEqual(result['checks'][0]['curbSideM'], 40)
        for name in ['land', 'curb_top', 'curb_bottom']:
            raised = asphalt.copy()
            raised[:, :, 1] = .1
            self.assertFalse(check_passages([(metadata, gate)], [*meshes, (name, raised)])['passed'])

    def test_enclosed_acute_corner_uses_both_banks_not_one_corner_normal(self):
        data=json.loads((Path(__file__).parent/'fixtures/road-seam-acute-enclosed.json').read_text())
        rows=[{**r,'poly':shape(r['geometry'])} for r in data['candidates']]
        raw=shape(data['road']);point=sh.Point(data['witness']);extent=sh.box(*data['bounds'])
        self.assertFalse(raw.covers(point))
        fixed,repairs,_=reconcile(raw,rows,[],extent,GRID)
        self.assertTrue(fixed.covers(point))
        self.assertTrue(any(shape(r['geometry']).covers(point) for r in repairs))
        _,again,_=reconcile(fixed,rows,[],extent,GRID)
        self.assertFalse(again)

    def test_precision_grid_does_not_hide_real_enclosed_cracks(self):
        data=json.loads((Path(__file__).parent/'fixtures/road-seam-precision-probes.json').read_text())
        rows=[{**r,'poly':sh.set_precision(shape(r['geometry']),GRID)} for r in data['candidates']]
        raw=sh.union_all([r['poly'] for r in rows if r['kind']=='road' and r['part']=='roadbed_flat'],grid_size=GRID)
        holes=[shape(h) for h in data['holes']]
        self.assertTrue(all(h.difference(raw).area>h.area*.98 for h in holes))
        fixed,repairs,_=reconcile(raw,rows,data['records'],sh.box(*data['bounds']),GRID)
        self.assertTrue(repairs)
        for h in holes:self.assertLess(h.difference(fixed).area,1e-8)
        _,extra,_=reconcile(fixed,rows,data['records'],sh.box(*data['bounds']),GRID)
        self.assertFalse(extra)


if __name__ == '__main__':
    unittest.main(verbosity=2)
