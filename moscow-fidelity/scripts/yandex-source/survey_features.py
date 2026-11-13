"""Read physical detail evidence without interpreting CAD decoration as terrain.

Model-space paths retain their layer, handles and raw Z, but geometry consumers
must not use symbol/decorative elevations as measured ground or wall heights.
The previous ground-mark extraction stays immutable.
"""
import argparse, collections, gzip, hashlib, json, math
from pathlib import Path


def normalized(name):
    # This survey mixes Latin p/c with visually identical Cyrillic letters.
    return name.lower().translate(str.maketrans({'p': 'р', 'c': 'с'}))


def semantic(layer):
    s = normalized(layer)
    if s.startswith('ограды_каменные_и_жб'):
        return 'fence-stone-low' if 'менее' in s else 'fence-stone-high'
    if s.startswith('ограды_метал'):
        return 'fence-metal-low' if 'менее' in s else 'fence-metal-high'
    if s.startswith('ограждения_из_проволочной'):
        return 'fence-wire'
    if s.startswith(('заборы_деревянные', 'изгороди')):
        return 'fence-wood'
    if s.startswith('стенки_подпор'):
        return 'retaining-wall'
    if s.startswith('ворота_габаритныелиния'):
        return 'gate'
    if s.startswith('контуры_расти_грунт'):
        return 'ground-boundary'
    if s.startswith('лестницылиния'):
        return 'stairs'
    if s.startswith('проезжие_части_улиц'):
        return 'road-edge'
    if s.startswith('фонари_электрич'):
        return 'lamp-double' if 'двойные' in s else 'lamp-single'
    if s.startswith('деревья-ели'):
        return 'tree-spruce'
    if s.startswith('деревья_хвойные'):
        return 'tree-conifer'
    if s.startswith('деревья'):
        return 'tree-deciduous'
    if s.startswith(('кусты_отдельно', 'кустарники_отдельные')):
        return 'shrub-point'
    if s.startswith('газоныклумбы_'):
        return 'lawn-label'
    if s.startswith('луговая_растительность'):
        return 'meadow-label'
    if s.startswith('кустарники_заросли'):
        return 'scrub-label'
    if s.startswith('материал_покрытия'):
        return 'paving-label'
    return None


def hatch_rings(obj):
    """Return straight boundary loops; do not replace curves with chords."""
    rings = []
    for path in obj.get('paths', []):
        segs = path.get('segs', [])
        if not segs or any(s.get('curve_type') != 1 for s in segs):
            return []
        pts = [segs[0]['first_endpoint']]
        for seg in segs:
            if math.dist(pts[-1], seg['first_endpoint']) > .002:
                return []
            pts.append(seg['second_endpoint'])
        if math.dist(pts[0], pts[-1]) > .002:
            return []
        rings.append(pts)
    return rings


def extract_details(document):
    objects = document['OBJECTS']
    by_id = {o['handle'][-1]: o for o in objects if 'handle' in o}
    layers = {k: o['name'] for k, o in by_id.items() if o.get('object') == 'LAYER'}
    paths, hatches, points, texts = [], [], [], []
    counts, omitted = collections.Counter(), collections.Counter()
    for obj in objects:
        if obj.get('entmode') != 2 or obj.get('invisible'):
            continue
        layer = layers.get(obj.get('layer', [0])[-1], '')
        family = semantic(layer)
        if family is None:
            continue
        kind = obj.get('entity'); counts[(family, kind)] += 1
        row = dict(handle=obj['handle'][-1], layer=layer, family=family, entity=kind)
        if kind == 'INSERT':
            points.append(dict(row, point=obj['ins_pt'], rotation=obj.get('rotation', 0),
                               scale=obj.get('scale'), blockHandle=obj.get('block_header')))
            continue
        if kind in ('TEXT', 'MTEXT'):
            texts.append(dict(row, point=obj.get('ins_pt'), text=obj.get('text_value', obj.get('text'))))
            continue
        if kind == 'HATCH':
            rings = hatch_rings(obj)
            if rings:
                hatches.append(dict(row, rings=rings, pattern=obj.get('name'),
                                    rawElevation=obj.get('elevation')))
            else:
                omitted[(family, 'unsupported-hatch-boundary')] += 1
            continue
        vertices = []
        if kind == 'POLYLINE_3D':
            vertices = [by_id[r[-1]]['point'] for r in obj.get('vertex', []) if r[-1] in by_id]
        elif kind == 'LINE':
            vertices = [obj['start'], obj['end']]
        elif kind == 'LWPOLYLINE' and not any(obj.get('bulges', [])):
            vertices = [[x, y, obj.get('elevation', 0)] for x, y in obj['points']]
        if len(vertices) < 2:
            continue
        closed = bool(obj.get('flag', 0) & 1) if kind != 'LINE' else False
        if closed and math.dist(vertices[0][:2], vertices[-1][:2]) > 1e-7:
            vertices.append(vertices[0])
        length = sum(math.dist(a[:2], b[:2]) for a, b in zip(vertices[:-1], vertices[1:]))
        paths.append(dict(row, points=vertices, closed=closed, lengthXY=length))
    return dict(paths=paths, hatches=hatches, points=points, texts=texts,
                report=dict(counts=[dict(family=f, entity=e, count=c) for (f, e), c in counts.items()],
                            omitted=[dict(family=f, reason=r, count=c) for (f, r), c in omitted.items()],
                            zPolicy='Raw CAD Z preserved; not assumed to be ground or object top',
                            appliedToScene=False))


if __name__ == '__main__':
    p = argparse.ArgumentParser(); p.add_argument('input', type=Path); p.add_argument('output', type=Path)
    args = p.parse_args()
    raw = args.input.read_bytes(); result = extract_details(json.loads(raw))
    result['report']['decodedSourceSha256'] = hashlib.sha256(raw).hexdigest()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(gzip.compress(json.dumps(result, ensure_ascii=False).encode(), mtime=0))
    print(json.dumps({k: len(result[k]) for k in ('paths', 'hatches', 'points', 'texts')}))
    print(json.dumps(result['report'], ensure_ascii=False))
