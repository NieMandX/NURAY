#!/usr/bin/env python3
"""Package a flat tile catalog and matching splats for immutable cloud delivery.

No geometry is rebuilt. Only catalog-referenced meshes enter the byte-range pack;
private canonical inputs, placement masks and survey data stay off public storage.
"""
import argparse
import hashlib
import json
from pathlib import Path
from prepare_delivery import digest


def prepare(root, splats, manifest):
    catalog = json.loads((root / 'tileset.json').read_text())
    validation = json.loads((root / 'validation.json').read_text())
    merged = json.loads((root / 'merged/validation.json').read_text())
    if not validation.get('passed') or not merged.get('passed'):
        raise ValueError('Only validated scenes may be published')
    chunks = {c['file']: c for c in catalog['chunks']}
    pack = root / 'meshes.pack'
    index = {'version': 1, 'url': 'meshes.pack', 'bytes': 0, 'entries': {}}
    rows = []
    h = hashlib.sha256()
    with pack.open('xb') as out:
        for name, c in sorted(chunks.items()):
            p = root / name
            if p.resolve().parent != (root / 'meshes').resolve():
                raise ValueError('Unexpected mesh path')
            data = p.read_bytes()
            if len(data) != c['downloadBytes']:
                raise ValueError('Unexpected mesh size: ' + name)
            offset = out.tell()
            out.write(data)
            h.update(data)
            index['entries'][name] = [offset, len(data)]
            rows.append({'path': root.name + '/' + name, 'bytes': len(data),
                         'sha256': hashlib.sha256(data).hexdigest(),
                         'pack': {'path': root.name + '/meshes.pack', 'offset': offset}})
        index['bytes'] = out.tell()
    (root / 'mesh-pack.json').write_text(json.dumps(index, separators=(',', ':')) + '\n')
    paths = {'tileset.json', 'validation.json', 'mesh-pack.json',
             'merged/metadata.json', 'merged/visibility.json', 'merged/validation.json'}
    for folder in ('delivery-20261113-v1', 'textures', 'merged/trace'):
        paths.update(p.relative_to(root).as_posix() for p in (root / folder).rglob('*') if p.is_file())
    for name in sorted(paths):
        p = root / name
        rows.append({'path': root.name + '/' + name, 'bytes': p.stat().st_size, 'sha256': digest(p)})
    for p in sorted(splats.iterdir()):
        if p.is_file() and p.suffix in ('.json', '.gsbin'):
            rows.append({'path': splats.name + '/' + p.name, 'bytes': p.stat().st_size, 'sha256': digest(p)})
    result = {'version': 1, 'baseURL': 'https://storage.yandexcloud.net/nuray-assets-niemandx/',
              'release': root.name, 'splatRelease': splats.name, 'totalTiles': len(catalog['tiles']),
              'geometryChanged': False, 'files': rows,
              'packs': [{'path': root.name + '/meshes.pack', 'bytes': index['bytes'], 'sha256': h.hexdigest()}]}
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps(result, separators=(',', ':')) + '\n')
    objects = [r for r in rows if 'pack' not in r] + result['packs']
    print(json.dumps({'objects': len(objects), 'bytes': sum(r['bytes'] for r in objects),
                      'packedMeshes': len(chunks), 'packBytes': index['bytes']}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path)
    parser.add_argument('--splats', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    args = parser.parse_args()
    prepare(args.root, args.splats, args.manifest)
