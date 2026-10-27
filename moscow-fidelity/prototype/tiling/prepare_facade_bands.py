"""Incremental ordinary-facade appearance revision, preserving city geometry."""
import argparse, gzip, hashlib, json, os, subprocess, shutil
from pathlib import Path
import numpy as np
from facade_bands import install, select_faces, apply_faces, building_bases, make_material, POLICY, TEXTURE
from prepare_cemetery_cover import save, digest, raw
from object_geometry import export_glb


def verify_revision(root, city, scene):
    rev = city['geometryRevision']; parent = root.parent / rev['parent']
    assert digest(parent/'validation.json') == rev['parentValidationSha256']
    assert json.loads((parent/'validation.json').read_text())['passed']
    old = json.loads((parent/'canonical/full/scene.json').read_text())
    rows = json.loads((root/'facade-input.json').read_text())
    patch = json.loads((root/'facade-patch.json').read_text()); mid = patch['material']
    body = [i for i,m in enumerate(old['materials']) if m.get('family') == 'Buildings' and not m.get('texture')]
    assert scene['materials'] == old['materials'] + [make_material(old['materials'][body[0]])]
    assert scene['instances'] == old['instances'] and scene['stats'] == old['stats']
    assert {k:v for k,v in scene['textures'].items() if k != TEXTURE} == old['textures']
    assert digest(root/'textures'/TEXTURE) == scene['textures'][TEXTURE]['sha256']
    bases = building_bases(rows, old['origin']); labels = {}; triangles = 0
    assert len(old['chunks']) == len(scene['chunks'])
    for a,b in zip(old['chunks'],scene['chunks']):
        data = raw(parent,a,True) if a.get('category') == 'building' else None
        phase = select_faces(data,a,bases,body) if data is not None else np.full(a['triangles'],np.nan)
        if not np.isfinite(phase).any():
            assert a == b and digest(parent/'canonical/full'/Path(a['file']).name) == digest(root/'canonical/full'/Path(b['file']).name)
            continue
        labels[a['id']] = phase; triangles += int(np.isfinite(phase).sum())
        expected,vb = apply_faces(data,a['vertexBytes'],a['triangles']*12,phase,mid)
        assert raw(root,b,True) == expected and b['vertexBytes'] == vb
        assert {k:v for k,v in a.items() if k not in ('vertexBytes','vertexCount')} == {k:v for k,v in b.items() if k not in ('vertexBytes','vertexCount')}
    before = json.loads((parent/'tileset.json').read_text()); after = json.loads((root/'tileset.json').read_text())
    assert before['tiles'] == after['tiles'] and before['sourceChunks'] == after['sourceChunks']
    assert len(before['chunks']) == len(after['chunks']) and after['materials'] == scene['materials']
    assert after['textures'] == scene['textures']
    touched = []; packed = 0
    for a,b in zip(before['chunks'],after['chunks']):
        if a == b:
            assert digest(parent/a['file']) == digest(root/b['file']); continue
        assert a['sourceChunk'] in labels
        data = raw(parent,a); lineage = np.frombuffer(data[-a['lineageBytes']:],'<u4')
        phase = labels[a['sourceChunk']][lineage]; assert np.isfinite(phase).any()
        expected,vb = apply_faces(data,a['vertexBytes'],a['indexBytes'],phase,mid)
        assert raw(root,b) == expected and b['vertexBytes'] == vb
        assert hashlib.sha256(expected).hexdigest() == b['sha256'] and (root/b['file']).stat().st_size == b['downloadBytes']
        allowed = {'vertexBytes','vertexCount','file','sha256','downloadBytes'}
        assert {k:v for k,v in a.items() if k not in allowed} == {k:v for k,v in b.items() if k not in allowed}
        touched.append(a['tileId']); packed += int(np.isfinite(phase).sum())
    assert digest(parent/'canonical/terrain.npz') == digest(root/'canonical/terrain.npz')
    for name in old['textures']:
        assert digest(parent/'textures'/name) == digest(root/'textures'/name)
    return dict(passed=True, type='facade-bands', **patch['facadeStats'], changedTiles=len(set(touched)),
                changedTileChunks=len(touched), packedTriangles=packed,
                positionsNormalsTintAndTriangleOrderBitIdentical=True, bvhAndLineageBitIdentical=True,
                roofsAndLandmarksBitIdentical=True, allExistingMaterialsUnchanged=True,
                geometryAndInstancesUnchanged=True, policy=POLICY)


def main():
    ap = argparse.ArgumentParser()
    for k in ('base','output','buildings'): ap.add_argument('--'+k,type=Path,required=True)
    ap.add_argument('--skip-glb',action='store_true',help='Do not write the optional unmerged GLB; merged export is separate')
    a = ap.parse_args(); assert not a.output.exists() and a.base.parent == a.output.parent
    validation = json.loads((a.base/'validation.json').read_text()); assert validation['passed']
    scene = json.loads((a.base/'canonical/full/scene.json').read_text())
    tiles = json.loads((a.base/'tileset.json').read_text()); rows = json.loads(a.buildings.read_text())
    report = json.loads((a.base/'canonical/validation.json').read_text())
    metadata = json.loads((a.base/'canonical/transport-metadata.json').read_text())
    subprocess.run(['/bin/cp','-cR',str(a.base),str(a.output)],check=True)
    for relative in ('validation.json','canonical/full/model.glb','merged/model.glb','merged/metadata.json','merged/validation.json','merged/benchmark.json'):
        (a.output/relative).unlink(missing_ok=True)
    save(a.output/'facade-input.json',rows)
    folder = a.output/'canonical/full'; result = install(rows,scene,folder)
    labels = result['labels']; mid = result['material']; print('FACADES',json.dumps(result['stats']),flush=True)
    shutil.copy2(folder/TEXTURE,a.output/'textures'/TEXTURE)
    rev = dict(type='facade-bands',version=1,parent=a.base.name,parentValidationSha256=digest(a.base/'validation.json'),
               previousRevision=validation['geometryRevision'],policy=POLICY)
    layer = {k:result[k] for k in ('material','policy','stats')}
    patch = dict(features=[],surfaces=[],geometryRevision=rev,material=mid,facadeStats=result['stats'],
                 objectLayerUpdate=dict(buildings=result['buildings'],stats=dict(materials=len(scene['materials'])),facades=layer))
    tiles['materials'] = scene['materials']; tiles['textures'] = scene['textures']; tiles['geometryRevision'] = rev
    for item in (tiles['objectLayer'],metadata['objectLayer']):
        item['facades'] = layer; item['stats']['materials'] = len(scene['materials'])
    tiles['stats']['objectLayer']['materials'] = len(scene['materials'])
    for c in tiles['chunks']:
        if c['sourceChunk'] not in labels: continue
        data = raw(a.base,c); lineage = np.frombuffer(data[-c['lineageBytes']:],'<u4'); phase = labels[c['sourceChunk']][lineage]
        if not np.isfinite(phase).any(): continue
        updated,vb = apply_faces(data,c['vertexBytes'],c['indexBytes'],phase,mid)
        signature = hashlib.sha256(updated).hexdigest(); file = f'meshes/{signature}.bin.gz'
        encoded = gzip.compress(updated,compresslevel=6,mtime=0); (a.output/file).write_bytes(encoded)
        c.update(vertexBytes=vb,vertexCount=vb//32,file=file,sha256=signature,downloadBytes=len(encoded))
    files = {c['file'] for c in tiles['chunks']}
    for p in (a.output/'meshes').iterdir():
        if 'meshes/'+p.name not in files: p.unlink()
    for key,ids in [('fullDownloadBytes',{c for t in tiles['tiles'] for c in t['chunks']}),('coarseDownloadBytes',{c for t in tiles['tiles'] for c in t['coarseChunks']})]:
        ids |= {i['mesh'] for t in tiles['tiles'] for i in t['instances']}
        tiles['stats'][key] = sum(c['downloadBytes'] for c in tiles['chunks'] if c['id'] in ids)
    camera = dict(tiles['witnessViews']['flat-roof-review']); camera.update(pitch=.55)
    tiles['witnessViews']['facade-bands-review'] = camera
    save(folder/'scene.json',scene); save(a.output/'tileset.json',tiles)
    save(a.output/'canonical/transport-metadata.json',metadata); save(a.output/'facade-patch.json',patch)
    print('VERIFY FACADES',flush=True)
    proof = verify_revision(a.output,{'geometryRevision':rev},scene); save(a.output/'facade-proof.json',proof)
    for name in ('canonical/urban-model.json.gz','objects.json.gz'):
        subprocess.run([os.environ.get('NODE','node'),str(Path(__file__).with_name('restyle_registry.mjs')),
                        str(a.base/name),str(a.output/name),str(a.output/'facade-patch.json')],check=True)
    if not a.skip_glb:
        print('EXPORT CANONICAL GLB',flush=True); export_glb(scene,folder)
    report['geometryRevision'] = rev; report['facades'] = proof
    report['objectLayer']['materials'] = len(scene['materials']); report['export']['objectLayer']['materials'] = len(scene['materials'])
    report['export']['glbBytes'] = (folder/'model.glb').stat().st_size if (folder/'model.glb').exists() else 0
    report['export']['downloadBytes'] = sum((folder/Path(c['file']).name).stat().st_size for c in scene['chunks'])
    save(a.output/'canonical/validation.json',report)
    validation.update(geometryRevision=rev,facades=proof); validation['objectLayer']['materials'] = len(scene['materials'])
    save(a.output/'validation.json',validation)
    print('FACADES PASSED',json.dumps(proof),flush=True)


if __name__ == '__main__': main()
