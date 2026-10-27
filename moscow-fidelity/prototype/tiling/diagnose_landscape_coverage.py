"""Reproduce the exported paving audit and retain exact geometry witnesses."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path

import numpy as np
import shapely as sh


def polygons(g):
    if g.is_empty:
        return []
    if g.geom_type == 'Polygon':
        return [g]
    return [p for child in getattr(g, 'geoms', []) for p in polygons(child)]


def diagnose(root, output):
    output.mkdir(parents=True, exist_ok=True)
    scene_path = root/'canonical/full/scene.json'
    report_path = root/'canonical/validation.json'
    scene = json.loads(scene_path.read_text())
    report = json.loads(report_path.read_text())
    revision = report['geometryRevision']
    assert revision['type'] == 'landscape'
    preserved = {r['id'] for r in revision['preservedChunks']}
    added = set(revision['newChunks'])
    origin = np.asarray(scene['origin'])
    expected = sh.geometry.shape(report['landscape']['convertedGeometry'])
    witness_key = dict(sceneSha256=hashlib.sha256(scene_path.read_bytes()).hexdigest(),
                       reportSha256=hashlib.sha256(report_path.read_bytes()).hexdigest())
    selected = [c for c in scene['chunks'] if
                (c['id'] in added and c['name'] in {'pedestrian_path', 'railway_apron'})
                or (c['id'] in preserved and c['name'] == 'land')]
    witness_key['meshes'] = {c['file']: hashlib.sha256((root/'canonical/full'/Path(c['file']).name).read_bytes()).hexdigest()
                             for c in selected}
    cache_key = output/'cache-key.json'
    actual_file = output/'actual-paving.wkb'
    if actual_file.exists() and cache_key.exists() and json.loads(cache_key.read_text()) == witness_key:
        actual = sh.from_wkb(actual_file.read_bytes())
        print('REUSED EXACT PAVING WITNESS', flush=True)
    else:
        converted, existing = [], []
        for c in selected:
            raw = gzip.decompress((root/'canonical/full'/Path(c['file']).name).read_bytes())
            v = np.frombuffer(raw[:c['vertexBytes']], '<f4').reshape(-1, 8)
            ix = np.frombuffer(raw[c['vertexBytes']:], '<u4').reshape(-1, 3)
            world = v[:, :3][:, [0, 2, 1]]*[1, -1, 1]+origin
            if c['id'] in preserved:
                mask = (v.view('<u4')[ix[:, 0], 6] & 0x7fffffff) == 7
                existing.extend(sh.polygons(world[ix[mask], :2]))
            else:
                converted.extend(sh.polygons(world[ix, :2]))
            print('PAVING CHUNK', c['id'], c['name'], flush=True)
        # Match the verifier's grouping and order, including preserved paving.
        print('UNION CONVERTED', len(converted), flush=True)
        converted_domain = sh.union_all(converted)
        del converted
        print('UNION EXISTING', len(existing), flush=True)
        actual = sh.union_all([converted_domain, *existing])
        actual_file.write_bytes(sh.to_wkb(actual))
        cache_key.write_text(json.dumps(witness_key, indent=2)+'\n')
    (output/'expected-paving.wkb').write_bytes(sh.to_wkb(expected))
    missing = expected.difference(actual.buffer(.001))
    (output/'missing.wkb').write_bytes(sh.to_wkb(missing))
    pieces = sorted(polygons(missing), key=lambda p: -p.area)
    rows = [dict(index=i, areaM2=p.area, bounds=list(p.bounds),
                 representative=list(p.representative_point().coords)[0],
                 minimumClearanceM=p.minimum_clearance,
                 areaAfterHalfMillimetreInsetM2=p.buffer(-.0005).area,
                 areaAfterFiveMillimetreInsetM2=p.buffer(-.005).area)
            for i, p in enumerate(pieces)]
    geo = dict(type='FeatureCollection', features=[dict(type='Feature', properties=r,
                geometry=sh.geometry.mapping(p)) for r, p in zip(rows, pieces)])
    (output/'missing.geojson').write_text(json.dumps(geo, separators=(',', ':')))
    result = dict(missingAreaM2=missing.area, pieces=len(pieces), rows=rows)
    (output/'report.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(dict(result, rows=rows[:20]), indent=2), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    diagnose(args.root, args.output)
