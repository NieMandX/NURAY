#!/usr/bin/env python3
"""Check configured delivery objects, CORS and sampled byte integrity before Pages deployment."""
import argparse
import hashlib
import json
from pathlib import Path
from urllib.parse import urljoin
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]


def verify(config, require_cache=False):
    results = []
    for catalog, delivery in config.get('assetDelivery', {}).items():
        base = urljoin(config['assetBase'], catalog)
        for kind in ('catalog', 'validation', 'merged', 'mergedBuffer'):
            spec = delivery.get(kind)
            if not spec:
                continue
            url = urljoin(base, spec['url'])
            headers = {'Origin': 'https://niemandx.github.io'}
            with urlopen(Request(url, method='HEAD', headers=headers), timeout=60) as response:
                h = response.headers
                if int(h.get('Content-Length', -1)) != spec['bytes']:
                    raise ValueError(f'{url}: incorrect size')
                if h.get('Content-Encoding'):
                    raise ValueError(f'{url}: must not have HTTP Content-Encoding')
                if h.get('Access-Control-Allow-Origin') not in ('*', headers['Origin']):
                    raise ValueError(f'{url}: missing CORS')
                cache = h.get('Cache-Control', '')
                if require_cache and 'max-age=31536000' not in cache:
                    raise ValueError(f'{url}: missing immutable cache policy')
            proofs = spec.get('rangeProofs', [])
            if not proofs:
                raise ValueError(f'{url}: no verification ranges')
            for proof in proofs:
                start = proof['offset']; end = start + proof['bytes'] - 1
                with urlopen(Request(url, headers={**headers, 'Range': f'bytes={start}-{end}'}), timeout=60) as response:
                    if response.status != 206 or response.headers.get('Content-Range') != f'bytes {start}-{end}/{spec["bytes"]}':
                        raise ValueError(f'{url}: invalid Range response')
                    data = response.read(proof['bytes'] + 1)
                    if len(data) != proof['bytes'] or hashlib.sha256(data).hexdigest() != proof['sha256']:
                        raise ValueError(f'{url}: range checksum mismatch')
            results.append({'url': url, 'bytes': spec['bytes'], 'ranges': len(proofs), 'cacheControl': cache})
    return results


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=ROOT/'moscow-fidelity/web-preview/prototype/tiles/config.json')
    parser.add_argument('--require-cache', action='store_true')
    args = parser.parse_args()
    print(json.dumps({'verified': verify(json.loads(args.config.read_text()), args.require_cache)}, indent=2))
