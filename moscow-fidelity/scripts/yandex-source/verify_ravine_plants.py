"""Independently verify approximate infill without changing any prior scene data."""
import argparse,gzip,hashlib,json,math
from pathlib import Path
import numpy as np
import shapely as sh
from scipy.spatial import cKDTree
from build_scene import dump
from street_placement import SurfaceSampler
from ravine_plants import POLICY

def verify(root):
    report=json.loads((root/'ravine-plants.json').read_text());base=root.parent/report['parent']
    before=json.loads((base/'canonical/full/scene.json').read_text());scene=json.loads((root/'canonical/full/scene.json').read_text())
    assert before['chunks']==scene['chunks'] and before['materials']==scene['materials']
    assert scene['instances'][:len(before['instances'])]==before['instances']
    for c in before['chunks']:
        assert hashlib.sha256((base/'canonical/full'/c['file']).read_bytes()).digest()==hashlib.sha256((root/'canonical/full'/c['file']).read_bytes()).digest()
    for name in ('canonical/terrain.npz','canonical/survey-field.npz','canonical/road-height-field.npz','placement-masks.json.gz'):
        assert (base/name).read_bytes()==(root/name).read_bytes()
    added={r['id']:r for r in scene['instances'][len(before['instances']):]}
    records={r['id']:r for r in report['records'] if r['status']=='accepted'};assert set(added)==set(records)
    previous=json.loads(gzip.decompress((base/'plant-placement-audit.json.gz').read_bytes()));old=cKDTree([p['eastNorth'] for p in previous['acceptedPoints']])
    masks=json.loads(gzip.decompress((root/'placement-masks.json.gz').read_bytes()))
    green=sh.union_all([sh.from_wkb(bytes.fromhex(g['geometry'])) for g in masks['finishedGround'] if g['kind'] in ('grass','cemetery')]).buffer(-POLICY['greenEdgeClearanceM'])
    zones={z['id']:sh.Polygon(z['polygon']) for z in report['evidence']['zones']}
    ground=SurfaceSampler(root,scene,{'land','road-curbs','green-curbs','curbs'});errors=[];xy=[];spacing=[]
    for key,inst in added.items():
        r=records[key];x,n=r['eastNorth'];m=np.array(inst['matrix']).reshape(3,4);s=r['scale']
        assert inst['matrix']==r['matrix'];assert scene['chunks'][inst['mesh']]['name']=='nuray-approved-'+r['model']
        assert green.covers(sh.Point(x,n)) and zones[r['zone']].covers(sh.Point(x,n))
        assert old.query([x,n])[0]>=r['separationM']
        np.testing.assert_allclose(m[:,:3].T@m[:,:3],np.eye(3)*s*s,rtol=0,atol=1e-12)
        np.testing.assert_allclose(m[:,1],[0,s,0],rtol=0,atol=1e-12)
        hit=ground.ground(x,-n);assert hit;errors.append(abs(hit['height']-m[1,3]));xy.append([x,n]);spacing.append(r['separationM'])
    xy=np.array(xy);spacing=np.array(spacing);d=np.linalg.norm(xy[:,None]-xy[None,:],axis=2);np.fill_diagonal(d,np.inf)
    assert np.all(d>=np.maximum(spacing[:,None],spacing[None,:])-1e-8);assert max(errors)<.001
    result=dict(passed=True,addedPlants=len(added),byModel=report['acceptedByModel'],parentInstancesUnchanged=len(before['instances']),allParentGeometryAndMaterialsUnchanged=True,terrainSurveyAndRoadFieldsIdentical=True,confirmedGreenOnly=True,greenMarginM=POLICY['greenEdgeClearanceM'],groundMaxErrorM=max(errors),nearestNewMinimumM=float(d.min()),coordinates='approximate panorama-guided infill, not survey')
    dump(root/'ravine-plants-validation.json',result);print('RAVINE VERIFIED',json.dumps(result),flush=True);return result

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);verify(p.parse_args().root)
