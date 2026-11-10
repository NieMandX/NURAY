"""Resume the offline 10 km Moscow build; never activate an incomplete release."""
import json
import argparse
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
CITY = ROOT / 'moscow-fidelity'
SOURCE = CITY / 'source/2gis-moscow-20261021-10km-build'
WORK = CITY / 'diagnostics/moscow-10km-20261108'
PREPARED = SOURCE / 'output/area_10000'
SURFACE = CITY / 'web-preview/prototype/tiles/assets-moscow-10km-20261108-surface'
WORK.mkdir(parents=True, exist_ok=True)


def stage(name, command, env=None):
    receipt = WORK / (name + '.json')
    if receipt.exists() and json.loads(receipt.read_text()).get('passed'):
        print('REUSE', name, flush=True)
        return
    state = dict(stage=name, command=list(map(str, command)), started=time.time(), passed=False)
    receipt.write_text(json.dumps(state, indent=2))
    print('START', name, flush=True)
    with (WORK / (name + '.log')).open('w') as log:
        result = subprocess.run(command, cwd=CITY, stdout=log, stderr=subprocess.STDOUT, env=env)
    state.update(finished=time.time(), returncode=result.returncode, passed=result.returncode == 0)
    receipt.write_text(json.dumps(state, indent=2))
    if result.returncode:
        raise RuntimeError('Failed stage ' + name + '; see ' + str(WORK / (name + '.log')))
    print('PASSED', name, flush=True)


def require_stages(names, wait=False):
    for name in names:
        path = WORK / (name + '.json')
        while True:
            prior = json.loads(path.read_text()) if path.exists() else {}
            if prior.get('passed'):
                break
            if prior.get('returncode') is not None or not wait:
                raise RuntimeError('Required stage is not complete: ' + name)
            time.sleep(5)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--phase', choices=['surfaces', 'objects', 'city', 'final', 'finish'], default='surfaces')
    parser.add_argument('--wait', action='store_true', help='Wait for the preceding owned build stage')
    resume = parser.add_mutually_exclusive_group()
    resume.add_argument('--resume-surfaces', action='store_true', help='Reuse fitted road/terrain checkpoint after a structural-rule repair')
    resume.add_argument('--resume-stage', choices=['surfaces', 'paint'], help='Reuse a completed canonical surface or paint stage')
    resume.add_argument('--resume-final', action='store_true', help='Reuse completed walls too; rerun only canonical validation/export')
    parser.add_argument('--rebuild-curb-sides',action='store_true',help='Rebuild curb side classification with --resume-stage')
    args = parser.parse_args()
    if args.rebuild_curb_sides and not args.resume_stage:parser.error('--rebuild-curb-sides requires --resume-stage')
    os.environ['NURAY_DEFER_CANONICAL_GLB'] = '1'
    py = sys.executable
    live = CITY / 'scripts/live-source'
    if args.phase == 'objects':
        require_stages(['01-prepare-source'], args.wait)
        env = dict(os.environ)
        env.pop('PYTHONPATH', None)
        stage('05-extract-objects', ['/Applications/Blender 2.app/Contents/MacOS/Blender',
            '--background', '--factory-startup', '--python', live / 'extract_objects_blender.py',
            '--', '--source', SOURCE, '--output', SOURCE / 'extraction'], env=env)
        sys.exit(0)
    if args.phase in ('city', 'finish'):
        require_stages(['04-canonical-surfaces', '05-extract-objects'], args.wait)
        stage('06-city-layers', [py, live / 'build_assets.py', '--snapshot', SOURCE,
            '--surface', SURFACE, '--output', CITY / 'web-preview/prototype/tiles/assets-moscow-10km-20261108-city',
            '--node', os.environ['NODE'], '--inventory', WORK / 'inventory'])
        if args.phase == 'city':
            sys.exit(0)
    if args.phase in ('final', 'finish'):
        require_stages(['06-city-layers'], args.wait)
        base = CITY / 'web-preview/prototype/tiles/assets-moscow-10km-20261108-city'
        final = CITY / 'web-preview/prototype/tiles/assets-moscow-10km-20261108-r1'
        command = [py, CITY / 'prototype/tiling/prepare_waterfront_parapet.py', '--base', base, '--output', final]
        if final.exists():
            command.append('--resume')
        stage('07-river-parapet', command)
        stage('08-surface-effects', [py, CITY / 'prototype/tiling/prepare_surface_effects.py', '--catalog', final])
        config = json.loads((CITY / 'web-preview/prototype/tiles/config.json').read_text())
        catalog = json.loads((final / 'tileset.json').read_text())
        catalog['geography'] = config['geography']['assets-moscow-style-20261024-r14/tileset.json']
        catalog['regionName'] = 'Москва'
        (final / 'tileset.json').write_text(json.dumps(catalog, ensure_ascii=False, separators=(',', ':')))
        stage('09-merged-scene', [py, CITY / 'prototype/tiling/export_merged_glb.py', '--source', final,
            '--output', final / 'merged'])
        stage('10-compressed-delivery', [py, ROOT / 'scripts/prepare_delivery.py', '--source', final,
            '--output', final / 'delivery-20261108-v1'])
        sys.exit(0)
    stage('01-prepare-source', [py, live / 'prepare_scene.py', PREPARED / 'plan.json'])
    stage('02-marking-symbols', [py, live / 'prepare_icons.py', PREPARED])
    stage('03-extract-markings', [py, live / 'extract_paint.py', SOURCE, SOURCE / 'markings'])
    if args.resume_final:
        stage('04-canonical-surfaces', [py, CITY / 'prototype/tiling/resume_region.py',
            SOURCE / 'canonical-stage.pkl', '--source', SOURCE])
        sys.exit(0)
    command = [py, CITY / 'prototype/tiling/build_region.py',
        '--source', SOURCE, '--markings', SOURCE / 'markings', '--size', '10000',
        '--output', SURFACE / 'canonical',
        '--source-checkpoint', SOURCE / 'source-stage.pkl',
        '--surface-checkpoint', SOURCE / 'surface-stage.pkl',
        '--checkpoint', SOURCE / 'canonical-stage.pkl']
    if args.resume_surfaces:
        command += ['--resume-surfaces', SOURCE / 'surface-stage.pkl']
    elif args.resume_stage:
        command += ['--resume-stage', SOURCE / ('canonical-stage.' + args.resume_stage + '.pkl')]
    if args.rebuild_curb_sides:command.append('--rebuild-curb-sides')
    stage('04-canonical-surfaces', command)
