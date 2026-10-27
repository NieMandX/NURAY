"""Verify downloaded bytes and coverage before using a live source snapshot."""
from pathlib import Path
import argparse
import hashlib
import json


def verify(root):
    root = Path(root).resolve()
    plan = json.loads((root / 'plan.json').read_text())
    checks = []
    receipts = ['sources.json', 'style-resources.json']
    if (root / 'browser-resources.json').exists():
        receipts.append('browser-resources.json')
    for receipt in receipts:
        for row in json.loads((root / receipt).read_text()):
            path = (root / row['file']).resolve()
            inside = path.is_relative_to(root)
            passed = inside and path.is_file()
            if passed:
                passed = (path.stat().st_size == row['bytes'] and
                          hashlib.sha256(path.read_bytes()).hexdigest() == row['sha256'])
            checks.append(dict(file=str(path.relative_to(root)) if inside else str(path),
                               receipt=receipt, passed=passed,
                               retrievedAt=row['retrievedAt']))
    coverage = []
    for tile in plan['tiles']:
        stem = '_'.join(map(str, tile[:3]))
        files = [f'{stem}.pbf', f'{stem}.json', f'{stem}.ald.json',
                 f'dem_{stem}.bin', f'dem_{stem}.json']
        coverage.append(dict(tile=tile, passed=all((root / 'source/cache' / f).is_file() for f in files)))
    output = root / 'output' / plan.get('output_subdir', 'area_5000')
    models = json.loads((output / 'models.json').read_text())
    model_checks = []
    for model in models:
        files = [Path(p).resolve() for p in model['local_files'].values()]
        model_checks.append(dict(buildingId=model['properties'].get('building_id'),
            passed=bool(files) and all(p.is_relative_to(root) and p.is_file() for p in files)))
    report = dict(passed=all(c['passed'] for c in checks + coverage + model_checks),
        resources=len(checks), sourceTiles=len(coverage), availableModels=len(models),
        checks=checks, coverage=coverage, models=model_checks,
        unavailableModels=json.loads((output / 'unavailable_models.json').read_text()),
        sourcePolicy='Only bytes inside this live snapshot; no geometry fallback to an older capture.')
    (root / 'acquisition-validation.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
    if not report['passed']:
        raise RuntimeError('Live snapshot verification failed; inspect acquisition-validation.json')
    print('LIVE SNAPSHOT VERIFIED', report['resources'], 'resources,', report['sourceTiles'],
          'tiles,', report['availableModels'], 'available models,',
          len(report['unavailableModels']), 'unavailable model resources', flush=True)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('root', type=Path)
    verify(parser.parse_args().root)
