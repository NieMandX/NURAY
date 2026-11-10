#!/usr/bin/env python3
"""Split runtime metadata for manual area loading; never touch city geometry."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path


def intersects(a, b):
    return a[0] < b[2] and a[2] > b[0] and a[1] < b[3] and a[3] > b[1]


def prepare(root, center, size=3000, output='sectors-v1'):
    root = Path(root)
    source = root / 'tileset.json'
    data = json.loads(source.read_text())
    out = root / output
    out.mkdir(exist_ok=True)
    if any(out.iterdir()):
        raise ValueError('Use a new versioned output directory')
    assets = {c['id']: c for c in data['chunks']}
    initial_bounds = [center[0]-size/2, center[1]-size/2,
                      center[0]+size/2, center[1]+size/2]
    initial = [t['id'] for t in data['tiles'] if intersects(t['boundsMSK'], initial_bounds)]
    groups = {}
    for t in data['tiles']:
        key = f"{t['east']//4}-{t['north']//4}"
        groups.setdefault(key, []).append(t)
    shared_ids = {i['mesh'] for t in data['tiles'] for i in t.get('instances', [])}
    # Only metadata needed by the viewer. Full provenance remains at tileset.json.
    keys = ('version', 'format', 'name', 'regionName', 'crsProj', 'extentMetres',
            'tileSizeM', 'grid', 'origin', 'axes', 'boundsMSK', 'materials', 'textures',
            'geography', 'witnessViews', 'sourceSnapshot')
    index = {k: data[k] for k in keys if k in data}
    index['chunks'] = [c for c in data['chunks'] if c['id'] in shared_ids]
    index['tiles'] = [{**{k: t[k] for k in ('id', 'east', 'north', 'boundsMSK', 'bounds', 'contentBounds') if k in t},
                       'chunks': [], 'coarseChunks': [], 'instances': []} for t in data['tiles']]
    shards = []
    for key, tiles in sorted(groups.items()):
        ids = {c for t in tiles for c in t['chunks'] + t['coarseChunks']} - shared_ids
        payload = {'tiles': tiles, 'chunks': [assets[i] for i in sorted(ids)]}
        raw = json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode()
        packed = gzip.compress(raw, compresslevel=6, mtime=0)
        sha = hashlib.sha256(raw).hexdigest()
        name = f'{key}-{sha[:12]}.json.gz'
        (out / name).write_bytes(packed)
        assert json.loads(gzip.decompress(packed)) == payload
        # Every tile/chunk/instance is copied exactly, including materials,
        # transforms, bounds, source identity, content hashes and relative URLs.
        bounds = [min(t['boundsMSK'][i] for t in tiles) if i < 2 else max(t['boundsMSK'][i] for t in tiles) for i in range(4)]
        shards.append({'id': key, 'east': tiles[0]['east']//4, 'north': tiles[0]['north']//4,
                       'boundsMSK': bounds, 'tileIds': [t['id'] for t in tiles],
                       'asset': {'url': f'{output}/{name}', 'encoding': 'gzip', 'bytes': len(packed),
                                 'decodedBytes': len(raw), 'decodedSha256': sha}})
    covered = [t for t in data['tiles'] if t['id'] in initial]
    coverage = [min(t['boundsMSK'][i] for t in covered) if i < 2 else max(t['boundsMSK'][i] for t in covered) for i in range(4)]
    index['manualAreas'] = {'version': 1, 'initial': {'centerMSK': center, 'sizeM': size,
                           'boundsMSK': initial_bounds, 'coverageBoundsMSK': coverage, 'tileIds': initial}, 'shards': shards}
    text = json.dumps(index, ensure_ascii=False, separators=(',', ':')).encode()
    (out / 'index.json').write_bytes(text)
    used = {c for t in covered for c in t['chunks']} | {i['mesh'] for t in covered for i in t.get('instances', [])}
    unique_files = {assets[i]['file']: assets[i]['downloadBytes'] for i in used}
    proof = {'passed': True, 'source': str(source), 'sourceSha256': hashlib.sha256(source.read_bytes()).hexdigest(),
             'tiles': len(data['tiles']), 'shards': len(shards), 'sharedMeshes': len(shared_ids),
             'initialTiles': len(initial), 'initialBoundsMSK': initial_bounds, 'coverageBoundsMSK': coverage,
             'indexBytes': len(text), 'initialMetadataBytes': sum(s['asset']['bytes'] for s in shards if set(s['tileIds']) & set(initial)),
             'initialGeometryDownloadBytes': sum(unique_files.values()),
             'initialGeometryGPUBytes': sum(assets[i]['vertexBytes']+assets[i]['indexBytes'] for i in used),
             'geometryChanged': False}
    assert sum(len(s['tileIds']) for s in shards) == len(data['tiles'])
    assert len({i for s in shards for i in s['tileIds']}) == len(data['tiles'])
    (out / 'proof.json').write_text(json.dumps(proof, ensure_ascii=False, indent=2))
    return proof


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path)
    parser.add_argument('--center', type=float, nargs=2, required=True)
    parser.add_argument('--size', type=float, default=3000)
    parser.add_argument('--output', default='sectors-v1')
    args = parser.parse_args()
    print(json.dumps(prepare(args.root, args.center, args.size, args.output), ensure_ascii=False, indent=2))
