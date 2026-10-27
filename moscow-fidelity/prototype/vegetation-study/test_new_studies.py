"""Geometry and editor contracts for the three additional source classes."""
import gzip
import hashlib
import json
import numpy as np
import build

catalog = json.loads((build.OUT / 'catalog.json').read_text())
expected = {'thuja': (12, 1), 'growth': (9, 3), 'low': (11, 1)}
for model, (leaves, trunks) in expected.items():
    row = next(r for r in catalog['models'] if r['id'] == model)
    a, materials, parts = build.make(model, row['sourceBounds'])
    build.validate(a, parts)
    again, again_materials, _ = build.make(model, row['sourceBounds'])
    assert np.array_equal(a, again) and np.array_equal(materials, again_materials)
    stored = np.load(build.OUT / model / 'geometry.npz')
    assert np.array_equal(a, stored['attributes'])
    assert np.array_equal(materials, stored['materials'])
    foliage = [p for p in parts if p['kind'] == 'foliage']
    stems = [p for p in parts if p.get('role') == 'trunk']
    assert len(foliage) == leaves and len(stems) == trunks
    assert np.allclose(np.linalg.norm(a[:, :, 3:6], axis=2), 1)
    assert a[:, :, 1].min() >= -1e-7, 'Base foliage must remain above ground'
    for part in stems:
        radii = [s['radius'] for s in part['roundSections']]
        assert np.all(np.diff(radii) <= 1e-12), 'Trunk must taper upwards'
        for section in part['roundSections']:
            assert section['radius'] <= min(section['beforeRadii']) + 1e-12, 'Circularizing may only narrow the trunk'
    source = np.array(row['sourceBounds']['max']) - row['sourceBounds']['min']
    actual = np.ptp(a[:, :, :3], axis=(0, 1))
    assert np.all(actual / source < 1.2), 'Large fragments must stay close to source class dimensions'
    editor = json.loads(gzip.decompress((build.OUT / model / 'editor.json.gz').read_bytes()))
    assert editor['model'] == model
    assert editor['baseGeometrySha256'] == hashlib.sha256((build.OUT / model / 'geometry.npz').read_bytes()).hexdigest()
    assert len(editor['fragments']) == leaves
    assert editor['wood']['triangles'] == int((materials >= 4).sum())
    assert editor['wood']['triangles'] + sum(f['levels'][0]['triangles'] for f in editor['fragments']) == len(a)
    print(f'PASS {model}: {len(a)} triangles, {leaves} fragments, {trunks} tapered circular trunks; exact editor geometry, closed meshes, stable size and seed')
