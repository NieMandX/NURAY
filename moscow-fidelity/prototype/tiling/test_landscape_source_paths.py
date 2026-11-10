import json
from pathlib import Path
import unittest
import numpy as np
import shapely as sh
from landscape_source_paths import SourceGreenPrecision


class SourcePathPrecisionTests(unittest.TestCase):
    def setUp(self):
        d=json.loads((Path(__file__).parent/'fixtures/landscape-collapsed-source-lawn.json').read_text())
        self.origin=d['origin'];self.line=sh.geometry.shape(d['line'])
        self.source=sh.union_all([sh.geometry.shape(g) for g in d['sourceGreen']])
        self.actual=sh.union_all([sh.geometry.shape(g) for g in d['actualGreen']])
        paths=sh.union_all([sh.geometry.shape(g) for g in d['actualPaths']])
        self.missing=self.line.intersection(self.source).difference(paths.buffer(.003))

    def test_real_source_island_is_unrepresentable_in_packed_mesh(self):
        self.assertAlmostEqual(self.missing.length,.012758351940737198,places=10)
        precision=SourceGreenPrecision(self.source,self.actual,self.origin)
        result=precision.filter(self.missing)
        self.assertLess(result.length,1e-8)
        report=precision.report()
        self.assertEqual(report['components'],1)
        self.assertAlmostEqual(report['sourceAreaM2'],3.8199999904424477e-7,places=15)
        self.assertAlmostEqual(report['excludedSourcePathLengthM'],self.missing.length,places=8)

    def test_real_missing_paving_is_still_a_failure(self):
        source=sh.box(5600,4390,5615,4410)
        gap=sh.LineString([(5601,4391),(5601.02,4391)])
        precision=SourceGreenPrecision(source,sh.Polygon(),self.origin)
        self.assertTrue(precision.filter(gap).equals_exact(gap,0))
        self.assertGreater(precision.filter(gap).length,.01)
        self.assertEqual(precision.report()['components'],0)

    def test_actual_green_cannot_be_excused_by_a_collapsed_source(self):
        actual=self.missing.buffer(.01)
        precision=SourceGreenPrecision(self.source,actual,self.origin)
        self.assertTrue(precision.filter(self.missing).equals_exact(self.missing,0))
        self.assertEqual(precision.report()['components'],0)

    def test_tiny_but_representable_lawn_is_not_filtered(self):
        source=sh.Polygon([(1.,1.),(1.,1.00004),(1.02,1.)])
        gap=sh.LineString([(1.0001,1.000001),(1.018,1.000001)])
        precision=SourceGreenPrecision(source,sh.Polygon(),[0,0,0])
        self.assertTrue(precision.filter(gap).equals_exact(gap,0))
        self.assertEqual(precision.report()['components'],0)

    def test_green_at_packed_location_also_prevents_exclusion(self):
        pieces=[g for g in sh.get_parts(self.source) if g.intersects(self.missing)]
        self.assertEqual(len(pieces),1)
        source=pieces[0];origin=np.asarray(self.origin)[:2]
        packed=sh.make_valid(sh.transform(source,lambda xy:
            (xy-origin).astype(np.float32).astype(np.float64)+origin))
        actual=packed.buffer(1e-6)
        self.assertFalse(actual.intersects(source))
        precision=SourceGreenPrecision(source,actual,self.origin)
        self.assertTrue(precision.filter(self.missing).equals_exact(self.missing,0))

    def test_attached_tail_is_not_treated_as_an_isolated_island(self):
        source=sh.Polygon([(5600,4390),(5601,4390),(5601,4390.5),
            (5601.02,4390.50001),(5601,4390.50002),(5601,4391),(5600,4391)])
        gap=sh.LineString([(5601.001,4390.50001),(5601.018,4390.50001)])
        precision=SourceGreenPrecision(source,sh.Polygon(),self.origin)
        self.assertTrue(precision.filter(gap).equals_exact(gap,0))

    def test_empty_audit_report_needs_no_index(self):
        precision=SourceGreenPrecision(sh.Polygon(),sh.Polygon(),[0,0,0])
        self.assertTrue(precision.filter(sh.LineString()).is_empty)
        self.assertEqual(precision.report()['components'],0)


if __name__=='__main__':unittest.main()
