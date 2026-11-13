#!/usr/bin/env python3
"""Create immutable, lossless web-delivery companions without rebuilding geometry.

Keep original files for offline restoration/provenance. Upload the output folder
under the same public release prefix, then enable its descriptor in config.json.
Explicit *.gz objects must NOT have an HTTP Content-Encoding header.
"""
import argparse
import gzip
import hashlib
import json
from pathlib import Path


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for data in iter(lambda: f.read(1024 * 1024), b''):
            h.update(data)
    return h.hexdigest()


def range_proofs(path, sample_bytes=65536):
    size = path.stat().st_size
    length = min(size, sample_bytes)
    offsets = sorted({0, max(0, (size - length) // 2), size - length})
    with path.open('rb') as f:
        result = []
        for offset in offsets:
            f.seek(offset)
            data = f.read(length)
            result.append({'offset': offset, 'bytes': len(data),
                           'sha256': hashlib.sha256(data).hexdigest()})
        return result


def runtime_catalog(catalog):
    # Build provenance is preserved in the original catalog. Keep the actual
    # tiles, instances, material indices, source identity and all other fields.
    return {k: v for k, v in catalog.items() if k not in ('geometryRevision', 'sourceChunks')}


def validation_summary(v):
    if v.get('adapter') == 'yandex-2gis':
        return {k: v[k] for k in ('adapter', 'passed', 'chunks', 'plantInstances') if k in v}
    result = {k: v[k] for k in ('passed', 'meshes') if k in v}
    fields = {'seams': ['maxGapM'], 'roadInterfaces': ['passed', 'interfaces'],
              'roadSeams': ['passed', 'passages'], 'roadPaint': ['passed', 'trianglesChecked']}
    for key, keep in fields.items():
        if key in v:
            result[key] = {k: v[key][k] for k in keep if k in v[key]}
    if 'transportClearance' in v:
        c = v['transportClearance']
        result['transportClearance'] = {'fullWidth': {'passed': c.get('fullWidth', {}).get('passed', False)},
            'source': {'interfaces': c.get('source', {}).get('interfaces', 0),
                       'corridorCount': len(c.get('source', {}).get('corridors', []))}}
    if 'tunnelWalls' in v:
        result['tunnelWalls'] = {'groups': [{k: g[k] for k in
            ('sourceMatchedBoundaryM', 'fallbackBoundaryM', 'portalHeaders') if k in g}
            for g in v['tunnelWalls'].get('groups', [])]}
    return result


def compressed_file(source, target, relative):
    if target.exists():
        raise ValueError(f'Refusing to overwrite delivery file: {target}')
    h = hashlib.sha256()
    temporary = target.with_suffix(target.suffix + '.part')
    try:
        with source.open('rb') as f, temporary.open('wb') as raw:
            with gzip.GzipFile(filename='', mode='wb', fileobj=raw, compresslevel=1, mtime=0) as z:
                for data in iter(lambda: f.read(1024 * 1024), b''):
                    h.update(data)
                    z.write(data)
        # Verify the entire decompressed stream before publishing its descriptor.
        verified = hashlib.sha256()
        with gzip.open(temporary, 'rb') as f:
            for data in iter(lambda: f.read(1024 * 1024), b''):
                verified.update(data)
        if verified.digest() != h.digest():
            raise ValueError('Lossless round-trip failed')
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    return {'url': relative, 'encoding': 'gzip', 'bytes': target.stat().st_size,
            'sha256': digest(target), 'decodedBytes': source.stat().st_size, 'decodedSha256': h.hexdigest(),
            'rangeProofs': range_proofs(target)}


def prepare(source, output):
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise ValueError('Use a new empty versioned delivery directory')
    prefix = output.name + '/'
    original = source / 'tileset.json'
    catalog = json.loads(original.read_text())
    compact = output / 'tileset-runtime.json'
    compact.write_text(json.dumps(runtime_catalog(catalog), ensure_ascii=False, separators=(',', ':')))
    descriptor = {'version': 1, 'sourceCatalogSha256': digest(original),
                  'excludedBuildFields': ['geometryRevision', 'sourceChunks']}
    descriptor['catalog'] = compressed_file(compact, output / 'tileset-runtime.json.gz', prefix + 'tileset-runtime.json.gz')
    compact.unlink()
    original_validation = source / 'validation.json'
    if original_validation.exists():
        compact = output / 'validation-summary.json'
        compact.write_text(json.dumps(validation_summary(json.loads(original_validation.read_text())), separators=(',', ':')))
        descriptor['validation'] = compressed_file(compact, output / 'validation-summary.json.gz', prefix + 'validation-summary.json.gz')
        compact.unlink()
    print(json.dumps({'catalog': descriptor['catalog']}, ensure_ascii=False), flush=True)
    metadata_path = source / 'merged/metadata.json'
    asset = json.loads(metadata_path.read_text()).get('asset', {}) if metadata_path.exists() else {}
    filename = asset.get('file', 'model.glb')
    if filename not in ('model.glb', 'model.gltf'):
        raise ValueError('Unsupported merged scene container')
    descriptor['merged'] = compressed_file(source / ('merged/' + filename), output / (filename + '.gz'), prefix + filename + '.gz')
    if filename == 'model.gltf':
        descriptor['mergedBuffer'] = compressed_file(source / 'merged/model.bin', output / 'model.bin.gz', prefix + 'model.bin.gz')
    (output / 'delivery.json').write_text(json.dumps(descriptor, indent=2) + '\n')
    print(json.dumps(descriptor, ensure_ascii=False), flush=True)
    return descriptor


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', required=True, type=Path)
    p.add_argument('--output', required=True, type=Path)
    args = p.parse_args()
    prepare(args.source, args.output)
