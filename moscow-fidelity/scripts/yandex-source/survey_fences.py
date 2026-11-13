"""Match explicit survey fence classes to existing map fence centre lines.

This stage only produces evidence. CAD ticks, picket symbols and raw symbol Z
are not physical fence paths or heights. Conflicting classes stay unresolved.
"""
import argparse
import collections
import gzip
import hashlib
import json
import math
import pickle
from pathlib import Path

import numpy as np
import shapely as sh
from pyproj import Transformer
from build_scene import dump, lines
from moscow_style import ribbon_centerlines
from shapely.ops import substring

POLICY = dict(version=1, maximumOffsetM=1.5, minimumParallelCosine=.98,
              minimumCadPathLengthM=2., minimumCadSegmentLengthM=.5,
              minimumMatchedRunM=2., closedCadPaths='excluded: may be picket symbols',
              conflicts='leave the original display wherever survey classes disagree',
              geometry='retain Yandex ribbon medial line and gates',
              heights='ignore CAD symbol Z; display defaults seated on finished ground')


def source_key(feature, geometry, centreline):
    fid = feature.get('id')
    if fid is None:
        fid = hashlib.sha256((geometry.wkb_hex+centreline.wkb_hex).encode()).hexdigest()[:24]
    return 'yandex:'+feature['layer']+':'+str(fid)


# Explicit survey families; dimensions are shared display defaults, not CAD Z.
SPECS = {
    'fence-stone-high': dict(family='solid', heightM=1.8, spacingM=1.3, material=2),
    'fence-stone-low': dict(family='solid', heightM=.9, spacingM=1.3, material=2),
    'fence-metal-high': dict(family='metal', heightM=1.8, spacingM=1.8, material=0),
    'fence-metal-low': dict(family='metal', heightM=.9, spacingM=1.3, material=0),
    'fence-wood': dict(family='wood', heightM=1.6, spacingM=1.7, material=1),
    'fence-wire': dict(family='wire', heightM=1.6, spacingM=2., material=0),
}


def overlay_pieces(line, baseline, record):
    if record is None:
        return baseline
    pieces = []
    runs = [r for r in record['runs'] if r['family']]
    for part, old in baseline:
        assembled = []
        xy = np.asarray(part.coords)
        for a, b in zip(xy[:-1], xy[1:]):
            length = np.linalg.norm(b-a)
            if length < 1e-8: continue
            mid = sh.Point((a+b)/2)
            station = line.project(mid)
            assert line.interpolate(station).distance(mid) < 1e-5
            tangent = np.asarray(line.interpolate(min(line.length, station+.001)).coords[0])-np.asarray(line.interpolate(max(0, station-.001)).coords[0])
            direction = 1 if (b-a) @ tangent >= 0 else -1
            start, end = station-direction*length/2, station+direction*length/2
            cuts = {0., 1.}
            for r in runs:
                for s in (r['startM'], r['endM']):
                    u = (s-start)/(end-start)
                    if 1e-9 < u < 1-1e-9: cuts.add(u)
            cuts = sorted(cuts)
            for lo, hi in zip(cuts[:-1], cuts[1:]):
                s = start+(end-start)*(lo+hi)/2
                r = next((r for r in runs if r['startM']-1e-8 <= s <= r['endM']+1e-8), None)
                spec = old if r is None else dict(SPECS[r['family']], sourceCode='survey:'+r['family'],
                                                 surveyHandles=r['handles'], typeStatus='survey-layer')
                p, q = a+(b-a)*lo, a+(b-a)*hi
                if assembled and assembled[-1][1] == spec and np.linalg.norm(assembled[-1][0][-1]-p) < 1e-8:
                    assembled[-1][0].append(q)
                else: assembled.append(([p, q], spec))
        pieces.extend((sh.LineString(points), spec) for points, spec in assembled)
    return pieces


def evidence(details, transformer):
    rows = []
    rejected = collections.Counter()
    for p in details['paths']:
        if not p['family'].startswith('fence-'):
            continue
        if p['closed'] or p['lengthXY'] < POLICY['minimumCadPathLengthM']:
            rejected['closed-or-symbol-size'] += 1
            continue
        xy = np.asarray(p['points'])[:, :2]
        xy = np.column_stack(transformer.transform(xy[:, 0], xy[:, 1]))
        for a, b in zip(xy[:-1], xy[1:]):
            if np.linalg.norm(b-a) < POLICY['minimumCadSegmentLengthM']:
                rejected['short-segment'] += 1
                continue
            rows.append(dict(handle=p['handle'], family=p['family'], layer=p['layer'],
                             line=sh.LineString([a, b])))
    return rows, dict(rejected)


def classify_line(line, rows, tree):
    """Partition original chainage; make overlap conflicts order independent."""
    intervals = []
    station = 0.
    xy = np.asarray(line.coords)
    for a, b in zip(xy[:-1], xy[1:]):
        d = b-a
        length = np.linalg.norm(d)
        if length < 1e-8:
            continue
        edge = sh.LineString([a, b])
        for i in tree.query(edge, predicate='dwithin', distance=POLICY['maximumOffsetM']):
            row = rows[i]
            near = row['line']
            n = np.asarray(near.coords)
            v = n[-1]-n[0]
            if abs(d @ v) < POLICY['minimumParallelCosine']*length*np.linalg.norm(v):
                continue
            # Flat caps prevent a nearby fence end from crossing a real gate.
            overlap = edge.intersection(near.buffer(POLICY['maximumOffsetM'], cap_style='flat'))
            for part in lines(overlap):
                uv = [float(np.clip((np.asarray(p)-a) @ d/length, 0, length))
                      for p in [part.coords[0], part.coords[-1]]]
                lo, hi = sorted(uv)
                if hi-lo > 1e-6:
                    intervals.append((station+lo, station+hi, int(i)))
        station += length
    cuts = sorted({0., line.length, *(x for lo, hi, _ in intervals for x in [lo, hi])})
    runs = []
    for lo, hi in zip(cuts[:-1], cuts[1:]):
        if hi-lo < 1e-7:
            continue
        middle = (lo+hi)/2
        active = [i for a, b, i in intervals if a-1e-7 <= middle <= b+1e-7]
        classes = sorted({rows[i]['family'] for i in active})
        family = classes[0] if len(classes) == 1 else None
        status = 'matched' if family else 'conflict' if classes else 'unmatched'
        handles = {rows[i]['handle'] for i in active}
        if runs and runs[-1]['family'] == family and runs[-1]['status'] == status:
            runs[-1]['endM'] = hi
            runs[-1]['handles'].update(handles)
            runs[-1]['classes'].update(classes)
        else:
            runs.append(dict(startM=lo, endM=hi, family=family, status=status,
                             handles=handles, classes=set(classes)))
    for row in runs:
        row['lengthM'] = row['endM']-row['startM']
        if row['family'] and row['lengthM'] < POLICY['minimumMatchedRunM']:
            row.update(family=None, status='short-match')
        row['handles'] = sorted(row['handles'])
        row['classes'] = sorted(row['classes'])
    return runs


def audit(base, source, details_path, output):
    city = json.loads((base/'canonical/urban-model.json').read_text())
    meta = json.loads((base/'survey-terrain.json').read_text())
    raw = details_path.read_bytes()
    details = json.loads(gzip.decompress(raw))
    transform = Transformer.from_crs(meta['projection'], city['crsProj'], always_xy=True)
    rows, rejected = evidence(details, transform)
    tree = sh.STRtree([p['line'] for p in rows])
    with (source/'projected-scene-v1.pickle').open('rb') as f:
        features, *_ = pickle.load(f)
    stats = collections.Counter()
    results = []
    for f, g, source_line in features:
        if f['layer'] != 'fence_a':
            continue
        if not len(tree.query(g, predicate='dwithin', distance=POLICY['maximumOffsetM'])):
            continue
        for index, line in enumerate(ribbon_centerlines(g)):
            runs = classify_line(line, rows, tree)
            if not any(r['handles'] for r in runs):
                continue
            for r in runs:
                stats[r['family'] or r['status']] += r['lengthM']
            results.append(dict(sourceId=source_key(f, g, source_line), lineIndex=index,
                                points=np.asarray(line.coords).tolist(), runs=runs))
    report = dict(policy=POLICY, parent=base.name, decodedSourceSha256=details['report']['decodedSourceSha256'],
                  detailsSha256=hashlib.sha256(raw).hexdigest(), evidenceSegments=len(rows),
                  rejected=rejected, matchedLengthByClassM=dict(stats), sourceLines=len(results),
                  records=results, appliedToScene=False)
    dump(output, report)
    print(json.dumps({k: v for k, v in report.items() if k != 'records'}, ensure_ascii=False), flush=True)
    return report


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    for name in ('base', 'source', 'details', 'output'):
        p.add_argument('--'+name, type=Path, required=True)
    a = p.parse_args()
    audit(a.base, a.source, a.details, a.output)
