"""Apply a distinct light road asphalt to final Parking_area-owned surfaces."""
import argparse, gzip, hashlib, json, os, subprocess, sys
from collections import defaultdict
from pathlib import Path
import ijson
import numpy as np
import shapely as sh
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from parking_cover import LAYER, POLICY, BRIGHTNESS, material, owns_surface
from semantics import classify
from material_remap import remap
from object_geometry import export_glb
from prepare_cemetery_cover import save, digest, raw, choose_faces, assert_appearance_only


def select(base, cache):
    signature = digest(base/'objects.json.gz')
    if cache.exists():
        result = json.loads(cache.read_text())
        if result.get('baseRegistrySha256') == signature:
            return result
    print('SELECT PARKING SOURCE OWNERS', flush=True)
    with gzip.open(base/'objects.json.gz', 'rb') as f:
        features = [r for r in ijson.items(f, 'features.item', use_float=True) if r['layer'] == LAYER]
    owners = {r['id'] for r in features}
    print('SELECT FINAL PARKING CELLS', len(owners), flush=True)
    with gzip.open(base/'objects.json.gz', 'rb') as f:
        surfaces = [s for s in ijson.items(f, 'surfaces.item', use_float=True) if owns_surface(s, owners)]
    result = dict(baseRegistrySha256=signature, features=features, surfaces=surfaces)
    save(cache, result)
    print('PARKING SELECTED', len(features), len(surfaces), flush=True)
    return result


def witness(rows, origin):
    # Choose an actual medium-sized parking surface near the scene centre.
    # This only supplies a review camera; it never affects material selection.
    groups = defaultdict(list)
    for row in rows:
        groups[row['owner']].append(row)
    areas = {key: sum(sh.geometry.shape(s['geometry']).area for s in value) for key, value in groups.items()}
    candidates = [key for key, area in areas.items() if 1500 < area < 6000] or list(groups)
    key = min(candidates, key=lambda key: sh.geometry.shape(groups[key][0]['geometry']).distance(sh.Point(origin[:2])))
    poly = sh.union_all([sh.geometry.shape(s['geometry']) for s in groups[key]])
    point = poly.representative_point()
    cell = next(s for s in groups[key] if sh.geometry.shape(s['geometry']).covers(point))
    z = float(np.dot(cell['heightPlane'], [point.x, point.y, 1]))
    span = max(poly.bounds[2]-poly.bounds[0], poly.bounds[3]-poly.bounds[1])
    return dict(yaw=-.4, pitch=1.15, distance=max(110., span*1.7),
                target=[point.x-origin[0], z-origin[2], origin[1]-point.y])


def previous_selection(base, scene):
    """Reuse verified face ownership only through unchanged canonical land.

    Follow hash-linked approvals to its original parking revision, then check
    both the selection and all affected chunks. Never infer parking from the
    shared asphalt material, which also belongs to motor roads.
    """
    patch_path = base/'parking-material-patch.json'
    patch = json.loads(patch_path.read_text())
    owner = base; seen = set()
    while True:
        assert owner not in seen; seen.add(owner)
        validation = json.loads((owner/'validation.json').read_text())
        assert validation['passed']
        rev = validation['geometryRevision']
        if rev['type'] == 'parking-material': break
        parent = owner.parent/rev['parent']
        assert digest(parent/'validation.json') == rev['parentValidationSha256']
        owner = parent
    assert digest(owner/'parking-material-patch.json') == digest(patch_path)
    proof = json.loads((owner/'parking-material-proof.json').read_text()); assert proof['passed']
    approved = json.loads((owner/'canonical/full/scene.json').read_text())
    old_chunks = {c['id']:c for c in approved['chunks']}
    for c in scene['chunks']:
        if str(c['id']) not in patch['canonicalFaces']: continue
        assert c == old_chunks[c['id']] and c['name'] == 'land'
        assert digest(base/'canonical/full'/Path(c['file']).name) == digest(owner/'canonical/full'/Path(c['file']).name)
    return patch, proof, owner.name


def verify_revision(root, city, scene):
    rev = city['geometryRevision']; parent = root.parent/rev['parent']
    assert digest(parent/'validation.json') == rev['parentValidationSha256']
    assert json.loads((parent/'validation.json').read_text())['passed']
    old = json.loads((parent/'canonical/full/scene.json').read_text())
    patch = json.loads((root/'parking-material-patch.json').read_text())
    mid = patch['material']
    if rev.get('version',1) == 1:
        assert mid == 0 and scene['materials'] == old['materials']
    else:
        assert mid == len(old['materials'])
        assert scene['materials'] == old['materials']+[material(old['materials'][0])]
    assert scene['textures'] == old['textures']
    assert scene['instances'] == old['instances'] and scene['stats'] == old['stats']
    assert len(scene['chunks']) == len(old['chunks'])
    changes = {int(k): np.asarray(v, dtype=int) for k, v in patch['canonicalFaces'].items()}
    for a, b in zip(old['chunks'], scene['chunks']):
        if a['id'] not in changes:
            assert a == b and digest(parent/'canonical/full'/Path(a['file']).name) == digest(root/'canonical/full'/Path(b['file']).name)
            continue
        selected = np.zeros(a['triangles'], bool); selected[changes[a['id']]] = True
        assert a['name'] == 'land'
        assert_appearance_only(raw(parent, a, True), raw(root, b, True), a, b, selected, mid, True)
    old_tiles = json.loads((parent/'tileset.json').read_text()); tiles = json.loads((root/'tileset.json').read_text())
    assert tiles['tiles'] == old_tiles['tiles'] and tiles['sourceChunks'] == old_tiles['sourceChunks']
    assert tiles['materials'] == scene['materials'] and tiles['textures'] == old_tiles['textures']
    assert len(tiles['chunks']) == len(old_tiles['chunks'])
    touched = []; faces = 0
    for a, b in zip(old_tiles['chunks'], tiles['chunks']):
        if a == b:
            assert digest(parent/a['file']) == digest(root/b['file']); continue
        assert a['sourceChunk'] in changes and a['name'] == 'land'
        data = raw(parent, a); lineage = np.frombuffer(data[-a['lineageBytes']:], '<u4')
        selected = np.isin(lineage, changes[a['sourceChunk']]); assert selected.any()
        after = raw(root, b)
        assert hashlib.sha256(after).hexdigest() == b['sha256']
        assert (root/b['file']).stat().st_size == b['downloadBytes']
        assert_appearance_only(data, after, a, b, selected, mid, False)
        touched.append(a['tileId']); faces += int(selected.sum())
    return dict(passed=True, type='parking-material', changedTiles=len(set(touched)),
                changedTileChunks=len(touched), recoloredTriangles=faces,
                geometryCornersBitIdentical=True, bvhAndLineageBitIdentical=True,
                allOtherMeshesBitIdentical=True, existingMaterialsUnchanged=True,
                sameMaterialAsRoad=mid == 0, material=mid,
                roadMaterialUnchanged=scene['materials'][0] == old['materials'][0],
                linearAlbedoFactor=1. if mid == 0 else BRIGHTNESS,
                inheritedParent=parent.name, policy=rev['policy'])


def main():
    ap = argparse.ArgumentParser()
    for key in ('base', 'output'): ap.add_argument('--'+key, type=Path, required=True)
    ap.add_argument('--selection', type=Path)
    ap.add_argument('--reuse-verified-selection', action='store_true')
    ap.add_argument('--select-only', action='store_true')
    ap.add_argument('--skip-glb', action='store_true')
    a = ap.parse_args()
    parent_validation = json.loads((a.base/'validation.json').read_text()); assert parent_validation['passed']
    if not a.reuse_verified_selection:
        assert a.selection is not None
        selected = select(a.base, a.selection)
        if a.select_only: return
    assert not a.output.exists() and a.base.parent == a.output.parent
    scene = json.loads((a.base/'canonical/full/scene.json').read_text())
    tiles = json.loads((a.base/'tileset.json').read_text())
    report = json.loads((a.base/'canonical/validation.json').read_text())
    metadata = json.loads((a.base/'canonical/transport-metadata.json').read_text())
    previous = previous_selection(a.base,scene) if a.reuse_verified_selection else None
    mid = len(scene['materials']); scene['materials'].append(material(scene['materials'][0]))
    tiles['materials'] = scene['materials']
    rev = dict(type='parking-material', version=2, parent=a.base.name,
               parentValidationSha256=digest(a.base/'validation.json'),
               previousRevision=parent_validation.get('geometryRevision'), policy=POLICY)
    patch = dict(material=mid, features=[], surfaces=[], geometryRevision=rev, canonicalFaces={})
    if previous:
        inherited, inherited_proof, owner = previous
        patch['features'] = inherited['features']; patch['surfaces'] = inherited['surfaces']
        patch['selectionFrom'] = owner
    else:
        rows = selected['surfaces']; assert rows
        patch['features'] = [dict(id=f['id'],semantics=classify(LAYER,f['properties'],'polygon')) for f in selected['features']]
        patch['surfaces'] = [dict(id=s['id'],surfaceType='asphalt',styleId=None) for s in rows]
    for f in patch['features']: f['semantics'].update(material=mid,rule='parking-material-v2')
    for s in patch['surfaces']: s['material'] = mid
    patch['objectLayerUpdate'] = dict(stats=dict(materials=len(scene['materials'])))
    for item in (tiles['objectLayer'],metadata['objectLayer']):
        item['stats']['materials'] = len(scene['materials'])
    tiles['stats']['objectLayer']['materials'] = len(scene['materials'])
    subprocess.run(['/bin/cp', '-cR', str(a.base), str(a.output)], check=True)
    # Discard only stale exports/approval in the new clone, keeping R9 intact.
    for relative in ('validation.json', 'canonical/full/model.glb', 'merged/model.glb',
                     'merged/metadata.json', 'merged/validation.json', 'merged/benchmark.json'):
        (a.output/relative).unlink(missing_ok=True)
    area = 0.; escapes = 0.
    for c in scene['chunks']:
        if c['name'] != 'land': continue
        print('CHECK PARKING CHUNK', c['id'], flush=True)
        data = raw(a.base, c, True)
        if previous:
            flags = np.zeros(c['triangles'],bool)
            flags[inherited['canonicalFaces'].get(str(c['id']),[])] = True
            cover = escape = 0.
        else:
            flags, cover, escape = choose_faces(data, c, np.asarray(scene['origin']), rows)
        if not flags.any(): continue
        area += cover; escapes = max(escapes, escape)
        patch['canonicalFaces'][str(c['id'])] = np.flatnonzero(flags).tolist()
        updated, vb, _ = remap(data, c['vertexBytes'], c['triangles']*12, flags, mid)
        (a.output/'canonical/full'/Path(c['file']).name).write_bytes(gzip.compress(updated, compresslevel=6, mtime=0))
        c.update(vertexBytes=vb, vertexCount=vb//32)
        print('PARKING CANONICAL', c['id'], int(flags.sum()), flush=True)
    if previous:
        area = inherited_proof['coveredAreaM2']; expected = inherited_proof['expectedAreaM2']
        escapes = inherited_proof['maxEscapedTriangleAreaM2']
    else:
        expected = sum(sh.geometry.shape(s['geometry']).area for s in rows)
    assert abs(area-expected) < max(.02, expected*1e-6), (area, expected)
    for c in tiles['chunks']:
        ids = patch['canonicalFaces'].get(str(c['sourceChunk']))
        if ids is None: continue
        data = raw(a.base, c); lineage = np.frombuffer(data[-c['lineageBytes']:], '<u4')
        flags = np.isin(lineage, ids)
        if not flags.any(): continue
        updated, vb, _ = remap(data, c['vertexBytes'], c['indexBytes'], flags, mid)
        signature = hashlib.sha256(updated).hexdigest(); file = f'meshes/{signature}.bin.gz'
        encoded = gzip.compress(updated, compresslevel=6, mtime=0); (a.output/file).write_bytes(encoded)
        c.update(vertexBytes=vb, vertexCount=vb//32, file=file, sha256=signature, downloadBytes=len(encoded))
    files = {c['file'] for c in tiles['chunks']}
    for p in (a.output/'meshes').iterdir():
        if 'meshes/'+p.name not in files: p.unlink()
    for key, ids in [('fullDownloadBytes', {c for t in tiles['tiles'] for c in t['chunks']}),
                     ('coarseDownloadBytes', {c for t in tiles['tiles'] for c in t['coarseChunks']})]:
        ids |= {i['mesh'] for t in tiles['tiles'] for i in t['instances']}
        tiles['stats'][key] = sum(c['downloadBytes'] for c in tiles['chunks'] if c['id'] in ids)
    if not previous:
        tiles.setdefault('witnessViews', {})['parking-asphalt-review'] = witness(rows, scene['origin'])
    tiles['geometryRevision'] = rev
    save(a.output/'canonical/full/scene.json', scene); save(a.output/'tileset.json', tiles)
    save(a.output/'canonical/transport-metadata.json',metadata)
    save(a.output/'parking-material-patch.json', patch)
    print('VERIFY PARKING APPEARANCE', flush=True)
    proof = verify_revision(a.output, {'geometryRevision': rev}, scene)
    proof.update(sourceFeatures=len(patch['features']), surfaceCells=len(patch['surfaces']),
                 coveredAreaM2=area, expectedAreaM2=expected, maxEscapedTriangleAreaM2=escapes)
    save(a.output/'parking-material-proof.json', proof)
    for name in ('canonical/urban-model.json.gz', 'objects.json.gz'):
        subprocess.run([os.environ.get('NODE', 'node'), str(Path(__file__).with_name('restyle_registry.mjs')),
                        str(a.base/name), str(a.output/name), str(a.output/'parking-material-patch.json')], check=True)
    if not a.skip_glb:
        print('EXPORT CANONICAL GLB', flush=True); export_glb(scene, a.output/'canonical/full')
    report['geometryRevision'] = rev; report['parkingMaterial'] = proof
    report['objectLayer']['materials'] = len(scene['materials'])
    report['export']['objectLayer']['materials'] = len(scene['materials'])
    report['export']['glbBytes'] = (a.output/'canonical/full/model.glb').stat().st_size if not a.skip_glb else 0
    report['export']['downloadBytes'] = sum((a.output/'canonical/full'/Path(c['file']).name).stat().st_size for c in scene['chunks'])
    save(a.output/'canonical/validation.json', report)
    parent_validation.update(geometryRevision=rev, parkingMaterial=proof)
    parent_validation['objectLayer']['materials'] = len(scene['materials'])
    save(a.output/'validation.json', parent_validation)
    print('PARKING MATERIAL PASSED', json.dumps(proof), flush=True)


if __name__ == '__main__': main()
