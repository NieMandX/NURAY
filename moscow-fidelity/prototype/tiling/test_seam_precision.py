"""Serialized passage precision scales with format ULP, never with object ID."""
import unittest
import json
from pathlib import Path
import numpy as np
import shapely as sh
from seam_validation import check_passages


def rectangle(x0,z0,x1,z1,height=0):
    return np.array([[[x0,height,z0],[x1,height,z0],[x1,height,z1]],
                     [[x0,height,z0],[x1,height,z1],[x0,height,z1]]],dtype=np.float32).astype(float)


class SerializedPassagePrecision(unittest.TestCase):
    def check(self,gate,meshes):
        return check_passages([(dict(sourceParents=['left','right']),gate)],meshes)

    def test_float32_boundary_rounding_in_large_region(self):
        right=2500.0001
        gate=sh.box(2499.98,10,right-.00001,70)
        meshes=[('roadbed_flat',rectangle(2490,0,right,80)),
                ('curb_top',rectangle(right,0,2510,80,.1))]
        result=self.check(gate,meshes);row=result['checks'][0]
        self.assertTrue(result['passed'],row)
        self.assertGreater(row['missingAsphaltM2'],1e-5)
        self.assertGreater(row['curbRoofM2'],1e-5)
        self.assertEqual(row['curbRoofCoreM2'],0)
        self.assertLess(row['positionToleranceM'],.0005)

    def test_real_two_millimetre_gap_is_rejected_at_every_distance(self):
        for offset in (0,2500,-2500):
            with self.subTest(offset=offset):
                gate=sh.box(offset-.02,10,offset+.02,70)
                meshes=[('roadbed_flat',rectangle(offset-1,0,offset-.001,80)),
                        ('roadbed_flat',rectangle(offset+.001,0,offset+1,80))]
                row=self.check(gate,meshes)['checks'][0]
                self.assertFalse(row['passed'])
                self.assertGreater(row['missingAsphaltBeyondToleranceM2'],.01)

    def test_real_horizontal_and_vertical_barriers_are_rejected(self):
        gate=sh.box(2499.98,10,2500.02,70)
        asphalt=('roadbed_flat',rectangle(2490,0,2510,80))
        for kind in ('land','curb_top','curb_bottom'):
            with self.subTest(kind=kind):
                obstacle=(kind,rectangle(2499.999,10,2500.001,70,.1))
                self.assertFalse(self.check(gate,[asphalt,obstacle])['passed'])
        wall=np.array([[[2500,0,20],[2500,0,60],[2500,.1,60]],
                       [[2500,0,20],[2500,.1,60],[2500,.1,20]]],dtype=float)
        row=self.check(gate,[asphalt,('curb_front',wall)])['checks'][0]
        self.assertFalse(row['passed'])
        self.assertEqual(row['curbSideM'],40)

    def test_tolerance_is_local_and_has_a_fixed_ceiling(self):
        near=self.check(sh.box(0,10,.02,70),[('roadbed_flat',rectangle(-1,0,1,80))])['checks'][0]
        self.assertLess(near['positionToleranceM'],.00006)
        far=self.check(sh.box(1e6,10,1e6+1,70),[('roadbed_flat',rectangle(1e6-1,0,1e6+2,80))])['checks'][0]
        self.assertFalse(far['precisionPassed'])
        self.assertFalse(far['passed'])

    def test_acute_gate_keeps_real_asphalt_just_outside_its_cap(self):
        data=json.loads((Path(__file__).parents[1]/'fixtures/serialized-seam-acute-cap.json').read_text())
        gate=sh.geometry.shape(data['gate']);triangles=np.asarray(data['triangles'])
        result=self.check(gate,[('roadbed_flat',triangles)])
        self.assertTrue(result['passed'],result)
        tolerance=result['checks'][0]['positionToleranceM']
        asphalt=sh.union_all(sh.polygons(triangles[:,:,[0,2]]))
        self.assertGreater(gate.difference(asphalt.intersection(gate).buffer(tolerance)).area,1e-7)
        self.assertEqual(result['checks'][0]['missingAsphaltBeyondToleranceM2'],0)


if __name__=='__main__':unittest.main()
