import unittest
import numpy as np
import shapely as sh
from survey_fences import classify_line, evidence, overlay_pieces
from shapely.ops import substring


def match(points, records):
    rows = [dict(handle=i, family=f, line=sh.LineString(p)) for i, (f, p) in enumerate(records)]
    return classify_line(sh.LineString(points), rows, sh.STRtree([r['line'] for r in rows]))


class SurveyFenceTests(unittest.TestCase):
    def test_gate_and_perpendicular_neighbour_remain_unmatched(self):
        result = match([(0, 0), (20, 0)], [
            ('fence-stone-high', [(0, .3), (8, .3)]),
            ('fence-stone-high', [(12, .3), (20, .3)]),
            ('fence-metal-high', [(10, -4), (10, 4)])])
        self.assertEqual([(r['startM'], r['endM'], r['family']) for r in result],
                         [(0, 8, 'fence-stone-high'), (8, 12, None), (12, 20, 'fence-stone-high')])

    def test_conflicting_types_are_order_independent(self):
        records = [('fence-wood', [(0, 1), (20, 1)]),
                   ('fence-metal-high', [(8, -.5), (12, -.5)])]
        a = match([(0, 0), (20, 0)], records)
        b = match([(0, 0), (20, 0)], records[::-1])
        self.assertEqual([(r['startM'], r['endM'], r['family'], r['status']) for r in a],
                         [(r['startM'], r['endM'], r['family'], r['status']) for r in b])
        self.assertEqual(a[1]['status'], 'conflict')

    def test_bends_use_local_tangent_and_preserve_full_length(self):
        a = match([(0, 0), (10, 0), (10, 10)], [
            ('fence-stone-high', [(0, .3), (9, .3)]),
            ('fence-metal-high', [(9.7, 1), (9.7, 10)])])
        self.assertAlmostEqual(sum(r['lengthM'] for r in a), 20)
        self.assertEqual([r['family'] for r in a], ['fence-stone-high', None, 'fence-metal-high'])

    def test_symbols_closed_pickets_and_raw_z_do_not_become_paths(self):
        class Identity:
            def transform(self, x, y): return x, y
        base = dict(family='fence-stone-high', handle=1, layer='stone', closed=False,
                    lengthXY=10, points=[[0, 0, 99], [10, 0, 999]])
        rows, rejected = evidence(dict(paths=[base, dict(base, closed=True), dict(base, lengthXY=.2)]), Identity())
        self.assertEqual(len(rows), 1)
        np.testing.assert_array_equal(rows[0]['line'].coords, [[0, 0], [10, 0]])
        self.assertEqual(rejected['closed-or-symbol-size'], 2)

    def test_overlay_retains_complete_path_and_original_gate(self):
        line = sh.LineString([(311.0283, 129.2787), (297.1728, 187.5294), (275.8822, 223.0184)])
        old = dict(sourceCode=None, family='neutral')
        # A source gap stays open even when the survey class continues past it.
        baseline = [(substring(line, 0, 30), old), (substring(line, 35, line.length), old)]
        record = dict(runs=[dict(startM=11.134, endM=76.721, family='fence-stone-high', handles=[7])])
        result = overlay_pieces(line, baseline, record)
        self.assertAlmostEqual(sum(p.length for p, _ in result), line.length-5, places=7)
        assigned = sum(p.length for p,s in result if s['sourceCode'] is not None)
        self.assertAlmostEqual(assigned, 76.721-11.134-5, places=7)


if __name__ == '__main__': unittest.main()
