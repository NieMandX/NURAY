"""Prepare exact canonical witnesses without city-sized temporary arrays."""
import numpy as np


def source_geometry(raw, chunk, *, batch_size=250_000):
    words = np.frombuffer(raw, '<u4', count=chunk['vertexBytes'] // 4).reshape(-1, 8)
    vertices = words.view('<f4')
    indices = np.frombuffer(raw, '<u4', offset=chunk['vertexBytes']).reshape(-1, 3)
    count = len(indices)
    result = {'area': np.empty(count, dtype=float),
              'material': np.empty(count, dtype='<u4')}
    attributed = chunk.get('objectGeometry') or chunk['name'] == 'waterfront-bank'
    if attributed:
        result['points'] = np.empty((count, 3, 3), dtype=float)
        result['uv'] = np.empty((count, 3, 2), dtype=float)
    for start in range(0, count, batch_size):
        end = min(start + batch_size, count)
        ix = indices[start:end]
        p = vertices[ix, :3].astype(float)
        result['area'][start:end] = np.linalg.norm(
            np.cross(p[:, 1] - p[:, 0], p[:, 2] - p[:, 0]), axis=1) / 2
        result['material'][start:end] = words[ix[:, 0], 6]
        if attributed:
            result['points'][start:end] = p
            result['uv'][start:end] = vertices[ix, 4:6]
    if chunk.get('instanced'):
        result['cornerWords'] = words[indices].copy()
    return result
