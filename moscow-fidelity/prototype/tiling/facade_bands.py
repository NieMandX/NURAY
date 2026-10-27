"""Ordinary house walls: lighter PBR finish and ground-relative storey bands.

Bands are a tiny periodic material texture, not geometry. Its UV height is
derived before tile cutting, so bends and transport seams cannot restart it.
The three-metre spacing is explicitly illustrative, not measured storeys.
"""
import gzip, hashlib
from pathlib import Path
import numpy as np
from PIL import Image
from source_objects import source_class
from flat_roofs import HOUSE_TYPES

FAMILY = 'generated-facade-storeys'
BRIGHTNESS = 1.35
STOREY_METRES = 3.0
TEXTURE = 'facade-storey-bands-v1.png'
POLICY = dict(version=1, brightness=BRIGHTNESS, storeyHeightM=STOREY_METRES,
              storeys='illustrative spacing; no authoritative floor count in retained building attributes',
              scope='near-vertical ordinary house walls with the Buildings material',
              preserve='all roof surfaces, landmarks, geometry, normals, tint, triangle order and BVHs',
              alignment='source building group ground datum; continuous across corners and tiles')


def make_material(source):
    return {**source, 'name': 'Фасад · светлый · этажные пояса', 'family': FAMILY,
            'color': [min(1., c * BRIGHTNESS) for c in source['color']],
            'texture': 'textures/' + TEXTURE, 'facadeBands': POLICY}


def make_texture(path):
    # A narrow recessed stripe with a soft edge: 12 cm in a 3 m repeat.
    # Both ends are equal, so the material wraps without a texture seam.
    y = (np.arange(256) + .5) / 256
    distance = np.minimum(y, 1-y)
    coverage = np.clip((.023-distance)/.006, 0, 1)
    linear = 1 - .28 * coverage
    srgb = np.round((1.055 * linear ** (1/2.4) - .055) * 255).astype('uint8')
    pixels = np.repeat(srgb[:, None, None], 8, axis=1).repeat(3, axis=2)
    Image.fromarray(pixels, 'RGB').save(path)
    return dict(bytes=path.stat().st_size, sha256=hashlib.sha256(path.read_bytes()).hexdigest())


def building_bases(rows, origin):
    landmarks = {r.get('sourceBuildingId') for r in rows if r['category'] == 'landmark'}
    bases = {}
    for r in rows:
        layer = source_class(r)
        body = layer.removesuffix('_roof')
        if r['category'] != 'building' or body not in HOUSE_TYPES or r.get('sourceBuildingId') in landmarks:
            continue
        p = r['placement']
        # The same datum is shared by the body and its independently stored
        # roof/gables. Never restart the pattern at a chunk or tile boundary.
        base = p.get('targetBaseM')
        if base is None: continue
        bases[r['id']] = float(base) - origin[2]
    return bases


def select_faces(data, chunk, bases, body_materials):
    vertices = np.frombuffer(data[:chunk['vertexBytes']], '<u4').reshape(-1, 8)
    ix = np.frombuffer(data[chunk['vertexBytes']:], '<u4').reshape(-1, 3)
    phase = np.full(len(ix), np.nan, dtype='<f4')
    for r in chunk.get('sourceObjectRanges', []):
        if r['id'] not in bases: continue
        start, end = r['first'], r['first'] + r['count']
        words = vertices[ix[start:end]]
        xyz = words.view('<f4')[:, :, :3].astype(float)
        n = np.cross(xyz[:, 1]-xyz[:, 0], xyz[:, 2]-xyz[:, 0])
        length = np.linalg.norm(n, axis=1)
        wall = (length > 1e-9) & (abs(n[:, 1]) <= length * np.sin(np.deg2rad(1.)))
        wall &= np.isin(words[:, 0, 6] & 0x7fffffff, body_materials)
        phase[start:end][wall] = bases[r['id']]
    return phase


def apply_faces(data, vertex_bytes, index_bytes, phase, material):
    """Change only selected face material/UV; split shared vertices as needed."""
    old = np.frombuffer(data[:vertex_bytes], '<u4').reshape(-1, 8)
    ix = np.frombuffer(data[vertex_bytes:vertex_bytes+index_bytes], '<u4').reshape(-1, 3)
    mask = np.isfinite(phase)
    if not mask.any(): return data, vertex_bytes
    corners = old[ix].copy()
    f = corners.view('<f4')
    f[mask, :, 4] = .5
    f[mask, :, 5] = (f[mask, :, 1] - phase[mask, None]) / STOREY_METRES
    corners[mask, :, 6] = (corners[mask, :, 6] & np.uint32(0x80000000)) | np.uint32(material)
    unique, inverse = np.unique(corners.reshape(-1, 8).view('V32').ravel(), return_inverse=True)
    vertices = unique.view('<u4').reshape(-1, 8)
    indices = inverse.reshape(-1, 3).astype('<u4')
    assert np.array_equal(vertices[indices], corners)
    assert np.array_equal(corners[:, :, [0, 1, 2, 3, 7]], old[ix][:, :, [0, 1, 2, 3, 7]])
    assert np.array_equal(corners[~mask], old[ix][~mask])
    return vertices.tobytes() + indices.tobytes() + data[vertex_bytes+index_bytes:], vertices.nbytes


def install(rows, scene, folder):
    material = len(scene['materials'])
    existing = [i for i, m in enumerate(scene['materials']) if m.get('family') == FAMILY]
    if existing: return dict(material=existing[0], labels={}, buildings=[], policy=POLICY, stats={})
    body = [i for i, m in enumerate(scene['materials']) if m.get('family') == 'Buildings' and not m.get('texture')]
    assert len(body) == 1
    bases = building_bases(rows, scene['origin'])
    labels = {}; owners = set(); triangles = 0
    for c in scene['chunks']:
        if c.get('category') != 'building': continue
        path = folder / Path(c['file']).name
        data = gzip.decompress(path.read_bytes())
        phase = select_faces(data, c, bases, body)
        if not np.isfinite(phase).any(): continue
        labels[c['id']] = phase
        updated, vb = apply_faces(data, c['vertexBytes'], c['triangles']*12, phase, material)
        path.write_bytes(gzip.compress(updated, compresslevel=6, mtime=0))
        c.update(vertexBytes=vb, vertexCount=vb//32)
        triangles += int(np.isfinite(phase).sum())
        owners.update(r['id'] for r in c['sourceObjectRanges'] if np.isfinite(phase[r['first']:r['first']+r['count']]).any())
    if not labels: raise ValueError('No ordinary house facades selected')
    scene['materials'].append(make_material(scene['materials'][body[0]]))
    scene['textures'][TEXTURE] = make_texture(folder / TEXTURE)
    updates = [dict(id=owner, facadeBands=dict(material=material, baseY=bases[owner], **POLICY)) for owner in sorted(owners)]
    by_id = {r['id']: r for r in rows}
    for update in updates: by_id[update['id']].update(update)
    return dict(material=material, labels=labels, buildings=updates, policy=POLICY,
                stats=dict(buildings=len(owners), triangles=triangles, changedCanonicalChunks=len(labels)))
