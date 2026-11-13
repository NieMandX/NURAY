"""Independent receipts for a civil surface above immutable survey terrain."""
import argparse, gzip, hashlib, json
from pathlib import Path
import numpy as np
import shapely as sh
from scipy.spatial import cKDTree
from apply_crossfall import unpack,RoadField
from apply_paved_grade import FinishedGrade
from survey_terrain import safe_sample
from street_placement import SurfaceSampler

def digest(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        while b:=f.read(8*1024*1024):h.update(b)
    return h.hexdigest()

def verify(root):
    receipt=json.loads((root/'paved-grade.json').read_text());base=root.parent/receipt['parent']
    scene=json.loads((root/'canonical/full/scene.json').read_text());parent=json.loads((base/'canonical/full/scene.json').read_text())
    unchanged=[]
    for name in ('canonical/terrain.npz','canonical/survey-field.npz','survey-terrain.json','survey-outliers.json'):
        assert digest(root/name)==digest(base/name),name
        unchanged.append(name)
    for name,h in receipt['historicalReceipts'].items():
        assert digest(root/'prior-stages'/name)==h==digest(base/name),name
    grade=FinishedGrade(base,root/'canonical/road-height-field.npz',receipt['settings'])
    collar=np.load(root/'canonical/finished-grade-field.npz');h=collar['height']
    assert np.isfinite(h).all()
    rng=np.random.default_rng(711);cy=rng.integers(1,len(collar['y'])-1,8000);cx=rng.integers(1,len(collar['x'])-1,8000)
    q=np.column_stack([collar['x'][cx],collar['y'][cy]])
    distance=grade.road.sample(q)[2]
    interior=(distance>2)&(distance<26)&(np.linalg.norm(q-grade.center,axis=1)<grade.outer)
    cy,cx=cy[interior],cx[interior];assert len(cy)>100
    residual=abs(4*h[cy,cx]-h[cy-1,cx]-h[cy+1,cx]-h[cy,cx-1]-h[cy,cx+1])
    assert residual.max()<1e-5,('Discontinuous off-road collar',residual.max())
    road=np.load(root/'canonical/road-height-field.npz');road_xy=road['xy'].reshape(-1,2);road_z=road['z'].ravel();road_tree=cKDTree(road_xy);field=RoadField(root/'canonical/road-height-field.npz')
    road_error=0.;road_vertices=0;inherited_overhang=0.
    old={c['id']:c for c in parent['chunks']};rigid=[];roof_vertices=0;foot_errors=[]
    for c in scene['chunks']:
        if c['name']=='land':
            t,m,_=unpack(root/'canonical/full',c);t=t[m==0]
            if len(t):
                q=t[:,:,[0,2]].reshape(-1,2)*[1,-1];distance,index=road_tree.query(q)
                expected=road_z[index].copy();split=distance>1e-5
                if split.any():
                    dz,z,offroad=field.sample(q[split])
                    beyond=offroad>.001
                    if beyond.any():
                        # Earlier serialized road/ramp joins contain
                        # overhangs beyond the solver TIN. The application
                        # evaluates them on the nearest edge. A material cut
                        # may insert vertices inside these existing faces;
                        # require containment in the parent road footprint.
                        assert c['id'] in old
                        a,am,_=unpack(base/'canonical/full',old[c['id']]);oldxy=a[am==0][:,:,[0,2]]*[1,-1]
                        oldpolys=sh.polygons(oldxy);oldtree=sh.STRtree(oldpolys);points=sh.points(q[split][beyond])
                        delta=sh.distance(points,oldpolys[oldtree.nearest(points)])
                        assert delta.max()<.001,('Expanded road footprint',c['id'],float(delta.max()),q[split][beyond][int(delta.argmax())].tolist())
                        inherited_overhang=max(inherited_overhang,float(offroad.max()))
                    expected[split]=dz+z
                err=float(abs(t[:,:,1].ravel()-expected).max(initial=0));assert err<.001,(c['id'],err)
                road_error=max(road_error,err);road_vertices+=len(q)
        if c['id'] not in old:continue
        p=old[c['id']]
        if c.get('instanced') or c['name'] in ('water','landmarks','transport-structures','transport-approaches','rails'):
            assert digest(root/'canonical/full'/c['file'])==digest(base/'canonical/full'/p['file']),c['name']
            rigid.append(c['id'])
        if c['name'] not in ('buildings','survey-model-foundations'):continue
        a,am,ac=unpack(base/'canonical/full',p);b,bm,bc=unpack(root/'canonical/full',c)
        assert np.array_equal(am,bm) and np.array_equal(ac,bc)
        assert np.array_equal(a[:,:,[0,2]],b[:,:,[0,2]])
        xy=a[:,:,[0,2]]*[1,-1];q=xy.reshape(-1,2)
        nat=safe_sample(grade.terrain,q).reshape(-1,3)-grade.alt
        feet=abs(a[:,:,1]-nat)<.003
        np.testing.assert_array_equal(a[:,:,1][~feet],b[:,:,1][~feet]);roof_vertices+=int((~feet).sum())
        expected=a[:,:,1]+grade.delta(q).reshape(-1,3)*feet
        err=abs(b[:,:,1]-expected);assert err.max(initial=0)<.0001,(c['id'],err.max())
        foot_errors.extend(err[feet].tolist())
    previous={i['id']:i for i in parent['instances'] if 'id' in i}
    current={i['id']:i for i in scene['instances'] if 'id' in i}
    recovery=json.loads((root/'recovered-square-plants.json').read_text()) if (root/'recovered-square-plants.json').exists() else {'records':[]}
    recovered={r['id']:r for r in recovery['records']}
    conflicts=json.loads((root/'graded-plant-conflicts.json').read_text()) if (root/'graded-plant-conflicts.json').exists() else {'records':[]}
    deferred={r['id']:r for r in conflicts['records']}
    if recovered:
        from build_scene import BASE_SCALE
        src=Path(__file__).resolve().parents[3]/recovery['sourceFile'];assert digest(src)==recovery['sourceSha256']
        observations={p['id']:p for p in json.loads(gzip.decompress(src.read_bytes()))}
        for key,r in recovered.items():
            p=observations[key];assert p['approvedModel']==r['model']
            np.testing.assert_array_equal(p['eastNorth'],r['eastNorth'])
            s=BASE_SCALE[r['model']]*p['scale'];angle=p['yawRadians'];c,si=np.cos(angle)*s,np.sin(angle)*s
            expected=[c,0,si,0,s,0,-si,0,c]
            np.testing.assert_allclose(np.array(r['matrix']).reshape(3,4)[:,:3].ravel(),expected,atol=1e-12)
    assert not set(previous)&set(recovered)
    assert (set(previous)|set(recovered))-set(deferred)==set(current)
    sampler=SurfaceSampler(root,scene,{'land','road-curbs','green-curbs','curbs'});contact=[]
    keep=[0,1,2,3,4,5,6,8,9,10,11]
    for key,row in current.items():
        b=np.array(row['matrix'])
        if key in previous:
            a=np.array(previous[key]['matrix'])
            assert row['mesh']==previous[key]['mesh'];np.testing.assert_array_equal(a[keep],b[keep])
        else:
            r=recovered[key];np.testing.assert_array_equal(b,np.array(r['matrix']))
            np.testing.assert_array_equal(b[[3,11]],np.array(r['eastNorth'])*[1,-1])
        if grade.weight(np.array([[b[3],-b[11]]]))[0]>0:
            hit=sampler.ground(b[3],b[11]);assert hit is not None,key
            contact.append(abs(hit['height']-b[7]));assert contact[-1]<.002,(key,contact[-1])
        else:assert key in previous and a[7]==b[7],key
    marks=np.load(root/'canonical/survey-field.npz')['marks']
    mark_error=abs(safe_sample(grade.terrain,marks[:,:2])-marks[:,2]);assert mark_error.max()<.002
    masks=json.loads(gzip.decompress((root/'placement-masks.json.gz').read_bytes()))
    for key,r in deferred.items():
        assert key in previous or key in recovered
        matrix=np.array(r['matrix']).reshape(3,4);scale=np.linalg.norm(matrix[:,:3],axis=0)[0]
        radius,low=np.array(masks['crowns'][r['model']])*scale;bottom=matrix[1,3]+scene['origin'][2]+low
        crown=sh.Point(r['eastNorth']).buffer(radius,quad_segs=8)
        hits=[h for p,h in masks['buildings'] if h>bottom+1e-6 and sh.from_wkb(bytes.fromhex(p)).intersects(crown)]
        assert hits,('Unsubstantiated deferred plant',key)
    finish={r['kind']:sh.from_wkb(bytes.fromhex(r['geometry'])) for r in masks['finishedGround']}
    assert finish['grass'].intersection(finish['ped']).area<.001
    assert finish['parking'].intersection(finish['ped']).area<.001
    result=dict(passed=True,immutableFiles=unchanged,historicalReceipts=len(receipt['historicalReceipts']),
      waterAuthoredStructuresAndTemplatesByteIdentical=rigid,retainedSurveyMarks=len(marks),surveyMarkMaxErrorM=float(mark_error.max()),
      unchangedRoofAndUpperBuildingVertices=roof_vertices,footingAdjustmentMaxErrorM=max(foot_errors,default=0),
      sourceInstanceIDsXYScaleYawPreserved=len(set(previous)-set(deferred)),recoveredSourcePlants=len(recovered),sourcePlantsDeferredAfterGrading=len(deferred),checkedFinishedGroundContacts=len(contact),contactMaxErrorM=max(contact,default=0),
      serializedRoadVerticesMatchingSolvedGrade=road_vertices,roadGradeMaxErrorM=road_error,inheritedRoadFootprintOverhangM=inherited_overhang,
      continuousCollarCheckedCells=len(cy),continuousCollarMaxResidualM=float(residual.max()),
      restoredSourceGreenM2=receipt['restoredSourceGreenM2'],restoredSourceParkingM2=receipt['restoredSourceParkingM2'],pavingM2=receipt['pavingM2'])
    (root/'paved-grade-validation.json').write_text(json.dumps(result,indent=2)+'\n')
    receipt['passed']=True;(root/'paved-grade.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n')
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);print(json.dumps(verify(p.parse_args().root),indent=2))
