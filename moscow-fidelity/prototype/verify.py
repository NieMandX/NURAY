"""Independent verification of serialized WebGPU buffers and GLB, not just build arrays."""
from pathlib import Path
import gzip,json,struct
import numpy as np
import shapely as sh
from shapely.geometry import shape
from shapely.ops import substring

BASE=Path(__file__).resolve().parents[1]/'web-preview/prototype/assets'
city=json.loads((BASE/'urban-model.json').read_text());report=json.loads((BASE/'validation.json').read_text())
assert report['passed'],report
surfaces=city['surfaces'];tree=sh.STRtree([shape(s['geometry']).buffer(.00005) for s in surfaces]);planes=np.array([s['heightPlane'] for s in surfaces])
previous=json.loads((BASE/'urban-model-terrain.json').read_text())
old_road=sh.union_all([shape(s['geometry']) for s in previous['surfaces'] if s['kind']=='roadbed_flat'])
new_road=sh.union_all([shape(s['geometry']) for s in surfaces if s['kind']=='roadbed_flat'])
repairs=sh.union_all([shape(r['geometry']) for r in city['roadSlitRepairs']])
connectors=sh.union_all([shape(r['connectorGeometry']) for r in city['gradeConnections']])
removed=old_road.difference(new_road).area
unexpected=new_road.difference(sh.union_all([old_road,repairs,connectors])).area
missing_repairs=repairs.difference(new_road).area
assert removed<.01 and unexpected<.01 and missing_repairs<.01,(removed,unexpected,missing_repairs)
for r in city['roadSlitRepairs']:
    assert len(r['sourceParents'])>=2
    if r['type']=='junction-wedge':
        assert r['junctions'] and new_road.covers(shape(r['geometry']).representative_point())
origin=np.array(city['originMSK']);output={};paint_count=0;max_paint_error=0.;road_shading_count=0;max_normal_seam=0.
smooth=json.loads((BASE/'urban-model-smooth.json').read_text())
old_ground=[s for s in smooth['surfaces'] if s['kind'] in ['land','roadbed_flat']]
ground_tree=sh.STRtree([shape(s['geometry']).buffer(.00005) for s in old_ground])
ground_planes=np.array([s['heightPlane'] for s in old_ground])
normal_check_road=new_road.buffer(.0001);sh.prepare(normal_check_road)
raised_count=0;front_count=0;max_raise_error=0.;max_curb_error=0.;serialized_front=[];serialized_land=[]
profile_support=[]
for p in city['overpassProfiles']:
    assert p['shoulderRaiseM']==.10 and p['parapetTopAboveRoadM']==.70
    profile_support.extend([s for s in surfaces if s['kind']=='roadbed_overpass' and s['owner'] in set(p['sourceParents'])])
    profile_support.extend([{**s,'kind':'shoulder'} for s in p['extensionHeightCells']])
profile_tree=sh.STRtree([shape(s['geometry']).buffer(.0001) for s in profile_support])
profile_planes=np.array([s['heightPlane'] for s in profile_support])
structure_count=0;max_structure_error=0.;structure_footprints={k:[] for k in ['overpass_bottom','overpass_shoulder','parapet_top']}
structure_lines={k:[] for k in ['overpass_side','overpass_riser','parapet_side']}
serialized_shoulders=[]
for version in ['before','terrain','smooth','structure','after']:
    folder=BASE/version;scene=json.loads((folder/'scene.json').read_text());count=0
    for c in scene['chunks']:
        raw=gzip.decompress((folder/Path(c['file']).name).read_bytes())
        assert len(raw)==c['vertexBytes']+c['triangles']*12
        v=np.frombuffer(raw[:c['vertexBytes']],'<f4').reshape(-1,8)
        ix=np.frombuffer(raw[c['vertexBytes']:],'<u4').reshape(-1,3)
        assert len(v)==c['vertexCount'] and ix.max()<len(v)
        assert np.isfinite(v[:,:3]).all()
        mi=v.view('<u4')[:,6];assert (mi&0x80000000).all() and (mi&0x7fffffff).max()<len(scene['materials'])
        tri=v[ix,:3].astype(float);assert np.all(np.linalg.norm(np.cross(tri[:,1]-tri[:,0],tri[:,2]-tri[:,0]),axis=1)>1e-9)
        count+=len(ix)
        if version=='after' and c['name'] in ['overpass_bottom','overpass_shoulder','overpass_side','overpass_riser','parapet_top','parapet_side']:
            world=tri[:,:,[0,2,1]]*np.array([1,-1,1])+origin
            for t in world:
                ids=profile_tree.query(sh.Point(t[:,:2].mean(0)),predicate='covered_by')
                errors=[]
                for i in ids:
                    offsets=t[:,2]-(t[:,:2]@profile_planes[i,:2]+profile_planes[i,2])
                    if c['name'] in ['overpass_bottom','overpass_shoulder','parapet_top']:
                        expected={'overpass_bottom':-1.,'overpass_shoulder':.10,'parapet_top':.70}[c['name']]
                        errors.append(float(np.max(abs(offsets-expected))))
                    else:
                        if c['name']=='overpass_side':
                            low,high=-1.,0. if profile_support[i]['kind']=='roadbed_overpass' else .10
                        elif c['name']=='overpass_riser':low,high=0.,.10
                        else:low,high=.10,.70
                        if abs(offsets.min()-low)<.001 and abs(offsets.max()-high)<.001:
                            errors.append(float(np.max(np.minimum(abs(offsets-low),abs(offsets-high)))))
                assert errors and min(errors)<.001,(c['name'],t,min(errors,default=None))
                max_structure_error=max(max_structure_error,min(errors));structure_count+=1
                if c['name'] in structure_footprints:structure_footprints[c['name']].append(sh.Polygon(t[:,:2]))
                if c['name']=='overpass_shoulder':serialized_shoulders.append(t)
                if c['name'] in structure_lines:
                    xy=np.unique(t[:,:2],axis=0);assert len(xy)==2
                    structure_lines[c['name']].append(sh.LineString(xy))
        if version=='after' and c['name'] in ['land','curb_top','curb_front']:
            world=tri[:,:,[0,2,1]]*np.array([1,-1,1])+origin
            for t in world:
                ids=ground_tree.query(sh.Point(t[:,:2].mean(0)),predicate='covered_by')
                if c['name']=='curb_front':
                    errors=[]
                    for i in ids:
                        levels=t[:,2]-(t[:,:2]@ground_planes[i,:2]+ground_planes[i,2])
                        error=float(np.max(np.minimum(abs(levels),abs(levels-.10))))
                        if abs(levels.min())<.001 and abs(levels.max()-.10)<.001: errors.append(error)
                    assert errors and min(errors)<.001,(c['name'],t,errors)
                    max_curb_error=max(max_curb_error,min(errors));front_count+=1
                    xy=np.unique(t[:,:2],axis=0);assert len(xy)==2
                    serialized_front.append(sh.LineString(xy))
                    n=np.cross(t[1]-t[0],t[2]-t[0]);n=n[:2]/np.linalg.norm(n[:2])
                    assert normal_check_road.covers(sh.Point(t[:,:2].mean(0)+n*.001)),('curb face reversed',t)
                else:
                    errors=[float(np.max(np.abs(t[:,2]-(t[:,:2]@ground_planes[i,:2]+ground_planes[i,2])-.10))) for i in ids]
                    assert errors and min(errors)<.001,(c['name'],t,min(errors,default=None))
                    max_raise_error=max(max_raise_error,min(errors));raised_count+=1
                    serialized_land.append(sh.Polygon(t[:,:2]))
        if version=='after' and c['name']=='roadbed_flat':
            octn=np.frombuffer(raw[:c['vertexBytes']],'<i2').reshape(-1,16)[:,6:8].astype(float)/32767
            normal=np.column_stack([octn,1-np.abs(octn).sum(1)])
            t=np.clip(-normal[:,2],0,1)
            normal[:,:2]+=np.where(normal[:,:2]>=0,-t[:,None],t[:,None])
            normal/=np.linalg.norm(normal,axis=1,keepdims=True)
            assert np.isfinite(normal).all() and np.all(normal[:,1]>.95)
            face=np.cross(tri[:,1]-tri[:,0],tri[:,2]-tri[:,0]);face/=np.linalg.norm(face,axis=1,keepdims=True)
            assert np.all(np.sum(normal[ix]*face[:,None,:],axis=2)>.995)
            # At duplicate serialized positions, shading must have the same normal.
            _,inverse=np.unique(v[:,:3],axis=0,return_inverse=True)
            lo=np.full((inverse.max()+1,3),np.inf);hi=-lo.copy()
            np.minimum.at(lo,inverse,normal);np.maximum.at(hi,inverse,normal)
            max_normal_seam=max(max_normal_seam,float(np.max(np.linalg.norm(hi-lo,axis=1))))
            assert max_normal_seam<.001
            road_shading_count+=len(tri)
        if version=='after' and c['name']=='paint':
            world=tri[:,:,[0,2,1]]*np.array([1,-1,1])+origin
            for t in world:
                ids=tree.query(sh.Point(t[:,:2].mean(0)),predicate='covered_by')
                errors=[float(np.max(np.abs(t[:,2]-(t[:,:2]@planes[i,:2]+planes[i,2])-.003))) for i in ids]
                assert errors and min(errors)<.001,(t,min(errors,default=None))
                max_paint_error=max(max_paint_error,min(errors));paint_count+=1
    assert count==scene['stats']['uniqueTriangles']
    glb=(folder/'model.glb').read_bytes();magic,ver,size=struct.unpack_from('<4sII',glb)
    assert magic==b'glTF' and ver==2 and size==len(glb)
    jsize,jtype=struct.unpack_from('<I4s',glb,12);assert jtype==b'JSON'
    g=json.loads(glb[20:20+jsize]);bsize,btype=struct.unpack_from('<I4s',glb,20+jsize);assert btype==b'BIN\0'
    assert sum(g['accessors'][m['primitives'][0]['attributes']['POSITION']]['count']//3 for m in g['meshes'])==count
    assert all(b['byteOffset']+b['byteLength']<=bsize for b in g['bufferViews'])
    assert scene['materials'][3]['color']==[.96,.96,.96] and scene['materials'][4]['color']==[1.,.93,.045]
    assert max(max(m['color']) for i,m in enumerate(scene['materials']) if i not in [3,4,5])<=.65
    output[version]=dict(triangles=count,chunks=len(scene['chunks']),glbValid=True)
# Compare the actual serialized vertical faces to the curb band's road-facing
# boundary; a correct JSON declaration cannot hide omitted faces in the buffers.
serialized_front=sh.union_all(serialized_front)
extent=sh.box(*city['boundsMSK']);opening=sh.union_all([shape(s['geometry']) for s in surfaces if s['kind']=='roadbed_tunnel_descent'])
expected_front=shape(city['curbBandGeometry']).boundary.intersection(new_road.boundary.buffer(.0001))
expected_front=expected_front.difference(extent.boundary.buffer(.0001)).difference(opening.buffer(.0001))
missing_front=expected_front.difference(serialized_front.buffer(.0001)).length
assert front_count>0 and raised_count>0 and missing_front<.001,missing_front
actual_land=sh.union_all(serialized_land,grid_size=.00001)
cut=shape(city['transitionTerrainCutGeometry'])
land_in_cut=actual_land.intersection(cut).area
assert land_in_cut<.01,('Serialized raised terrain intersects ramp slab',land_in_cut)
mouth_checks=[]
actual_shoulder=sh.union_all(structure_footprints['overpass_shoulder'],grid_size=.00001)
for connection in city['gradeConnections']:
    line=shape(connection['mouthGeometry']);gate=substring(line,.05,line.length-.05).buffer(.001,cap_style='flat')
    land_area=actual_land.intersection(gate).area
    curb_length=serialized_front.intersection(gate).length
    riser_length=sh.union_all(structure_lines['overpass_riser']).intersection(gate).length
    shoulder_area=actual_shoulder.intersection(gate).area
    assert land_area<.0001 and curb_length<.001 and riser_length<.001 and shoulder_area<.0001,(connection['id'],land_area,curb_length,riser_length,shoulder_area)
    mouth_checks.append(dict(id=connection['id'],raisedLandInPassageM2=land_area,curbFrontInPassageM=curb_length,
                            shoulderRiserInPassageM=riser_length,raisedShoulderInPassageM2=shoulder_area))
structure_area_errors={}
for name,key in [('overpass_bottom','deckGeometry'),('overpass_shoulder','shoulderGeometry'),('parapet_top','parapetGeometry')]:
    actual=sh.union_all(structure_footprints[name],grid_size=.00001)
    expected=sh.union_all([shape(p[key]) for p in city['overpassProfiles']],grid_size=.00001)
    error=actual.symmetric_difference(expected).area
    assert error<.05,(name,error)
    structure_area_errors[name]=error
actual_deck=sh.union_all(structure_footprints['overpass_bottom'],grid_size=.00001)
asphalt=sh.union_all([shape(p['asphaltGeometry']) for p in city['overpassProfiles']])
# An entry can be open yet still have a detached concrete island just outside
# the gate. Check exported components against their actual asphalt core too.
detached_area=sum(part.area for part in sh.get_parts(actual_deck)
    if part.area>.0001 and part.intersection(asphalt.buffer(.00005)).area<.0001)
assert detached_area<.0001,('Detached exported concrete island',detached_area)
assert structure_count>0
# Independent mouth-end check: compare the exported raised shoulder roofs to
# the common ground height datum, rather than trusting generator join metrics.
shoulder_tree=sh.STRtree([sh.Polygon(t[:,:2]).buffer(.0001) for t in serialized_shoulders])
max_ground_shoulder_error=0.;ground_shoulder_samples=0
for p in city['overpassProfiles']:
    profile_samples=0
    for line in sh.get_parts(shape(p['groundShoulderConnectionGeometry'])):
        if line.geom_type!='LineString':continue
        for distance in np.linspace(0,line.length,12):
            point=line.interpolate(distance);xy=np.array(point.coords)[0]
            a=shoulder_tree.query(point,predicate='covered_by');b=ground_tree.query(point,predicate='covered_by')
            if not len(a):continue  # The outer 20 cm is parapet, not shoulder roof.
            errors=[]
            for i in a:
                t=serialized_shoulders[int(i)];basis=t[1:,:2]-t[0,:2]
                if abs(np.linalg.det(basis))<1e-10:continue
                slope=np.linalg.solve(basis,t[1:,2]-t[0,2])
                height=t[0,2]+(xy-t[0,:2])@slope
                for j in b:errors.append(abs(float(height-(xy@ground_planes[j,:2]+ground_planes[j,2]+.10))))
            assert errors and min(errors)<.001,(p['level'],xy,min(errors,default=None))
            max_ground_shoulder_error=max(max_ground_shoulder_error,min(errors));profile_samples+=1
    assert profile_samples>0,('No serialized shoulder-ground join samples',p['level'])
    ground_shoulder_samples+=profile_samples
structure_missing_sides={}
for name,key in [('overpass_side','deckGeometry'),('overpass_riser','shoulderRiserGeometry'),('parapet_side','parapetGeometry')]:
    actual=sh.union_all(structure_lines[name])
    expected=sh.union_all([shape(p[key]) if name=='overpass_riser' else shape(p[key]).boundary for p in city['overpassProfiles']])
    expected=expected.difference(extent.boundary.buffer(.0001))
    missing=expected.difference(actual.buffer(.0001)).length
    assert missing<.001,(name,missing)
    structure_missing_sides[name]=missing
output.update(serializedPaintTrianglesChecked=paint_count,maxSerializedPaintHeightErrorM=max_paint_error,
    serializedGroundShoulderJoinSamples=ground_shoulder_samples,maxSerializedGroundShoulderJoinErrorM=max_ground_shoulder_error,
    serializedGradeConnections=mouth_checks,serializedRaisedLandInsideRampCutM2=land_in_cut,
    serializedOverpassStructureTrianglesChecked=structure_count,maxSerializedStructureHeightErrorM=max_structure_error,
    structureFootprintDifferenceM2=structure_area_errors,
    detachedSerializedConcreteAreaM2=detached_area,
    uncoveredSerializedStructureSidesM=structure_missing_sides,
    serializedRaisedGroundTrianglesChecked=raised_count,maxSerializedGroundRaiseErrorM=max_raise_error,
    serializedCurbFrontTrianglesChecked=front_count,maxSerializedCurbHeightErrorM=max_curb_error,
    uncoveredSerializedCurbFrontM=missing_front,
    serializedSmoothRoadTrianglesChecked=road_shading_count,maxSerializedNormalDiscontinuity=max_normal_seam,
    contourRepairCount=len(city['roadSlitRepairs']),removedRoadAreaM2=removed,
    unaccountedAddedRoadAreaM2=unexpected,uncoveredRepairAreaM2=missing_repairs,passed=True)
(BASE/'serialized-validation.json').write_text(json.dumps(output,indent=2));print(json.dumps(output,indent=2))
