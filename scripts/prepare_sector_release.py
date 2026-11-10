#!/usr/bin/env python3
"""Package an existing sector catalog for immutable cloud delivery, without rebuilding geometry."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(8 << 20), b''): h.update(block)
    return h.hexdigest()


def prepare(root, manifest):
    index = json.loads((root/'sectors-v1/index.json').read_text())
    chunks = {c['file']: c for c in index['chunks']}
    initial = set(index['manualAreas']['initial']['tileIds'])
    shards = sorted(index['manualAreas']['shards'], key=lambda s: (not bool(initial.intersection(s['tileIds'])), s['north'], s['east']))
    for shard in shards:
        data = json.loads(gzip.decompress((root/shard['asset']['url']).read_bytes()))
        for c in data['chunks']: chunks.setdefault(c['file'], c)
    pack = root/'meshes.pack'
    pack_index = {'version': 1, 'url': 'meshes.pack', 'bytes': 0, 'entries': {}}
    rows = []
    if pack.exists(): raise ValueError('Pack already exists; use the recorded manifest, never overwrite a release')
    h = hashlib.sha256()
    with pack.open('xb') as out:
        for name, c in chunks.items():
            data = (root/name).read_bytes()
            if len(data) != c['downloadBytes']: raise ValueError('Unexpected mesh size: '+name)
            offset = out.tell(); out.write(data); h.update(data)
            pack_index['entries'][name] = [offset, len(data)]
            rows.append({'path': root.name+'/'+name, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
                         'pack': {'path': root.name+'/meshes.pack', 'offset': offset}})
        pack_index['bytes'] = out.tell()
    (root/'mesh-pack.json').write_text(json.dumps(pack_index,separators=(',', ':'))+'\n')
    paths = {'tileset.json', 'surface-effects.json', 'mesh-pack.json',
             'merged/model.gltf', 'merged/metadata.json', 'merged/visibility.json', 'merged/validation.json'}
    surface = json.loads((root/'surface-effects.json').read_text())
    for p in root.glob('surface-effects-*.bin.gz'): paths.add(p.name)
    for folder in ('sectors-v1','delivery-20261108-v1','textures','merged/trace'):
        paths.update(p.relative_to(root).as_posix() for p in (root/folder).rglob('*') if p.is_file())
    for name in sorted(paths):
        p = root/name
        rows.append({'path': root.name+'/'+name, 'bytes': p.stat().st_size, 'sha256': digest(p)})
    m = {'version':1, 'baseURL':'https://storage.yandexcloud.net/nuray-assets-niemandx/',
         'release':root.name, 'initialTiles':len(initial), 'totalTiles':len(index['tiles']),
         'geometryChanged':False, 'files':rows,
         'packs':[{'path':root.name+'/meshes.pack','bytes':pack_index['bytes'],'sha256':h.hexdigest()}]}
    manifest.parent.mkdir(parents=True,exist_ok=True)
    manifest.write_text(json.dumps(m,separators=(',', ':'))+'\n')
    objects = [r for r in rows if 'pack' not in r]+m['packs']
    print(json.dumps({'objects':len(objects),'bytes':sum(r['bytes'] for r in objects),'packBytes':pack_index['bytes'],'packedMeshes':len(chunks),'manifest':str(manifest)}),flush=True)


if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('root',type=Path);p.add_argument('--manifest',type=Path,required=True)
    a=p.parse_args();prepare(a.root,a.manifest)
