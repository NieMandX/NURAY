"""Source-labelled roof slopes get their own approved matte-metal material.

Never infer roofs from arbitrary sloping geometry: source roof ownership is
required. Vertical gables, horizontal caps and authored landmark models retain
their original materials. Triangle winding does not change the classification.
"""
import gzip
from pathlib import Path
from collections import Counter
import numpy as np
from source_objects import BUILDING_LAYERS, source_class
from material_remap import remap

MATERIAL = dict(name='Кровля · скатная · матовый металл', family='pitched-roof',
                color=[.112, .128, .140], roughness=.55, metallic=.8,
                ior=1.5, kind=1, alphaCutoff=0, texture=None)
ANGLE_TOLERANCE = 1.0
POLICY = dict(version=1, source='explicit physical building *_roof source class',
              selection='inclined source roof faces only, independent of winding',
              angleToleranceDegrees=ANGLE_TOLERANCE,
              preserve='vertical gables, horizontal caps, house bodies, detailed models, positions, normals, UVs, tint, triangle order and BVHs')


def roof_row(row):
    layer = source_class(row)
    return row.get('category') == 'building' and layer in BUILDING_LAYERS and layer.endswith('_roof')


def slope_mask(xyz):
    p = np.asarray(xyz, dtype=float)
    n = np.cross(p[:, 1] - p[:, 0], p[:, 2] - p[:, 0])
    length = np.linalg.norm(n, axis=1)
    cosine = abs(n[:, 1]) / np.maximum(length, 1e-20)
    return (length > 1e-9) & (cosine > np.sin(np.deg2rad(ANGLE_TOLERANCE))) & (cosine < np.cos(np.deg2rad(ANGLE_TOLERANCE)))


def select_faces(data, chunk, rows):
    vertices = np.frombuffer(data[:chunk['vertexBytes']], '<u4').reshape(-1, 8)
    ix = np.frombuffer(data[chunk['vertexBytes']:], '<u4').reshape(-1, 3)
    selected = np.zeros(len(ix), dtype=bool)
    counts = Counter()
    for r in chunk.get('sourceObjectRanges', []):
        if r['id'] not in rows or not roof_row(rows[r['id']]):
            continue
        start, end = r['first'], r['first'] + r['count']
        mask = slope_mask(vertices.view('<f4')[ix[start:end], :3])
        selected[start:end] = mask
        if mask.any():
            counts[r['id']] += int(mask.sum())
    return selected, counts


def install(rows, scene, folder):
    by_id = {r['id']: r for r in rows}
    material = next((i for i, m in enumerate(scene['materials']) if m.get('family') == MATERIAL['family']), len(scene['materials']))
    if material < len(scene['materials']):
        assert scene['materials'][material] == MATERIAL
    labels, counts = {}, Counter()
    for c in scene['chunks']:
        if c.get('category') != 'building':
            continue
        path = folder / Path(c['file']).name
        data = gzip.decompress(path.read_bytes())
        mask, objects = select_faces(data, c, by_id)
        if not mask.any():
            continue
        labels[c['id']] = mask
        counts.update(objects)
        updated, vb, _ = remap(data, c['vertexBytes'], c['triangles'] * 12, mask, material)
        if updated != data:
            path.write_bytes(gzip.compress(updated, compresslevel=6, mtime=0))
        c.update(vertexBytes=vb, vertexCount=vb // 32)
    if counts and material == len(scene['materials']):
        scene['materials'].append(dict(MATERIAL))
    updates = [dict(id=owner, pitchedRoof=dict(material=material, triangles=count, policy=POLICY)) for owner, count in counts.items()]
    for update in updates:
        by_id[update['id']].update(update)
    return dict(policy=POLICY, material=material, labels=labels, buildings=updates,
                stats=dict(buildings=len(counts), triangles=sum(counts.values()), changedCanonicalChunks=len(labels)))
