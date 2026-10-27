"""Register an exact workshop export without rebuilding or simplifying its shape.

Capture {editor, shading, appearance, path} through the workshop download first.
Then run save_library.mjs with the normalized capture printed by this script.
"""
from pathlib import Path
import argparse, hashlib, json, struct
import numpy as np
import build


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main(args):
    state = json.loads(Path(args.state).read_text())
    editor, shading, appearance = (state[k] for k in ('editor', 'shading', 'appearance'))
    model = editor['model']
    assert shading['model'] == appearance['model'] == model
    assert args.variant.startswith(model + '-approved-')
    choices_path = build.OUT / 'choices.json'
    choices = json.loads(choices_path.read_text())
    assert model not in choices, 'Updating an accepted tree requires an explicit revision workflow'
    folder = build.OUT / args.variant
    assert not folder.exists(), 'Use a new revision; never replace an accepted model'
    raw = Path(state['path']).read_bytes()
    assert struct.unpack_from('<4sII', raw) == (b'glTF', 2, len(raw))
    size, kind = struct.unpack_from('<I4s', raw, 12)
    assert kind == b'JSON'
    doc = json.loads(raw[20:20 + size])
    binary = raw[28 + size:]
    extras = doc['extras']
    for key, expected in dict(model=model, foliageSettings=editor['settings'],
            foliageMode=editor['mode'], foliageSmoothingAngle=shading['angle'],
            foliageColor=appearance['foliageColor'],
            foliageCurvatureStrength=appearance['curvatureStrength']).items():
        assert extras[key] == expected, f'Live state changed before export: {key}'

    def accessor(index):
        a = doc['accessors'][index]
        v = doc['bufferViews'][a['bufferView']]
        assert 'byteStride' not in v
        width = {'VEC3': 3, 'SCALAR': 1}[a['type']]
        dtype = {5126: '<f4', 5125: '<u4'}[a['componentType']]
        return np.frombuffer(binary, dtype, count=a['count'] * width,
            offset=v.get('byteOffset', 0) + a.get('byteOffset', 0)).reshape(a['count'], width)

    primitives = doc['meshes'][0]['primitives']
    attributes = primitives[0]['attributes']
    assert all(p['attributes'] == attributes for p in primitives)
    positions = accessor(attributes['POSITION']).reshape(-1, 3, 3)
    normals = accessor(attributes['NORMAL']).reshape(-1, 3, 3).copy()
    count = len(positions)
    assert count == editor['triangles'] == shading['triangles']
    materials = np.full(count, -1, dtype=np.int32)
    for primitive in primitives:
        ix = accessor(primitive['indices']).reshape(-1, 3)
        assert np.array_equal(ix[:, 1:], ix[:, :1] + [1, 2]) and np.all(ix[:, 0] % 3 == 0)
        assert np.all(materials[ix[:, 0] // 3] == -1)
        materials[ix[:, 0] // 3] = primitive['material']
    assert np.all(materials >= 0)
    assert int((materials < 4).sum()) == editor['foliageTriangles']
    assert int((materials >= 4).sum()) == editor['woodTriangles']
    assert np.isfinite(positions).all() and np.isfinite(normals).all()

    # Store a flat base so the workshop's angle slider still starts at 0°.
    # Positions, material assignments and wood normals remain exactly captured.
    p = positions.astype(np.float64)
    face_normals = np.cross(p[:, 1] - p[:, 0], p[:, 2] - p[:, 0])
    lengths = np.linalg.norm(face_normals, axis=1)
    assert np.all(lengths > 1e-9)
    face_normals /= lengths[:, None]
    normals[materials < 4] = face_normals[materials < 4, None, :]
    geometry = np.concatenate([positions, normals, np.zeros((count, 3, 2), dtype=np.float32)], axis=2)

    catalog = json.loads((build.OUT / 'catalog.json').read_text())
    meta = build.export(folder, geometry, materials.astype(np.uint32), catalog['materials'])
    assert meta['triangles'] == count, 'Packing must not discard accepted triangles'
    scene_path = folder / 'scene.json'
    scene = json.loads(scene_path.read_text())
    scene['chunks'][0]['cornerNormals'] = normals.reshape(-1).tolist()
    scene_path.write_text(json.dumps(scene, ensure_ascii=False, separators=(',', ':')))
    (folder / 'model.glb').write_bytes(raw)
    selected = dict(variant=args.variant, folder=args.variant, label=args.label,
        description=args.description, triangles=count,
        foliageTriangles=editor['foliageTriangles'], woodTriangles=editor['woodTriangles'],
        baseFoliageTriangles=editor['baseFoliageTriangles'], bounds=meta['bounds'],
        settings=editor['settings'], mode=editor['mode'], smoothingAngle=shading['angle'],
        sourceGeometrySha256=sha(build.OUT / model / 'geometry.npz'),
        geometrySha256=sha(folder / 'geometry.npz'), glbSha256=sha(folder / 'model.glb'),
        inputGlbSha256=sha(state['path']), selectedBy='user', date=args.date, integrated=False,
        provenance='Exact live workshop export; no regeneration or simplification on approval.',
        engines=dict(manifold='3.5.4', meshoptimizer='1.3.0'))
    (folder / 'selection.json').write_text(json.dumps(selected, ensure_ascii=False, indent=2) + '\n')
    choices[model] = selected
    choices_path.write_text(json.dumps(choices, ensure_ascii=False, indent=2) + '\n')
    capture = {**state, 'sourceVariant': shading['variant'], 'date': args.date,
        'shading': {**shading, 'variant': args.variant}}
    Path(args.capture).write_text(json.dumps([capture], ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(selected, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    for name in ('state', 'variant', 'label', 'description', 'date', 'capture'):
        parser.add_argument('--' + name, required=True)
    main(parser.parse_args())
