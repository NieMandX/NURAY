"""Verify serialized lamp positions, physical collisions and city invariants."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import numpy as np
import shapely as sh
from pyproj import Transformer
from build_scene import dump
from street_placement import SurfaceSampler
from survey_lamps import POLICY


def verify(root):
    report=json.loads((root/'survey-lamps.json').read_text())
    base=root.parent/report['parent']
    before=json.loads((base/'canonical/full/scene.json').read_text())
    scene=json.loads((root/'canonical/full/scene.json').read_text())
    assert scene['chunks'][:len(before['chunks'])]==before['chunks']
    assert scene['instances'][:len(before['instances'])]==before['instances']
    assert scene['materials'][:len(before['materials'])]==before['materials']
    unchanged=[]
    for c in before['chunks']:
        old=(base/'canonical/full'/c['file']).read_bytes()
        assert (root/'canonical/full'/c['file']).read_bytes()==old
        unchanged.append(dict(file=c['file'],sha256=hashlib.sha256(old).hexdigest()))
    for n in ('terrain.npz','survey-field.npz','road-height-field.npz'):
        assert (base/'canonical'/n).read_bytes()==(root/'canonical'/n).read_bytes()
    m=json.loads(gzip.decompress((root/'placement-masks.json.gz').read_bytes()))
    masks={k:sh.from_wkb(bytes.fromhex(v)) for k,v in m['root'].items()}
    road=sh.union_all([sh.from_wkb(bytes.fromhex(v['geometry'])) for v in m['finishedGround'] if v['kind'] in ('road','parking')])
    btree=sh.STRtree([sh.from_wkb(bytes.fromhex(p)) for p,h in m['buildings']])
    tops=np.array([h for p,h in m['buildings']])
    ground=SurfaceSampler(root,scene,{'land','road-curbs','green-curbs','curbs'})
    city=json.loads((root/'canonical/urban-model.json').read_text())
    survey=json.loads((root/'survey-terrain.json').read_text())
    project=Transformer.from_crs(survey['projection'],city['crsProj'],always_xy=True)
    templates={}
    for c in scene['chunks'][len(before['chunks']):]:
        raw=gzip.decompress((root/'canonical/full'/c['file']).read_bytes())
        v=np.frombuffer(raw[:c['vertexBytes']],'<f4').reshape(-1,8)[:,:3]
        ix=np.frombuffer(raw[c['vertexBytes']:],'<u4').reshape(-1,3)
        templates[c['id']]=v[ix].astype(float)
    # A downstream scene may append separately validated survey vegetation.
    # Lamp ownership is explicit; the provider-neutral verifier still checks
    # every instance, and each supplement verifies its own parent prefix.
    added={r['id']:r for r in scene['instances'][len(before['instances']):]
           if r.get('id','').startswith('survey-lamp:')}
    accepted={r['sourceId']:r for r in report['records'] if r['status']=='accepted'}
    assert set(added)==set(accepted) and len(added)==report['accepted']
    assert len(report['records'])==report['source']
    heights=[]
    for key,inst in added.items():
        row=accepted[key];x,n=project.transform(*row['sourcePoint'][:2])
        matrix=np.array(inst['matrix']).reshape(3,4)
        np.testing.assert_allclose(matrix[:,3][[0,2]],[x,-n],rtol=0,atol=1e-8)
        np.testing.assert_allclose(matrix[:,:3].T@matrix[:,:3],np.eye(3),rtol=0,atol=1e-12)
        np.testing.assert_allclose(matrix[:,1],[0,1,0],rtol=0,atol=1e-12)
        point=sh.Point(x,n)
        assert all(masks[k].distance(point)>=POLICY['baseRadiusM'] for k in ('building','water'))
        assert not road.covers(point)
        hit=ground.ground(x,-n);assert hit is not None
        heights.append(abs(hit['height']-matrix[1,3]))
        w=templates[inst['mesh']]@matrix[:,:3].T+matrix[:,3]
        polys=sh.polygons(w[:,:,[0,2]]*[1,-1])
        pi,bi=btree.query(polys,predicate='intersects')
        assert np.all(w[pi,:,1].min(1)+scene['origin'][2]>=tops[bi]-.01),('Lamp/building overlap',key)
    assert max(heights,default=0)<.001
    result=dict(passed=True,lamps=len(added),sourcePoints=report['source'],
                deferred=report['source']-len(added),parentMeshesUnchanged=unchanged,
                parentInstanceCount=len(before['instances']),parentInstancesIdentical=True,
                terrainSurveyAndRoadFieldsIdentical=True,sourceXYPreserved=True,
                allPolesUpright=True,groundContactMaxErrorM=max(heights,default=0),
                waterBuildingRoadRootCollisions=0,luminaireBuildingCollisions=0,
                dimensionsAndOrientation='display estimates; not survey measurements')
    dump(root/'survey-lamps-validation.json',result)
    print('LAMPS VERIFIED',json.dumps({k:v for k,v in result.items() if k!='parentMeshesUnchanged'}),flush=True)
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);a=p.parse_args();verify(a.root)
