"""Check a survey plant supplement independently against its immutable parent."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import numpy as np
import shapely as sh
from pyproj import Transformer
from scipy.spatial import cKDTree
from build_scene import dump,BASE_SCALE
from street_placement import SurfaceSampler
from survey_plants import POLICY,source_model


def verify(root):
    report=json.loads((root/'survey-plants.json').read_text());base=root.parent/report['parent']
    before=json.loads((base/'canonical/full/scene.json').read_text())
    scene=json.loads((root/'canonical/full/scene.json').read_text())
    assert scene['chunks']==before['chunks'] and scene['materials']==before['materials']
    assert scene['instances'][:len(before['instances'])]==before['instances']
    for c in before['chunks']:
        assert (base/'canonical/full'/c['file']).read_bytes()==(root/'canonical/full'/c['file']).read_bytes()
    for name in ('terrain.npz','survey-field.npz','road-height-field.npz'):
        assert (base/'canonical'/name).read_bytes()==(root/'canonical'/name).read_bytes()
    assert (base/'placement-masks.json.gz').read_bytes()==(root/'placement-masks.json.gz').read_bytes()
    previous=json.loads(gzip.decompress((base/'plant-placement-audit.json.gz').read_bytes()))
    oldtree=cKDTree([p['eastNorth'] for p in previous['acceptedPoints']])
    m=json.loads(gzip.decompress((root/'placement-masks.json.gz').read_bytes()))
    green=sh.union_all([sh.from_wkb(bytes.fromhex(g['geometry'])) for g in m['finishedGround'] if g['kind'] in ('grass','cemetery')])
    city=json.loads((root/'canonical/urban-model.json').read_text());survey=json.loads((root/'survey-terrain.json').read_text())
    project=Transformer.from_crs(survey['projection'],city['crsProj'],always_xy=True)
    added={i['id']:i for i in scene['instances'][len(before['instances']):] if i['id'].startswith('survey-plant:')}
    accepted={r['id']:r for r in report['records'] if r['status']=='accepted'}
    assert set(added)==set(accepted) and len(added)==report['accepted']
    assert len(report['records'])==report['source']
    ground=SurfaceSampler(root,scene,{'land','road-curbs','green-curbs','curbs'})
    errors=[];xy=[];nearest=[]
    for key,inst in added.items():
        r=accepted[key];x,n=project.transform(*r['sourcePoint'][:2]);matrix=np.array(inst['matrix']).reshape(3,4)
        np.testing.assert_allclose(matrix[:,3][[0,2]],[x,-n],rtol=0,atol=1e-8)
        model=source_model(r);assert model is not None and scene['chunks'][inst['mesh']]['name']=='nuray-approved-'+model
        scale=np.linalg.norm(matrix[:,1]);assert BASE_SCALE[model]*.9<=scale<=BASE_SCALE[model]*1.1
        np.testing.assert_allclose(matrix[:,:3].T@matrix[:,:3],np.eye(3)*scale**2,atol=1e-12)
        np.testing.assert_allclose(matrix[:,1],[0,scale,0],atol=1e-12)
        assert green.covers(sh.Point(x,n))
        d=float(oldtree.query([x,n])[0]);assert d>=POLICY['existingSeparationM'];nearest.append(d)
        hit=ground.ground(x,-n);assert hit is not None
        errors.append(abs(hit['height']-matrix[1,3]));xy.append([x,n])
    newtree=cKDTree(xy);distance=newtree.query(xy,k=2)[0][:,1]
    assert distance.min()>=POLICY['newSeparationM']
    assert max(errors,default=0)<.001, max(errors)
    result=dict(passed=True,addedPlants=len(added),sourcePoints=report['source'],deferred=report['source']-len(added),
                parentMeshCount=len(before['chunks']),parentInstances=len(before['instances']),
                existingMeshesInstancesAndMaterialsIdentical=True,terrainSurveyRoadAndMasksIdentical=True,
                sourceXYPreserved=True,greenSurfaceOnly=True,allTrunksUpright=True,
                nearestExistingMinimumM=min(nearest),nearestAddedMinimumM=float(distance.min()),groundMaxErrorM=max(errors),
                modelDimensions='Approved display defaults, not measured CAD glyph dimensions')
    dump(root/'survey-plants-validation.json',result);print('SURVEY PLANTS VERIFIED',json.dumps(result),flush=True)
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);a=p.parse_args();verify(a.root)
