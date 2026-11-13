"""Numerical contracts for imported Gaussian vegetation, without a browser/GPU."""
import tempfile
import unittest
from pathlib import Path

import numpy as np

from prepare_gaussian_vegetation import read_ply, normalize, merge_voxels, lod, packed


class GaussianVegetationTests(unittest.TestCase):
    def test_ply_log_parameters_and_quaternion(self):
        names = ['x', 'y', 'z', 'nx', 'ny', 'nz', 'f_dc_0', 'f_dc_1',
                 'f_dc_2', 'opacity', 'scale_0', 'scale_1', 'scale_2',
                 'rot_0', 'rot_1', 'rot_2', 'rot_3']
        row = np.zeros((1, len(names)), '<f4')
        row[0, :3] = [1, 2, 3]
        row[0, 9] = np.inf  # TripoSplat legitimately exports alpha=1 this way.
        row[0, 10:13] = np.log([1, 2, 3])
        row[0, [13, 16]] = np.sqrt(.5)  # 90 degrees about Z, wxyz.
        header = ('ply\nformat binary_little_endian 1.0\nelement vertex 1\n'
                  + ''.join(f'property float {n}\n' for n in names) + 'end_header\n')
        with tempfile.TemporaryDirectory() as tmp:
            file = Path(tmp) / 'tree.ply'
            file.write_bytes(header.encode() + row.tobytes())
            pos, cov, color, alpha, count = read_ply(file)
            self.assertEqual(count, 1)
            np.testing.assert_allclose(pos, [[1, 2, 3]])
            np.testing.assert_allclose(cov[0], np.diag([4, 1, 9]), atol=1e-6)
            np.testing.assert_allclose(color, .5)
            np.testing.assert_allclose(alpha, 1)
            file.write_bytes(file.read_bytes()[:-1])
            with self.assertRaisesRegex(ValueError, 'byte length'):
                read_ply(file)

    def test_orientation_root_and_covariance_use_same_transform(self):
        pos = np.array([[2., 1, 3], [4, -9, 5]])
        c = np.array([[4., .3, .2], [.3, 9, .1], [.2, .1, 16]])
        cov = np.repeat(c[None], 2, axis=0)
        p, sigma, meta = normalize(pos, cov, '-y')
        np.testing.assert_allclose(p, [[0, 0, 0], [.2, 1, -.2]])
        rotation = np.diag([1, -1, -1])
        np.testing.assert_allclose(sigma[0], rotation @ c @ rotation.T / 100)
        self.assertEqual(meta['height'], 10)

    def test_lod_preserves_weighted_moments_and_positive_covariance(self):
        pos = np.array([[.1, .2, .1], [.3, .4, .1]])
        cov = np.repeat(np.eye(3)[None] * .01, 2, axis=0)
        color = np.array([[.2, .4, .1], [.4, .8, .3]])
        alpha = np.array([.25, .75])
        p, sigma, rgb, a = merge_voxels(pos, cov, color, alpha, 1)
        weights = alpha / alpha.sum()
        center = weights @ pos
        delta = pos - center
        expected = sum(w * (s + np.outer(d, d)) for w, s, d in zip(weights, cov, delta))
        np.testing.assert_allclose(p[0], center)
        np.testing.assert_allclose(sigma[0], expected)
        np.testing.assert_allclose(rgb[0], weights @ color)
        self.assertTrue(np.linalg.eigvalsh(sigma).min() > 0)
        self.assertTrue(np.all((a > 0) & (a <= .995)))

    def test_low_detail_output_is_finite_within_budget(self):
        rng = np.random.default_rng(42)
        pos = rng.uniform(-.5, .5, (300, 3))
        cov = np.repeat(np.eye(3)[None] * .0001, 300, axis=0)
        result = lod(pos, cov, rng.random((300, 3)), rng.uniform(.05, 1, 300), 32)
        data = packed(*result)
        self.assertLessEqual(len(data), 32)
        self.assertTrue(np.isfinite(data).all())
        self.assertEqual(data.strides[0], 64)
        self.assertTrue(np.linalg.eigvalsh(result[1]).min() > 0)


if __name__ == '__main__':
    unittest.main()
