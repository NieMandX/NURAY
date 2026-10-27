"""One-tree Boolean/decimation experiment. Run in isolated background Blender.

Blender --background --factory-startup --python .../optimize.py
Only writes compact-* study assets; never replaces the accepted source model.
"""
from pathlib import Path
import sys, json, time, hashlib
import bpy, bmesh
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build


def mesh_object(name, triangles, material_ids, materials):
    vertices, inverse = np.unique(triangles.reshape(-1, 3), axis=0, return_inverse=True)
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(vertices.tolist(), [], inverse.reshape(-1, 3).tolist())
    for material in materials:
        mesh.materials.append(material)
    for face, index in zip(mesh.polygons, material_ids):
        face.material_index = int(index)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def apply(obj, modifier):
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.modifier_apply(modifier=modifier.name)


def copy_object(obj, name):
    result = obj.copy()
    result.data = obj.data.copy()
    result.name = name
    bpy.context.scene.collection.objects.link(result)
    return result


def geometry(obj):
    mesh = obj.data
    mesh.calc_loop_triangles()
    v = np.array([v.co[:] for v in mesh.vertices])
    faces = np.array([t.vertices[:] for t in mesh.loop_triangles])
    p = v[faces]
    n = np.cross(p[:, 1]-p[:, 0], p[:, 2]-p[:, 0])
    length = np.linalg.norm(n, axis=1)
    assert np.isfinite(p).all() and np.all(length > 1e-9), 'Invalid triangle'
    n /= length[:, None]
    attrs = np.concatenate([p, np.repeat(n[:, None, :], 3, axis=1), np.zeros((len(p), 3, 2))], axis=2)
    mats = np.array([t.material_index for t in mesh.loop_triangles], dtype=np.uint32)
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bad_edges = sum(not e.is_manifold or not e.is_contiguous for e in bm.edges)
    volume = bm.calc_volume(signed=True)
    bm.free()
    assert bad_edges == 0 and volume > 0, (obj.name, bad_edges, volume)
    return attrs, mats, dict(closed=True, volume=float(volume), surfaceArea=float(length.sum()/2))


def main():
    started = time.perf_counter()
    # A factory-startup process; never connect this script to a user's live scene.
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    source = np.load(build.OUT/'compact/geometry.npz')
    original, original_mats = source['attributes'], source['materials']
    catalog = json.loads((build.OUT/'catalog.json').read_text())
    row = next(r for r in catalog['models'] if r['id']=='compact')
    generated, _, parts = build.make('compact', row['sourceBounds'])
    assert np.array_equal(original, generated), 'Regenerate source study first'
    wood = original_mats >= 4
    materials = [bpy.data.materials.new(m['name']) for m in catalog['materials']]
    leaves = []
    for i, part in enumerate(parts):
        if part['kind'] != 'foliage':
            continue
        a, b = part['start'], part['end']
        leaves.append(mesh_object(f'foliage-{i}', original[a:b, :, :3], original_mats[a:b], materials))
    union = leaves[0]
    operands = bpy.data.collections.new('union-operands')
    bpy.context.scene.collection.children.link(operands)
    for obj in leaves[1:]:
        operands.objects.link(obj)
    modifier = union.modifiers.new('Exact crown union', 'BOOLEAN')
    assert 'EXACT' in {i.identifier for i in modifier.bl_rna.properties['solver'].enum_items}
    modifier.operation = 'UNION'
    modifier.solver = 'EXACT'
    modifier.operand_type = 'COLLECTION'
    modifier.collection = operands
    apply(union, modifier)
    union_seconds = time.perf_counter()-started
    rows = []

    def save(obj, key, label, description):
        foliage, mats, quality = geometry(obj)
        attrs = np.concatenate([original[wood], foliage])
        mids = np.concatenate([original_mats[wood], mats])
        folder = build.OUT/key
        meta = build.export(folder, attrs, mids, catalog['materials'])
        assert meta['triangles'] == len(attrs)
        assert np.array_equal(attrs[:wood.sum()], original[wood])
        result = dict(id=key, label=label, description=description, triangles=meta['triangles'],
                      foliageTriangles=len(foliage), woodTriangles=int(wood.sum()), bounds=meta['bounds'],
                      meshBytes=(folder/'mesh-000.bin.gz').stat().st_size,
                      glbBytes=(folder/'model.glb').stat().st_size, **quality)
        rows.append(result)
        print(json.dumps(result, ensure_ascii=False), flush=True)

    save(union, 'compact-union', 'Объединение', 'Точная внешняя оболочка листвы. Внутренние поверхности удалены; ствол и ветви исходные.')
    clean = copy_object(union, 'clean')
    dissolve = clean.modifiers.new('Dissolve coplanar cuts', 'DECIMATE')
    dissolve.decimate_type = 'DISSOLVE'
    dissolve.angle_limit = 1e-5
    dissolve.delimit = {'MATERIAL'}
    apply(clean, dissolve)
    save(clean, 'compact-clean', 'Объединение · очистка', 'Внешняя оболочка с удалением лишних рёбер в одной плоскости. Сохранены границы материалов.')
    for ratio in (.75, .50, .35):
        reduced = copy_object(clean, f'reduced-{ratio}')
        decimate = reduced.modifiers.new('Simplify crown', 'DECIMATE')
        decimate.decimate_type = 'COLLAPSE'
        decimate.ratio = ratio
        decimate.use_collapse_triangulate = True
        apply(reduced, decimate)
        save(reduced, f'compact-reduced-{int(ratio*100)}', f'Упрощение {int(ratio*100)}%',
             'Объединённая и упрощённая листва; ствол и ветви исходные. Доля относится к сетке листвы после очистки.')
    report = dict(source='compact', sourceGeometrySha256=hashlib.sha256((build.OUT/'compact/geometry.npz').read_bytes()).hexdigest(),
                  sourceTriangles=len(original), sourceFoliageTriangles=int((~wood).sum()), woodTriangles=int(wood.sum()),
                  sourceMeshBytes=(build.OUT/'compact/mesh-000.bin.gz').stat().st_size,
                  blenderVersion=bpy.app.version_string, unionSeconds=union_seconds,
                  buildSeconds=time.perf_counter()-started, foliageScale=build.FOLIAGE_SCALE, variants=rows,
                  validation=dict(woodUnchanged=True, closedFoliage=True, finiteNondegenerateTriangles=True),
                  scope='One-tree geometry experiment; no city integration or render speed claim.')
    (build.OUT/'optimization.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
