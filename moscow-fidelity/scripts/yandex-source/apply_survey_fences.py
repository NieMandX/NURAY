"""Replace fence geometry only; inherit surveyed terrain and every other layer.

The map owns paths/gates. Explicit matching DWG layers own fence classes.
Physical ground contact is sampled from the already serialized r6 surfaces.
"""
import argparse
import collections
import gc
import gzip
import hashlib
import json
import pickle
import shutil
from pathlib import Path

import numpy as np
import shapely as sh
from build_scene import Builder, Terrain, dump
from canonical_store import copy_asset
from street_placement import SurfaceSampler
from style_evidence import load
import moscow_style


class FenceBuilder(Builder):
    def flush(self, name):
        # Namespace new blocks so source chunk renumbering cannot overwrite an
        # inherited building/terrain file with the same old numeric basename.
        full = self.full
        self.full = self.out/'fence-build'
        self.full.mkdir(exist_ok=True)
        before = len(self.chunks)
        super().flush(name)
        for c in self.chunks[before:]:
            source = self.full/c['file']
            c['file'] = 'survey-fence-'+source.name
            source.rename(full/c['file'])
        self.full = full


def apply(base, out, source, supplement, matches):
    assert not out.exists() and out.resolve() != base.resolve()
    report = json.loads(matches.read_text())
    assert report['parent'] == base.name and not report['appliedToScene']
    parent = json.loads((base/'canonical/full/scene.json').read_text())
    city = json.loads((base/'canonical/urban-model.json').read_text())
    out.mkdir(parents=True)
    for name in ('canonical', 'textures'):
        shutil.copytree(base/name, out/name, copy_function=copy_asset)
    # Immutable evidence is carried forward; derived validation is regenerated.
    for path in base.iterdir():
        if path.is_file() and path.suffix in ('.json', '.gz') and path.name not in ('validation.json', 'objects.json.gz'):
            copy_asset(path, out/path.name)
    full = out/'canonical/full'
    b = FenceBuilder.__new__(FenceBuilder)
    b.out, b.full = out, full
    b.materials, b.textures = parent['materials'], parent['textures']
    b.alt = parent['origin'][2]
    b.terrain = Terrain(np.load(base/'canonical/terrain.npz')['triangles'])
    masks = json.loads(gzip.decompress((base/'placement-masks.json.gz').read_bytes()))
    b.finished = {p['kind']: sh.from_wkb(bytes.fromhex(p['geometry'])) for p in masks['finishedGround'] if p['kind'] != 'road-curb'}
    b.road_curb = next(sh.from_wkb(bytes.fromhex(p['geometry'])) for p in masks['finishedGround'] if p['kind'] == 'road-curb')
    b.finished['water'] = sh.from_wkb(bytes.fromhex(masks['root']['water']))
    # Containment in the finished-ground sampler below excludes actual holes.
    b.holes = sh.Polygon()
    with (source/'projected-scene-v1.pickle').open('rb') as f:
        rows, *_ = pickle.load(f)
    b.fences = [r for r in rows if r[0]['layer'] == 'fence_a']
    del rows
    gc.freeze(); gc.disable()
    b.chunks = []
    mapping = {}
    unchanged = []
    for c in parent['chunks']:
        if c['name'] == 'street-fences':
            (full/c['file']).unlink()  # Independent COW stage copy only.
            continue
        c = dict(c)
        old = c['id']; c['id'] = len(b.chunks); mapping[old] = c['id']
        unchanged.append(dict(parentMesh=old, mesh=c['id'], name=c['name'], file=c['file'],
                              sha256=hashlib.sha256((full/c['file']).read_bytes()).hexdigest()))
        b.chunks.append(c)
    b.instances = [{**i, 'mesh':mapping[i['mesh']]} for i in parent['instances'] if i['mesh'] in mapping]
    b.batches = collections.defaultdict(list); b.batch_counts = collections.Counter()
    b.style_audit = {}
    print('READ FINISHED GROUND', flush=True)
    ground = SurfaceSampler(base, parent, {'land', 'road-curbs', 'green-curbs', 'curbs'})
    evidence = load(supplement, city['crsProj'], supplement/'nuray-style-evidence-v2.pickle')
    match_index = {(r['sourceId'], r['lineIndex']):r for r in report['records']}
    assert len(match_index) == len(report['records'])
    moscow_style.fences(b, evidence, survey=match_index, ground=ground)
    for name in list(b.batches): b.flush(name)
    (out/'fence-build').rmdir()
    # The complete parent layer list survives byte-for-byte except fences.
    for c in unchanged:
        assert hashlib.sha256((full/c['file']).read_bytes()).hexdigest() == c['sha256']
    for name in ('terrain.npz', 'survey-field.npz', 'road-height-field.npz'):
        assert (out/'canonical'/name).read_bytes() == (base/'canonical'/name).read_bytes()
    scene = {**parent, 'chunks':b.chunks, 'instances':b.instances, 'materials':b.materials}
    scene['stats'] = dict(uniqueTriangles=sum(c['triangles'] for c in b.chunks),
                         expandedTriangles=sum(b.chunks[i['mesh']]['triangles'] for i in b.instances))
    labels = {'fence-stone-high':'Каменная стена', 'fence-stone-low':'Низкая каменная ограда',
              'fence-metal-high':'Металлическое ограждение', 'fence-metal-low':'Низкая металлическая ограда',
              'fence-wood':'Деревянный забор', 'fence-wire':'Сетчатое ограждение'}
    for code, camera in b.style_audit['fences']['witnessViews'].items():
        if not code.startswith('survey:'): continue
        family = code.split(':', 1)[1]; key = 'survey-'+family+'-review'
        scene.setdefault('witnessViews', {})[key] = camera
        scene.setdefault('witnessViewLabels', {})[key] = 'Топосъёмка · '+labels[family].lower()
    report.update(appliedToScene=True, result=b.style_audit['fences'],
                  unchangedCanonicalMeshes=unchanged, terrainByteIdentical=True,
                  surveyFieldByteIdentical=True, roadFieldByteIdentical=True,
                  plantsIdentical=True, dimensions='NURAY display defaults, not measured fence height')
    city['surveyFences'] = {k:v for k,v in report.items() if k not in ('records','unchangedCanonicalMeshes')}
    city['geometryRevision'] = dict(version='yandex-survey-fences-7', parent=base.name)
    city['limitations'].append('Survey fence class requires parallel overlap; conflicting/short matches remain neutral. Heights are display defaults; CAD symbol Z is not used.')
    dump(full/'scene.json', scene); dump(out/'canonical/urban-model.json', city)
    dump(out/'survey-fences.json', report)
    for name in ('canonical/validation.json','build-audit.json'):
        audit = json.loads((out/name).read_text())
        audit.update(stats=scene['stats'], surveyFences=city['surveyFences'])
        dump(out/name, audit)
    print('SURVEY FENCES COMPLETE', scene['stats'], flush=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    for name in ('base','output','source','supplement','matches'):
        p.add_argument('--'+name, type=Path, required=True)
    a = p.parse_args()
    apply(a.base, a.output, a.source, a.supplement, a.matches)
