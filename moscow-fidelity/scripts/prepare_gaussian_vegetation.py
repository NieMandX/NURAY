"""Prepare real 3DGS PLY templates; covariance moment LODs, no mesh conversion.

PLY parameters follow the official VAST-AI-Research/TripoSplat exporter:
log scale, logit opacity, SH DC colour, normalized wxyz quaternion.
Input orientation is explicit: TripoSplat's default export uses -Y up.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct

import numpy as np


def read_ply(path):
    data = Path(path).read_bytes()
    end = data.index(b'end_header\n') + len(b'end_header\n')
    header = data[:end].decode('ascii')
    if 'format binary_little_endian 1.0' not in header:
        raise ValueError('Expected binary little-endian 3DGS PLY')
    names = re.findall(r'^property float (\w+)$', header, re.M)
    count = int(re.search(r'element vertex (\d+)', header)[1])
    if len(re.findall(r'^property ', header, re.M)) != len(names):
        raise ValueError('Unsupported PLY property; do not silently misalign records')
    if len(data) - end != count * len(names) * 4:
        raise ValueError('PLY byte length does not match vertex layout')
    arr = np.frombuffer(data, '<f4', offset=end).reshape(count, len(names)).astype(float)
    required = ['x', 'y', 'z', 'f_dc_0', 'f_dc_1', 'f_dc_2', 'opacity']
    required += [f'scale_{i}' for i in range(3)] + [f'rot_{i}' for i in range(4)]
    if not set(required).issubset(names) or np.isnan(arr).any():
        raise ValueError('Not a finite Gaussian splat file')
    col = lambda keys: arr[:, [names.index(k) for k in keys]]
    # Exact alpha=1 is legitimately serialized as +inf by inverse sigmoid.
    if not np.isfinite(col([k for k in required if k != 'opacity'])).all():
        raise ValueError('Nonfinite Gaussian geometry or colour')
    pos = col(['x', 'y', 'z'])
    color = np.clip(.5 + .28209479177387814 * col(required[3:6]), 0, 1)
    alpha = 1 / (1 + np.exp(-np.clip(col(['opacity'])[:, 0], -80, 80)))
    scale = np.exp(np.clip(col([f'scale_{i}' for i in range(3)]), -20, 10))
    q = col([f'rot_{i}' for i in range(4)])
    q /= np.maximum(np.linalg.norm(q, axis=1)[:, None], 1e-20)
    w, x, y, z = q.T
    rot = np.stack([1-2*(y*y+z*z), 2*(x*y-w*z), 2*(x*z+w*y),
                    2*(x*y+w*z), 1-2*(x*x+z*z), 2*(y*z-w*x),
                    2*(x*z-w*y), 2*(y*z+w*x), 1-2*(x*x+y*y)], axis=1).reshape(-1, 3, 3)
    basis = rot * scale[:, None, :]
    cov = basis @ basis.transpose(0, 2, 1)
    keep = alpha >= .02
    return pos[keep], cov[keep], color[keep], alpha[keep], count


def normalize(pos, cov, up):
    # A proper 180 degree rotation, including covariance, preserves chirality.
    orient = np.diag([1., -1., -1.]) if up == '-y' else np.eye(3)
    pos = pos @ orient.T
    cov = orient @ cov @ orient.T
    floor, top = pos[:, 1].min(), pos[:, 1].max()
    height = top - floor
    if height <= 1e-6:
        raise ValueError('Degenerate plant height')
    root = np.median(pos[pos[:, 1] < floor + height * .05], axis=0)
    root[1] = floor
    return (pos-root)/height, cov/height**2, {'inputUp': up, 'root': root.tolist(), 'height': height}


def merge_voxels(pos, cov, color, alpha, cell):
    keys = np.floor(pos/cell).astype(np.int32)
    _, ids = np.unique(keys, axis=0, return_inverse=True)
    n = ids.max()+1
    # Average projected Gaussian area is a stable mass across view directions.
    ev = np.sqrt(np.maximum(np.linalg.eigvalsh(cov), 1e-16))
    area = ev[:, 0]*ev[:, 1]+ev[:, 0]*ev[:, 2]+ev[:, 1]*ev[:, 2]
    mass = area*alpha
    total = np.bincount(ids, weights=mass, minlength=n)
    average = lambda a: np.stack([np.bincount(ids, weights=mass*a[:, k], minlength=n)/total
                                 for k in range(a.shape[1])], axis=1)
    center = average(pos)
    delta = pos-center[ids]
    out_cov = average((cov+delta[:, :, None]*delta[:, None, :]).reshape(-1, 9)).reshape(-1, 3, 3)
    ev2 = np.sqrt(np.maximum(np.linalg.eigvalsh(out_cov), 1e-16))
    area2 = ev2[:, 0]*ev2[:, 1]+ev2[:, 0]*ev2[:, 2]+ev2[:, 1]*ev2[:, 2]
    return center, out_cov, average(color), np.minimum(.995, total/area2)


def lod(pos, cov, color, alpha, target):
    lo, hi = .0001, 2.
    for _ in range(22):
        mid = (lo+hi)/2
        count = len(np.unique(np.floor(pos/mid).astype(np.int32), axis=0))
        if count > target:
            lo = mid
        else:
            hi = mid
    return merge_voxels(pos, cov, color, alpha, hi)


def packed(pos, cov, color, alpha):
    out = np.zeros((len(pos), 16), '<f4')
    out[:, :3] = pos
    out[:, 3] = alpha
    out[:, 4:8] = cov[:, [0, 0, 0, 1], [0, 1, 2, 1]]
    out[:, 8:10] = cov[:, [1, 2], [2, 2]]
    out[:, 12:15] = color
    out[:, 15] = 1
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('ply', type=Path)
    ap.add_argument('output', type=Path)
    ap.add_argument('--name', default='broadleaf')
    ap.add_argument('--up', choices=['y', '-y'], default='-y')
    args = ap.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    pos, cov, color, alpha, raw_count = read_ply(args.ply)
    pos, cov, orientation = normalize(pos, cov, args.up)
    levels = [(pos, cov, color, alpha)] + [lod(pos, cov, color, alpha, n) for n in [8192, 2048, 512, 128]]
    arrays, records, offset = [], [], 0
    for i, values in enumerate(levels):
        arr = packed(*values)
        arrays.append(arr)
        records.append({'offset': offset, 'count': len(arr)})
        offset += len(arr)
    data = np.concatenate(arrays).tobytes()
    file = args.name+'.gsbin'
    (args.output/file).write_bytes(data)
    model = {'format': 'nuray-gaussians-v1', 'name': args.name, 'file': file,
             'strideFloats': 16, 'levels': records, 'bytes': len(data),
             'sha256': hashlib.sha256(data).hexdigest(),
             'bounds': {'min': pos.min(axis=0).tolist(), 'max': pos.max(axis=0).tolist()},
             'source': {'file': args.ply.name, 'sha256': hashlib.sha256(args.ply.read_bytes()).hexdigest(),
                        'provider': 'Weavy / tripo3d/triposplat', 'rawGaussians': raw_count,
                        'orientation': orientation},
             'lodMethod': 'voxel covariance moments; approximate projected-area opacity conservation',
             'lighting': 'baked SH degree zero; not a physically relightable surface'}
    (args.output/(args.name+'.json')).write_text(json.dumps(model, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps({'file': file, 'levels': records, 'bytes': len(data)}))


if __name__ == '__main__':
    main()
