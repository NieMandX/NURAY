"""Validate the delta against a fully validated immutable parent release."""
import argparse,gzip,hashlib,json
from pathlib import Path
import numpy as np
import shapely as sh
from shapely import affinity
from relocate_green_plants import LocalGround,dump


def digest(p):
    h=hashlib.sha256()
    with p.open('rb')as f:
        for block in iter(lambda:f.read(4*1024*1024),b''):h.update(block)
    return h.hexdigest()


def verify(root):
    report=json.loads((root/'plant-relocation.json').read_text());base=root.parent/report['parent']
    parent_validation=json.loads((base/'validation.json').read_text());assert parent_validation['passed']
    prior=json.loads((base/'canonical/full/scene.json').read_text());scene=json.loads((root/'canonical/full/scene.json').read_text())
    catalog=json.loads((root/'tileset.json').read_text());old_catalog=json.loads((base/'tileset.json').read_text())
    assert scene['chunks']==prior['chunks'] and scene['materials']==prior['materials'] and scene['textures']==prior['textures']
    assert catalog['chunks']==old_catalog['chunks'],'No tile mesh may change in an instance-only correction'
    for c in scene['chunks']:assert digest(root/'canonical/full'/c['file'])==digest(base/'canonical/full'/c['file'])
    for c in catalog['chunks']:assert digest(root/c['file'])==digest(base/c['file'])
    unchanged_inputs=['placement-masks.json.gz','canonical/terrain.npz','canonical/road-height-field.npz']
    for name in unchanged_inputs:assert digest(root/name)==digest(base/name)
    scope=sh.Polygon(report['policy']['scopeEastNorth']);masks=json.loads(gzip.decompress((root/'placement-masks.json.gz').read_bytes()))
    green=sh.from_wkb(bytes.fromhex(next(r['geometry']for r in masks['finishedGround']if r['kind']=='grass')))
    obstacles=sh.union_all([sh.from_wkb(bytes.fromhex(g))for g in masks['root'].values()]);sh.prepare(obstacles)
    ground=LocalGround(root,scene,scope.buffer(report['policy']['maxMoveM']+35))
    changes={r['id']:r for r in report['records']};assert len(changes)==report['moved']
    packed={i['id']:i for t in catalog['tiles']for i in t['instances']}
    affected=0;maximum_error=0
    assert len(scene['instances'])==len(prior['instances'])
    plants=json.loads(gzip.decompress((root/'plant-placement-audit.json.gz').read_bytes()))
    audited={r['id']:r for r in plants['acceptedPoints']}
    for before,after in zip(prior['instances'],scene['instances']):
        assert before['mesh']==after['mesh']
        if before.get('id')not in changes:assert before==after;continue
        r=changes[before['id']];affected+=1
        assert before['matrix']==r['originalMatrix'] and after['matrix']==r['matrix']
        assert scope.covers(sh.Point(r['originalEastNorth']))
        assert not green.covers(sh.Point(r['originalEastNorth']).buffer(report['policy']['rootMarginM']))
        a,b=np.array(before['matrix']).reshape(3,4),np.array(after['matrix']).reshape(3,4)
        np.testing.assert_array_equal(a[:,:3],b[:,:3]);xy=[b[0,3],-b[2,3]]
        envelope=affinity.translate(sh.from_wkb(bytes.fromhex(r['envelopeWKB'])),*xy)
        assert green.covers(envelope) and not obstacles.intersects(envelope)
        assert r['shiftM']<=report['policy']['maxMoveM'] and r['shiftM']>0
        error=abs(ground.height(xy)-float(np.float32(b[1,3])));maximum_error=max(maximum_error,error);assert error<2e-5
        assert packed[before['id']]['matrix']==after['matrix']
        assert audited[before['id']]['matrix']==after['matrix'] and audited[before['id']]['originalMatrix']==before['matrix']
    assert affected==len(changes)
    for row in catalog['tiles']:
        for i in row['instances']:assert i['tileId']==row['id']
    result=dict(passed=True,adapter='yandex-2gis',parent=base.name,parentValidationSha256=digest(base/'validation.json'),
        plantInstances=report['plantCount'],movedPlants=affected,unchangedOtherInstances=len(scene['instances'])-affected,
        allCanonicalAndTileMeshesByteIdentical=True,terrainRoadFieldsAndMasksByteIdentical=True,
        changedRootsAndWholeCrownsOnGreen=True,maxSerializedRootErrorM=maximum_error,
        plantSourceXYPreserved=False,originalObservationsRetainedInAudit=True,chunks=len(catalog['chunks']),tiles=len(catalog['tiles']))
    dump(root/'validation.json',result);print(json.dumps(result),flush=True);return result

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);verify(p.parse_args().root)
