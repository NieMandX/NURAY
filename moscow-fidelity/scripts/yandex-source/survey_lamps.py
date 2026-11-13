"""Plan physical lamp INSERTs from survey layers, with auditable deferrals.

Block glyph size, Z and drawing rotation are not measured lamp dimensions or
orientation. Preserve them in evidence; seat upright library instances on the
finished city. Arms face the nearest drivable surface where it is unambiguous.
"""
import argparse
import collections
import gzip
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import shapely as sh
from pyproj import Transformer
from build_scene import dump
from survey_features import normalized
from street_placement import SurfaceSampler, transform

POLICY = dict(version=1, duplicateToleranceM=.1, baseRadiusM=.18,
              maximumRoadDirectionDistanceM=30.,
              xy='survey INSERT point, unchanged; no snapping',
              height='finished serialized ground; CAD symbol Z ignored',
              orientation='display estimate toward closest drivable boundary, otherwise fixed north; not a surveyed azimuth',
              dimensions='shared NURAY display defaults, not measured pole or luminaire dimensions',
              conflicts='defer building, water, road-interior and conflicting duplicate points')


def lamp_model(row):
    if row['family'] == 'lamp-double':
        return 'lamppost2'
    if row['family'] == 'lamp-single':
        return 'lamppost-concrete1' if '_жб_' in normalized(row['layer']) else 'lamppost1'
    raise ValueError('Not a physical lamp survey layer')


def orientation(point, road):
    """Model +Z points toward the road in the Y-up renderer (north is -Z)."""
    q = sh.shortest_line(point, road)
    if q.is_empty or q.length < 1e-6 or q.length > POLICY['maximumRoadDirectionDistanceM']:
        return math.pi, 'display-default-north', None
    a, b = np.asarray(q.coords)
    d = b-a
    return math.atan2(float(d[0]), float(-d[1])), 'estimated-nearest-road', float(q.length)


def plan(details, projection, ground, masks, road):
    rows = []
    for p in details['points']:
        if p['family'] not in ('lamp-single', 'lamp-double'):
            continue
        x, n = projection.transform(*p['point'][:2])
        assert math.isfinite(x) and math.isfinite(n)
        rows.append(dict(sourceId='survey-lamp:'+str(p['handle']), handle=p['handle'],
                         layer=p['layer'], model=lamp_model(p), sourcePoint=p['point'],
                         sourceRotation=p.get('rotation'), sourceScale=p.get('scale'),
                         blockHandle=p.get('blockHandle'), eastNorth=[x, n]))
    rows.sort(key=lambda r:r['handle'])
    points = sh.points([r['eastNorth'] for r in rows])
    tree = sh.STRtree(points)
    parents = list(range(len(rows)))
    def root(i):
        while parents[i] != i:
            parents[i] = parents[parents[i]]; i = parents[i]
        return i
    for i, p in enumerate(points):
        for j in tree.query(p, predicate='dwithin', distance=POLICY['duplicateToleranceM']):
            a, b = root(i), root(int(j))
            parents[max(a, b)] = min(a, b)
    groups = collections.defaultdict(list)
    for i in range(len(rows)): groups[root(i)].append(i)
    rejected = {}
    for ids in groups.values():
        if len({rows[i]['model'] for i in ids}) > 1:
            rejected.update((i, 'conflicting-duplicate-types') for i in ids)
        else:
            rejected.update((i, 'duplicate-source-point') for i in ids[1:])
    for i, r in enumerate(rows):
        p = points[i]; reason = rejected.get(i)
        if reason is None:
            for name in ('building', 'water'):
                if masks[name].distance(p) < POLICY['baseRadiusM']:
                    reason = name+'-clearance'; break
        if reason is None and road.covers(p): reason = 'inside-drivable-surface'
        x, n = r['eastNorth']
        hit = ground.ground(x, -n) if reason is None else None
        if reason is None and hit is None: reason = 'no-containing-finished-ground'
        if reason:
            r.update(status='deferred', reason=reason); continue
        yaw, direction, distance = orientation(p, road)
        r.update(status='accepted', surface=hit, orientation=direction,
                 roadDistanceM=distance, yawRadians=yaw,
                 matrix=transform([0, 0, math.degrees(yaw)], [1, 1, 1], [x, hit['height'], -n]))
    return rows


def audit(base, details_path, output):
    city = json.loads((base/'canonical/urban-model.json').read_text())
    meta = json.loads((base/'survey-terrain.json').read_text())
    scene = json.loads((base/'canonical/full/scene.json').read_text())
    raw = details_path.read_bytes(); details = json.loads(gzip.decompress(raw))
    projection = Transformer.from_crs(meta['projection'], city['crsProj'], always_xy=True)
    m = json.loads(gzip.decompress((base/'placement-masks.json.gz').read_bytes()))
    masks = {k:sh.from_wkb(bytes.fromhex(v)) for k,v in m['root'].items()}
    road = sh.union_all([sh.from_wkb(bytes.fromhex(v['geometry'])) for v in m['finishedGround'] if v['kind'] in ('road','parking')])
    ground = SurfaceSampler(base, scene, {'land','road-curbs','green-curbs','curbs'})
    rows = plan(details, projection, ground, masks, road)
    report = dict(parent=base.name, policy=POLICY, appliedToScene=False,
                  detailsSha256=hashlib.sha256(raw).hexdigest(),
                  decodedSourceSha256=details['report']['decodedSourceSha256'],
                  accepted=sum(r['status']=='accepted' for r in rows), source=len(rows),
                  deferredByReason=dict(collections.Counter(r['reason'] for r in rows if r['status']=='deferred')),
                  acceptedByModel=dict(collections.Counter(r['model'] for r in rows if r['status']=='accepted')), records=rows)
    dump(output, report)
    print(json.dumps({k:v for k,v in report.items() if k!='records'},ensure_ascii=False),flush=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    for n in ('base','details','output'): p.add_argument('--'+n, type=Path, required=True)
    a = p.parse_args(); audit(a.base, a.details, a.output)
