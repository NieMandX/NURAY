"""Interpolation must preserve slopes and must never bridge real data gaps."""
import unittest
import numpy as np
from shapely.geometry import box

from prepare_supplement import Terrain, close_quantization_cracks


def rectangle(x0, y0, x1, y1):
    xy = np.array([[[x0,y0],[x1,y0],[x1,y1]], [[x0,y0],[x1,y1],[x0,y1]]], dtype=float)
    return np.concatenate([xy, (2 * xy[:, :, 0] - 3 * xy[:, :, 1] + 17)[:, :, None]], axis=2)


class TerrainTests(unittest.TestCase):
    def test_sloped_ground_including_shared_edge(self):
        terrain = Terrain(rectangle(-10,-10,10,10))
        xy = np.array([[0,0],[4,-7],[-8,9],[10,10]])
        np.testing.assert_allclose(terrain.sample(xy), 2*xy[:,0]-3*xy[:,1]+17, atol=1e-10)

    def test_degenerate_faces_are_not_interpolation_planes(self):
        triangles = np.concatenate([rectangle(0,0,1,1), np.zeros((1,3,3))])
        terrain = Terrain(triangles)
        self.assertEqual(terrain.discarded_degenerate, 1)
        self.assertEqual(terrain.sample([[0,0]])[0], 17)

    def test_points_outside_coverage_fail_instead_of_floating(self):
        with self.assertRaisesRegex(ValueError, 'outside captured terrain'):
            Terrain(rectangle(0,0,1,1)).sample([[2,0]])

    def test_narrow_quantization_crack_preserves_boundary_height(self):
        terrain = Terrain(np.concatenate([rectangle(0,0,1,1), rectangle(1.02,0,2,1)]))
        repaired, report = close_quantization_cracks(terrain, box(0,0,2,1))
        self.assertAlmostEqual(report['sourceGapAreaM2'], .02)
        self.assertAlmostEqual(repaired.sample([[1.01,.5]])[0], 2*1.01-3*.5+17)

    def test_real_gap_is_not_silently_filled(self):
        terrain = Terrain(np.concatenate([rectangle(0,0,1,1), rectangle(1.5,0,2,1)]))
        with self.assertRaisesRegex(ValueError, 'real coverage gap'):
            close_quantization_cracks(terrain, box(0,0,2,1))


if __name__ == '__main__':
    unittest.main()
