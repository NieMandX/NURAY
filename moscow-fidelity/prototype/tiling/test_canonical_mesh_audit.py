import unittest
import numpy as np
from canonical_mesh_audit import source_geometry


class SourceGeometryTests(unittest.TestCase):
    def test_exact_old_witnesses_across_batch_boundaries(self):
        random = np.random.default_rng(7821)
        words = np.zeros((109, 8), dtype='<u4')
        vertices = words.view('<f4')
        vertices[:, :3] = random.uniform(-5000, 5000, (109, 3))
        vertices[:, 4:6] = random.uniform(-9, 9, (109, 2))
        vertices[0, :3] = [-0.0, 0.0, 1.0]
        words[:, 6] = random.integers(0, 0xffffffff, len(words), dtype='<u4')
        indices = random.integers(0, len(words), (207, 3), dtype='<u4')
        indices[0] = [0, 0, 0]
        raw = words.tobytes() + indices.tobytes()
        p = vertices[indices, :3].astype(float)
        expected = dict(area=np.linalg.norm(np.cross(p[:, 1] - p[:, 0], p[:, 2] - p[:, 0]), axis=1) / 2,
                        material=words[indices[:, 0], 6])
        for kind in ('terrain', 'object', 'waterfront-bank', 'instance'):
            chunk = dict(vertexBytes=words.nbytes, name=kind,
                         objectGeometry=kind in ('object', 'instance'), instanced=kind == 'instance')
            result = dict(expected)
            if chunk['objectGeometry'] or kind == 'waterfront-bank':
                result.update(points=p, uv=vertices[indices, 4:6].astype(float))
            if chunk['instanced']:
                result['cornerWords'] = words[indices].copy()
            for size in (1, 7, 103, 250_000):
                actual = source_geometry(raw, chunk, batch_size=size)
                self.assertEqual(set(actual), set(result))
                for key, value in result.items():
                    self.assertEqual(actual[key].dtype, value.dtype)
                    self.assertEqual(actual[key].shape, value.shape)
                    self.assertEqual(actual[key].tobytes(), value.tobytes(), (kind, size, key))

    def test_empty_mesh_keeps_witness_shapes(self):
        result = source_geometry(b'', dict(vertexBytes=0, name='empty', objectGeometry=True, instanced=True))
        self.assertEqual(result['points'].shape, (0, 3, 3))
        self.assertEqual(result['uv'].shape, (0, 3, 2))
        self.assertEqual(result['cornerWords'].shape, (0, 3, 8))


if __name__ == '__main__':
    unittest.main()
