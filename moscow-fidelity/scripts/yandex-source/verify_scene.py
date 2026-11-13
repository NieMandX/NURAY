"""Provider-neutral serialized mesh and placement validation for mixed cities.

Do not label 2GIS-only source-style/portal checks as passed for a Yandex source.
Verify the actual transport contract: hashes, BVH leaves, source lineage,
materials, no duplication/loss from clipping, and instance identity.
"""
import argparse,gzip,hashlib,json,sys
from pathlib import Path
import numpy as np
import shapely as sh
from prepare_supplement import Terrain
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'prototype/tiling'))
from bvh_validation import validate
from object_geometry import decode_normals

def area(p):return np.linalg.norm(np.cross(p[:,1]-p[:,0],p[:,2]-p[:,0]),axis=1)/2

def main(root):
    catalog=json.loads((root/'tileset.json').read_text());source=json.loads((root/'canonical/full/scene.json').read_text());audit=json.loads((root/'canonical/validation.json').read_text());assert audit['passed']
    assert source['materials']==catalog['materials'];sources={};accum={};max_error=0.;triangles=0;nodes=0;wall_faces=0;collapsed_faces=0
    for c in source['chunks']:
        raw=gzip.decompress((root/'canonical/full'/c['file']).read_bytes());u=np.frombuffer(raw[:c['vertexBytes']],'<u4').reshape(-1,8);v=u.view('<f4');ix=np.frombuffer(raw[c['vertexBytes']:],'<u4').reshape(-1,3)
        assert len(ix)==c['triangles'] and np.isfinite(v[:,:3]).all() and np.isfinite(v[:,4:6]).all()
        assert (u[:,6]&0x7fffffff).max()<len(source['materials'])
        sources[c['id']]={'words':u,'ix':ix,'area':area(v[ix,:3].astype(float)),'material':u[ix[:,0],6]};accum[c['id']]=np.zeros(len(ix))
    for index,c in enumerate(catalog['chunks']):
        raw=gzip.decompress((root/c['file']).read_bytes());assert hashlib.sha256(raw).hexdigest()==c['sha256']
        vb,ib,nb,lb=[c[k] for k in ('vertexBytes','indexBytes','nodeBytes','lineageBytes')];assert len(raw)==vb+ib+nb+lb
        u=np.frombuffer(raw[:vb],'<u4').reshape(-1,8);v=u.view('<f4');ix=np.frombuffer(raw[vb:vb+ib],'<u4').reshape(-1,3);nf=np.frombuffer(raw[vb+ib:vb+ib+nb],'<f4').reshape(-1,8);nu=nf.view('<u4');lineage=np.frombuffer(raw[vb+ib+nb:],'<u4');s=sources[c['sourceChunk']]
        assert len(ix)==len(lineage)==c['triangles'] and ix.max()<len(v) and lineage.max()<len(s['area'])
        assert np.isfinite(v[:,:3]).all() and np.array_equal(u[ix[:,0],6],s['material'][lineage]) and np.all(u[ix,6]==u[ix[:,0],6,None])
        p=v[ix,:3].astype(float);validate(p,nf,nu)
        if c['name'] in ('buildings','survey-model-foundations','curbs','green-curbs','street-fences','road-curbs','waterfront-granite','waterfront-cornice','waterfront-parapet','road-cut-fill','road-entry-ramp-sides'):
            cross=np.cross(p[:,1]-p[:,0],p[:,2]-p[:,0]);area2=np.linalg.norm(cross,axis=1)
            # A clipped subpixel triangle can collapse onto its neighbour after
            # Float32 storage. It draws no pixels and has no front/back side.
            drawable=area2>0;collapsed_faces+=int((~drawable).sum());wall_faces+=int(drawable.sum())
            dot=(cross*decode_normals(u[ix[:,0],3])).sum(1)
            assert np.all(dot[drawable]>0),('Generated wall front/normal disagreement',c['id'])
        if c.get('instanced'):assert np.array_equal(u[ix],s['words'][s['ix'][lineage]])
        else:
            np.add.at(accum[c['sourceChunk']],lineage,area(p))
            original=s['words'].view('<f4')[s['ix'][lineage],:3].astype(float)
            normal=np.cross(original[:,1]-original[:,0],original[:,2]-original[:,0]);normal/=np.maximum(np.linalg.norm(normal,axis=1,keepdims=True),1e-20)
            err=np.abs(((p-original[:,0,None])*normal[:,None]).sum(2)).max(initial=0);max_error=max(max_error,float(err));assert err<.002,(c['id'],err)
        triangles+=len(ix);nodes+=len(nf)
        if index%400==0:print('VERIFY',index,'/',len(catalog['chunks']),flush=True)
    source_area=tile_area=0.;worst=0.
    for c in source['chunks']:
        if c.get('instanced'):continue
        expected=sources[c['id']]['area'];actual=accum[c['id']];source_area+=expected.sum();tile_area+=actual.sum();worst=max(worst,float(np.abs(expected-actual).max(initial=0)))
        # Float32 transport splits can differ by <1mm along long edges.
        assert np.all(np.abs(expected-actual)<np.maximum(.02,expected*.002)),(c['id'],float(np.abs(expected-actual).max()))
    original={i['id']:i for i in source['instances'] if 'id' in i};packed={}
    source_ids={c['id']:c['sourceChunk'] for c in catalog['chunks']}
    for tile in catalog['tiles']:
        for row in tile['instances']:
            assert row['id'] not in packed;packed[row['id']]=row
            assert original[row['id']]['matrix']==row['matrix'] and original[row['id']]['mesh']==source_ids[row['mesh']]
    assert set(original)==set(packed)
    masks=json.loads(gzip.decompress((root/'placement-masks.json.gz').read_bytes()))
    plants=json.loads(gzip.decompress((root/'plant-placement-audit.json.gz').read_bytes()))
    rows=plants['acceptedPoints'];xy=np.array([p['eastNorth'] for p in rows]);matrices=np.array([p['matrix'] for p in rows]).reshape(-1,3,4)
    plant_meshes={c['id'] for c in source['chunks'] if c.get('category')=='vegetation' or c['name'].startswith('nuray-approved-')}
    plant_ids={key for key,i in original.items() if i['mesh'] in plant_meshes}
    assert {p['id'] for p in rows}==plant_ids and len(rows)==len(plant_ids)
    assert plants['source']==plants['accepted']+plants['rejected']
    np.testing.assert_allclose(matrices[:,0,3],xy[:,0],atol=1e-8);np.testing.assert_allclose(matrices[:,2,3],-xy[:,1],atol=1e-8)
    scales=np.linalg.norm(matrices[:,:,:3],axis=1)[:,0];crowns=np.array([masks['crowns'][p['model']] for p in rows])*scales[:,None]
    radii=np.where(crowns[:,1]<2.5,np.maximum(.22,crowns[:,0]),.22);footprints=sh.buffer(sh.points(xy),radii,quad_segs=4)
    collision_counts={}
    for key,wkb in masks['root'].items():
        geometry=sh.from_wkb(bytes.fromhex(wkb));sh.prepare(geometry);hits=sh.intersects(geometry,footprints);collision_counts[key]=int(hits.sum());assert not hits.any(),key
    building_tree=sh.STRtree([sh.from_wkb(bytes.fromhex(p)) for p,h in masks['buildings']]);tops=np.array([h for p,h in masks['buildings']]);pi,bi=building_tree.query(sh.buffer(sh.points(xy),crowns[:,0],quad_segs=8),predicate='intersects')
    root_heights=matrices[:,1,3]+source['origin'][2];conflicts=tops[bi]>root_heights[pi]+crowns[pi,1]+1e-6
    assert not conflicts.any(),'Canopy intersects a building height';collision_counts['buildingCanopy']=int(conflicts.sum())
    terrain=Terrain(np.load(root/'canonical/terrain.npz')['triangles']);diff=root_heights-terrain.sample(xy)
    if (root/'paved-grade.json').exists():
        # Graded pavement/verges are a separate civil surface. In the local
        # area compare roots to serialized triangles, not the untouched DTM.
        from apply_paved_grade import FinishedGrade
        from street_placement import SurfaceSampler
        receipt=json.loads((root/'paved-grade.json').read_text())
        grade=FinishedGrade(root,root/'canonical/road-height-field.npz',receipt['settings'])
        local=grade.weight(xy)>0
        sampler=SurfaceSampler(root,source,{'land','road-curbs','green-curbs','curbs'})
        for j in np.flatnonzero(local):
            hit=sampler.ground(xy[j,0],-xy[j,1]);assert hit is not None
            assert abs(hit['height']-matrices[j,1,3])<.002,rows[j]['id']
        expected=np.zeros(len(xy));points=sh.points(xy)
        for entry in masks['finishedGround']:
            g=sh.from_wkb(bytes.fromhex(entry['geometry']));sh.prepare(g)
            expected[sh.covers(g,points)]=entry['offsetM']
        np.testing.assert_allclose(diff[~local],expected[~local],atol=1e-5)
    elif 'finishedGround' in masks:
        expected=np.zeros(len(xy));points=sh.points(xy)
        for entry in masks['finishedGround']:
            g=sh.from_wkb(bytes.fromhex(entry['geometry']));sh.prepare(g)
            expected[sh.covers(g,points)]=entry['offsetM']
        np.testing.assert_allclose(diff,expected,atol=1e-5)
    else:assert np.minimum(np.abs(diff),np.abs(diff-.1)).max()<1e-5
    report={'passed':True,'adapter':'yandex-2gis','checks':{'canonicalSourceChecks':audit['passed'],'allMeshHashes':True,'allBVHLeaves':True,'materialsAndLineage':True,'instanceTransformsAndCounts':True,'staticAreaConservation':True},'tiles':len(catalog['tiles']),'chunks':len(catalog['chunks']),'triangles':triangles,'nodes':nodes,'sourceAreaM2':source_area,'transportAreaM2':tile_area,'maxPrimitiveAreaErrorM2':worst,'maxPlaneErrorM':max_error,'plantInstances':len(plant_ids),'otherSharedInstances':len(packed)-len(plant_ids)}
    report['plantCollisions']=collision_counts;report['plantSourceXYPreserved']=True;report['plantRootsOnTerrainOrRaisedLawn']=True
    report['generatedFaceOrientation']={'checkedNondegenerateFaces':wall_faces,'normalWindingDisagreements':0,'collapsedClippedFaces':collapsed_faces}
    road_field=root/'canonical/road-height-field.npz'
    if road_field.exists():
        from audit_crossfall import audit as audit_crossfall
        field=np.load(road_field);report['roadCrossfall']=audit_crossfall(root,field['segments'],check_continuity=True)
        assert report['roadCrossfall']['maxDegrees']<=5,report['roadCrossfall']
    if (root/'survey-lamps.json').exists():
        from verify_survey_lamps import verify as verify_survey_lamps
        lamps=verify_survey_lamps(root)
        assert report['otherSharedInstances']==lamps['lamps']
        report['surveyLamps']={k:v for k,v in lamps.items() if k!='parentMeshesUnchanged'}
    if (root/'survey-plants.json').exists():
        from verify_survey_plants import verify as verify_survey_plants
        report['surveyPlants']=verify_survey_plants(root)
    if (root/'ravine-plants.json').exists():
        from verify_ravine_plants import verify as verify_ravine_plants
        report['ravinePlants']=verify_ravine_plants(root)
        report['plantSourceXYPreserved']='existing source plants unchanged; additional approximate infill separately audited'
    if (root/'paved-grade.json').exists():
        from verify_paved_grade import verify as verify_paved_grade
        report['pavedGrade']=verify_paved_grade(root)
    (root/'validation.json').write_text(json.dumps(report,indent=2)+'\n');print('VALIDATED',report,flush=True)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);main(p.parse_args().root)
