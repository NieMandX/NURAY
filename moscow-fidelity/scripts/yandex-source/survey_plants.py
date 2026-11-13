"""Conservative additions from explicit survey plant INSERTs, never relocation.

Existing map plants remain unchanged. Unknown conifer species, crowded or
conflicting positions and paved tree pits need more evidence and are deferred.
CAD glyph dimensions/elevations are retained as evidence, not physical sizes.
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
from scipy.spatial import cKDTree
from build_scene import BASE_SCALE, dump
from prepare_supplement import Terrain
from survey_features import normalized

POLICY = dict(version=1, existingSeparationM=6., newSeparationM=2.,
              duplicateToleranceM=.1, rootClearanceM=.22,
              sourceXY='unchanged survey INSERT anchor',
              scope='explicit individual plant symbols inside existing finished green surfaces',
              dimensions='approved library defaults with deterministic +/-10% scale; not survey measurements',
              unknownConifer='deferred; do not infer pine, spruce or thuja from a generic conifer symbol',
              conflicts='defer, never snap or delete existing plants')


def source_model(row):
    if row['family'] == 'tree-spruce': return 'spruce'
    if row['family'] == 'shrub-point': return 'bush'
    if row['family'] == 'tree-deciduous':
        return 'low' if 'фруктов' in normalized(row['layer']) else 'open'
    return None


def variation(identity, model):
    h = hashlib.sha256(identity.encode()).digest()
    a = int.from_bytes(h[:8], 'little') / 2**64
    b = int.from_bytes(h[8:16], 'little') / 2**64
    return a*math.tau, BASE_SCALE[model]*(.9+.2*b)


def plan(details, projection, existing_xy, masks, crowns, buildings, green, sample_height, origin_alt):
    rows = []
    for p in details['points']:
        if p['family'] not in ('tree-deciduous','tree-spruce','tree-conifer','shrub-point'): continue
        x,n = projection.transform(*p['point'][:2])
        assert math.isfinite(x) and math.isfinite(n)
        rows.append(dict(id='survey-plant:'+str(p['handle']),handle=p['handle'],layer=p['layer'],
                         family=p['family'],model=source_model(p),sourcePoint=p['point'],
                         sourceScale=p.get('scale'),sourceRotation=p.get('rotation'),
                         blockHandle=p.get('blockHandle'),eastNorth=[x,n]))
    rows.sort(key=lambda r:r['id'])
    points = sh.points([r['eastNorth'] for r in rows])
    source_tree = sh.STRtree(points)
    existing = cKDTree(existing_xy) if len(existing_xy) else None
    btree = sh.STRtree([p for p,h in buildings])
    tops = np.array([h for p,h in buildings])
    accepted_points = []
    for i,r in enumerate(rows):
        p = points[i]; reason = None
        ids = source_tree.query(p,predicate='dwithin',distance=POLICY['duplicateToleranceM'])
        if len({rows[int(j)]['model'] for j in ids}) > 1: reason='conflicting-survey-symbols'
        elif any(int(j)<i for j in ids): reason='duplicate-survey-point'
        elif r['model'] is None: reason='unspecified-conifer-type'
        nearest = float(existing.query(r['eastNorth'])[0]) if existing else None
        r['nearestExistingM']=nearest
        if reason is None and nearest is not None and nearest < POLICY['existingSeparationM']:
            reason='near-existing-plant'
        if reason is None and not green.covers(p): reason='outside-confirmed-green-surface'
        if reason is None and any(p.distance(q)<POLICY['newSeparationM'] for q in accepted_points):
            reason='crowded-survey-points'
        if reason is not None:
            r.update(status='deferred',reason=reason);continue
        angle,scale=variation(r['id'],r['model'])
        radius,low=np.array(crowns[r['model']])*scale
        clearance=max(POLICY['rootClearanceM'],radius if low<2.5 else POLICY['rootClearanceM'])
        footprint=p.buffer(clearance,quad_segs=4)
        conflicts=[k for k,g in masks.items() if g.intersects(footprint)]
        height=sample_height(*r['eastNorth'])
        if height is None or not math.isfinite(height): conflicts.append('no-finished-ground')
        else:
            near=btree.query(p.buffer(radius,quad_segs=8),predicate='intersects')
            if len(near) and np.any(tops[near]>height+origin_alt+low+1e-6):conflicts.append('buildingCanopy')
        if conflicts:
            r.update(status='deferred',reason='surface-conflict',conflicts=conflicts);continue
        x,n=r['eastNorth'];c,s=math.cos(angle)*scale,math.sin(angle)*scale
        matrix=[c,0,s,x,0,scale,0,height,-s,0,c,-n]
        r.update(status='accepted',matrix=matrix,scale=scale,yawRadians=angle,
                 clearanceM=clearance,crownRadiusM=float(radius),crownBottomM=float(low))
        accepted_points.append(p)
    return rows


def audit(base,details_path,output):
    scene=json.loads((base/'canonical/full/scene.json').read_text())
    city=json.loads((base/'canonical/urban-model.json').read_text())
    survey=json.loads((base/'survey-terrain.json').read_text())
    raw=details_path.read_bytes();details=json.loads(gzip.decompress(raw))
    project=Transformer.from_crs(survey['projection'],city['crsProj'],always_xy=True)
    m=json.loads(gzip.decompress((base/'placement-masks.json.gz').read_bytes()))
    masks={k:sh.from_wkb(bytes.fromhex(v)) for k,v in m['root'].items()}
    green=sh.union_all([sh.from_wkb(bytes.fromhex(g['geometry'])) for g in m['finishedGround'] if g['kind'] in ('grass','cemetery')])
    buildings=[(sh.from_wkb(bytes.fromhex(p)),h) for p,h in m['buildings']]
    previous=json.loads(gzip.decompress((base/'plant-placement-audit.json.gz').read_bytes()))
    xy=np.array([r['eastNorth'] for r in previous['acceptedPoints']])
    terrain=Terrain(np.load(base/'canonical/terrain.npz')['triangles'])
    ground=[(sh.from_wkb(bytes.fromhex(g['geometry'])),g['offsetM']) for g in m['finishedGround']]
    def sample(x,n):
        p=sh.Point(x,n);offset=0
        for g,h in ground:
            if g.covers(p):offset=h
        return float(terrain.sample([[x,n]])[0])+offset-scene['origin'][2]
    rows=plan(details,project,xy,masks,m['crowns'],buildings,green,sample,scene['origin'][2])
    report=dict(parent=base.name,policy=POLICY,appliedToScene=False,
                detailsSha256=hashlib.sha256(raw).hexdigest(),decodedSourceSha256=details['report']['decodedSourceSha256'],
                source=len(rows),accepted=sum(r['status']=='accepted' for r in rows),
                acceptedByModel=dict(collections.Counter(r['model'] for r in rows if r['status']=='accepted')),
                deferredByReason=dict(collections.Counter(r['reason'] for r in rows if r['status']=='deferred')),
                records=rows)
    dump(output,report);print(json.dumps({k:v for k,v in report.items() if k!='records'},ensure_ascii=False),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser()
    for n in ('base','details','output'):p.add_argument('--'+n,type=Path,required=True)
    a=p.parse_args();audit(a.base,a.details,a.output)
