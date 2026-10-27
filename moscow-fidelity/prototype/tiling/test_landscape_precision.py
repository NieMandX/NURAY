import json,unittest
from pathlib import Path
import numpy as np
import shapely as sh
from landscape_precision import overlap_precision,paving_coverage


class LandscapePrecision(unittest.TestCase):
    def test_unsupported_expected_complement_is_not_a_path(self):
        path=sh.box(0,0,1000,2)
        isolated=sh.box(0,4,1000,4.00001)
        attached=sh.box(4,2,4.00001,1002)
        expected=sh.union_all([path,isolated,attached])
        result=paving_coverage(expected,path)
        self.assertGreater(result['rawMissingM2'],.019)
        self.assertTrue(result['passed'],result)
        self.assertLess(result['uncoveredPavingAreaM2'],1e-7)

    def test_real_narrow_gap_inside_supported_path_fails(self):
        expected=sh.box(0,0,1000,2)
        # The existing 1 mm packing allowance on each side leaves a 10 µm
        # residual. Filtering the missing area itself would wrongly erase it.
        actual=expected.difference(sh.box(0,.999,1000,1.00101))
        result=paving_coverage(expected,actual)
        self.assertFalse(result['passed'],result)
        self.assertGreater(result['uncoveredPavingAreaM2'],.009)

    def test_missing_centimetre_edge_strip_fails(self):
        result=paving_coverage(sh.box(0,0,10,2),sh.box(0,0,10,1.99))
        self.assertFalse(result['passed'],result)
        self.assertGreater(result['uncoveredPavingAreaM2'],.08)

    def test_resolved_thin_expected_path_cannot_be_discarded(self):
        result=paving_coverage(sh.box(0,0,100,.002),sh.Polygon())
        self.assertFalse(result['passed'],result)
        self.assertAlmostEqual(result['uncoveredPavingAreaM2'],.2,places=7)

    def test_missing_whole_path_fails(self):
        self.assertFalse(paving_coverage(sh.box(0,0,10,2),sh.Polygon())['passed'])

    def test_live_paving_complement_regression(self):
        p=Path(__file__).resolve().parents[1]/'fixtures/landscape-paving-complement.json'
        fixture=json.loads(p.read_text())
        result=paving_coverage(sh.geometry.shape(fixture['expected']),
                               sh.geometry.shape(fixture['actual']),fixture['gridM'])
        self.assertGreater(result['rawMissingM2'],.002)
        self.assertTrue(result['passed'],result)
        self.assertLess(result['uncoveredPavingAreaM2'],1e-7)

    def test_actual_single_float32_rounding(self):
        origin=np.array([2125.,8070.]);edge=4222.00013
        packed=float(np.float32(edge-origin[0]))+origin[0]
        self.assertGreater(packed-edge,.0001)
        overlap=sh.box(edge,7000,packed,7010)
        result=overlap_precision(overlap,sh.box(4200,6990,edge,7020),origin)
        self.assertTrue(result['passed'],result)
        self.assertLessEqual(result['maxBoundaryToleranceM'],.000223)

    def test_real_two_mm_intrusion_fails(self):
        result=overlap_precision(sh.box(4222,7000,4222.002,7010),sh.box(4200,6990,4222,7020),[2125,8070])
        self.assertFalse(result['passed'])
        self.assertGreater(result['interiorOverlapM2'],.017)

    def test_thin_interior_overlap_fails(self):
        result=overlap_precision(sh.box(4210,7000,4210.0001,7010),sh.box(4200,6990,4222,7020),[2125,8070])
        self.assertFalse(result['passed'])

    def test_local_origin_translation_invariant(self):
        green=sh.box(0,0,5,5);overlap=sh.box(5,1,5.00004,4)
        from shapely.affinity import translate
        a=overlap_precision(overlap,green,[0,0])
        b=overlap_precision(translate(overlap,1e6,2e6),translate(green,1e6,2e6),[1e6,2e6])
        self.assertEqual(a['passed'],b['passed'])
        self.assertEqual(a['maxBoundaryToleranceM'],b['maxBoundaryToleranceM'])

    def test_insufficient_format_precision_rejected(self):
        result=overlap_precision(sh.box(1e6,1e6,1e6+.0001,1e6+1),sh.box(1e6-1,1e6,1e6,1e6+1),[0,0])
        self.assertFalse(result['precisionPassed'])
        self.assertFalse(result['passed'])

    def test_empty(self):
        self.assertTrue(overlap_precision(sh.Polygon(),sh.Polygon(),[0,0])['passed'])

    def test_live_snapshot_rounding_regression(self):
        p=Path(__file__).resolve().parents[1]/'fixtures/landscape-packed-boundary.json'
        fixture=json.loads(p.read_text())
        green=sh.geometry.shape(fixture['expectedGreen'])
        overlap=sh.geometry.shape(fixture['actualOverlap'])
        self.assertGreater(overlap.difference(green.boundary.buffer(.0001)).area,1e-7)
        result=overlap_precision(overlap,green,fixture['origin'])
        self.assertTrue(result['passed'],result)


if __name__=='__main__':unittest.main()
