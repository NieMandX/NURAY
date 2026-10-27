"""Check actual exported geometry, immutable scope and ground-network coverage."""
import gzip,hashlib,json,sys
from pathlib import Path
import numpy as np
import shapely as sh
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from landscape import GREEN_RAISE,PATH_WIDTHS,ground_path
from railway_surfaces import confirmed_owners,RAIL_COLOR
from portal_validation import verify_headers
from landscape_precision import overlap_precision,paving_coverage
from line_coverage import side_lines as projected_side_lines,uncovered_linework
from spatial_mask import SpatialMask
from canonical_parent import load_parent
from pedestrian_materials import is_paving,paving_material_ids

def changed_since_base(revision):
    if not revision:return set()
    # Revisions may store either an audited change record or a chunk ID;
    # the revision-specific verifier validates the actual geometry in both cases.
    own={r if isinstance(r,int) else r['id'] for key in ('wallRebuilds','materialRemaps','changedChunks') for r in revision.get(key,[])}
    return own|changed_since_base(revision.get('previousRevision'))

def verify_revision(root,city,manifest):
    revision=city['geometryRevision'];parent=root.parent/revision['parent']
    old=json.loads((parent/'canonical/full/scene.json').read_text())
    parent_city=load_parent(parent/'canonical/urban-model.json',city)
    assert revision['previousRevision']==parent_city.get('geometryRevision')
    assert manifest['materials'][:len(old['materials'])]==old['materials']
    assert manifest['textures']==old['textures']
    for name in old['textures']:assert (parent/'textures'/name).read_bytes()==(root/'textures'/name).read_bytes()
    changes={r['id']:r for r in revision['changedChunks']}
    preserved={r['id']:r for r in revision['preservedChunks']}
    assert set(changes).isdisjoint(preserved)
    assert set(changes)|set(preserved)=={c['id'] for c in old['chunks']}
    assert set(revision['newChunks'])==set(range(len(old['chunks']),len(manifest['chunks'])))
    def raw(base,c):return gzip.decompress((base/'canonical/full'/Path(c['file']).name).read_bytes())
    origin=np.asarray(city['originMSK']);lawn_before=[];converted=[];raised=[];sides=[]
    for c in old['chunks']:
        before=raw(parent,c);new=manifest['chunks'][c['id']];after=raw(root,new)
        if c['id'] in preserved:
            assert before==after and hashlib.sha256(after).hexdigest()==preserved[c['id']]['sha256'],c['id']
            assert c==new
            continue
        r=changes[c['id']];assert hashlib.sha256(before).hexdigest()==r['beforeSha256']
        assert c['name']==new['name']
        if r['reason']=='retaining-guard':
            assert c['name'] in {'inferred-walls','tunnel_wall_top','tunnel_wall_bottom','tunnel_wall_side','portal_guard_top','portal_guard_bottom','portal_guard_side'}
        elif r['reason']=='green-partition':
            assert c['name']=='land';u=np.frombuffer(before[:c['vertexBytes']],'<u4').reshape(-1,8)
            assert np.all((u[:,6]&0x7fffffff)==2)
        elif r['reason']=='rail-material':
            assert c['name'] in {'roadbed_overpass','roadbed_tunnel_descent','roadbed_tunnel'}
            u=np.frombuffer(before[:c['vertexBytes']],'<u4').reshape(-1,8).copy()
            u[(u[:,6]&0x7fffffff)==12,6]=np.uint32(0x80000000|revision['railMaterial'])
            assert u.tobytes()+before[c['vertexBytes']:]==after,'Rail recoloring changed positions, normals or UV'
        elif r['reason']=='rail-material-mixed':
            from object_geometry import decode_normals
            u=np.frombuffer(before[:c['vertexBytes']],'<u4').reshape(-1,8)
            v=np.frombuffer(after[:new['vertexBytes']],'<u4').reshape(-1,8)
            ai=np.frombuffer(before[c['vertexBytes']:],'<u4').reshape(-1,3)
            bi=np.frombuffer(after[new['vertexBytes']:],'<u4').reshape(-1,3)
            assert len(ai)==len(bi)
            assert np.array_equal(u[ai][:,:,[0,1,2,4,5]],v[bi][:,:,[0,1,2,4,5]])
            assert np.max(np.abs(decode_normals(u[:,3])[ai]-decode_normals(v[:,3])[bi]))<.0002
            am=u[ai[:,0],6]&0x7fffffff;bm=v[bi[:,0],6]&0x7fffffff
            assert np.all((am==bm)|((am==12)&(bm==revision['railMaterial'])))
            rail_owners={p['source'] for p in revision['railProof']}
            rr=[s for s in parent_city['surfaces'] if s['kind']==c['name'] and s['owner'] in rail_owners]
            rp=[sh.geometry.shape(s['geometry']) for s in rr];rt=sh.STRtree(rp)
            centre=u.view('<f4')[ai,:3].mean(1)[:,[0,2,1]]*[1,-1,1]+origin
            for j in np.flatnonzero(am!=bm):
                hits=rt.query(sh.Point(centre[j,:2]),predicate='covered_by')
                assert any(abs(np.r_[centre[j,:2],1]@np.asarray(rr[k]['heightPlane'])-centre[j,2])<.003 for k in hits)
        else:raise AssertionError(('Unexpected revision scope',r))
    instance_changes={r['id']:r for r in revision['instanceChanges']}
    assert len(instance_changes)==len(revision['instanceChanges'])
    for before,after in zip(old['instances'],manifest['instances']):
        if before.get('id') not in instance_changes:assert before==after;continue
        r=instance_changes[before['id']];expected={**before,'matrix':list(before['matrix'])};expected['matrix'][7]+=GREEN_RAISE
        assert expected==after and before['matrix']==r['before'] and after['matrix']==r['after']
    assert len(manifest['instances'])-len(old['instances'])==len(revision['newChunks'])
    terrain=np.load(root/'canonical/terrain.npz');polys=sh.from_wkb(terrain['polygons']);tree=sh.STRtree(polys);planes=terrain['planes']
    terrain_error=0.;green_error=0.;guard_error=0.
    green_ids=set(city['landscape']['materials'].values())
    for c in manifest['chunks']:
        if c['id'] not in changes and c['id'] not in revision['newChunks']:continue
        print('VERIFY LANDSCAPE CHUNK',c['id'],c['name'],flush=True)
        data=raw(root,c);v=np.frombuffer(data[:c['vertexBytes']],'<f4').reshape(-1,8);u=v.view('<u4');ix=np.frombuffer(data[c['vertexBytes']:],'<u4').reshape(-1,3)
        world=v[:,:3][:,[0,2,1]]*[1,-1,1]+origin;mat=u[:,6]&0x7fffffff
        if c['name'] in {'land','green_curb_top','pedestrian_path','railway_apron','tunnel_wall_top','portal_guard_top'}:
            ids=tree.nearest(sh.points(world[:,:2]));base=(planes[ids,:2]*world[:,:2]).sum(1)+planes[ids,2]
            expected=.2 if c['name'] in {'land','green_curb_top'} else .1 if c['name'] in {'pedestrian_path','railway_apron'} else 1.1
            error=float(np.abs(world[:,2]-base-expected).max())
            assert error<.003,(c['id'],c['name'],'height mismatch',error)
            if c['name'] in {'tunnel_wall_top','portal_guard_top'}:guard_error=max(guard_error,error);assert np.all(mat==6)
            else:green_error=max(green_error,error)
        if c['name']=='land':
            assert set(mat)<=green_ids;raised.extend(sh.polygons(world[ix,:2]))
        if c['name']=='green_curb_top':assert np.all(mat==9);raised.extend(sh.polygons(world[ix,:2]))
        if c['name']=='pedestrian_path':assert np.all(mat==7);converted.extend(sh.polygons(world[ix,:2]))
        if c['name']=='railway_apron':assert np.all(mat==revision['railMaterial']);converted.extend(sh.polygons(world[ix,:2]))
        if c['name']=='green_curb_side':
            # Artificial crop/tile side faces are never allowed.
            assert np.all(mat==9)
            bounds=city['boundsMSK'];ts=world[ix]
            for axis,edge in [(0,bounds[0]),(0,bounds[2]),(1,bounds[1]),(1,bounds[3])]:
                assert not np.any(np.max(np.abs(ts[:,:,axis]-edge),axis=1)<.00001)
            sides=ts
    print('VERIFY LANDSCAPE COVERAGE',flush=True)
    actual_green=sh.union_all(raised);actual_path=sh.union_all(converted)
    expected_green=sh.geometry.shape(city['landscape']['raisedGeometry'])
    expected_path=sh.geometry.shape(city['landscape']['convertedGeometry'])
    from railway_landscape import railway_reserve,green_intrusion,low_slab
    rail_reserve=railway_reserve(city)
    rail_green=green_intrusion(expected_green,rail_reserve)
    assert rail_green['passed'],('Raised planting blocks a source railway ground approach',rail_green)
    # Independent height audit includes every confirmed rail bridge slab, even
    # if a future source has omitted its explicit ground connection record.
    rail_proof=confirmed_owners(city['features'])
    bridge_ids={r['source'] for r in rail_proof if r['part']=='roadbed_overpass'}
    low_rail=sh.union_all([low_slab(f['coordinates']) for f in city['features'] if f['id'] in bridge_ids])
    low_green=green_intrusion(expected_green,low_rail)
    assert low_green['passed'],('Raised planting intersects low source railway deck',low_green)
    assert expected_green.difference(actual_green.buffer(.001)).area<.001
    assert actual_green.difference(expected_green.buffer(.001)).area<.001
    # Detailed paving has priority over the source lawn. Removing their old
    # overlap does not require another coincident copy of that paving. Include
    # the preserved, serialized paving triangles in the coverage witness.
    existing_paving=[]
    for c in manifest['chunks']:
        if c['id'] not in preserved or c['name']!='land':continue
        data=raw(root,c);v=np.frombuffer(data[:c['vertexBytes']],'<f4').reshape(-1,8)
        ix=np.frombuffer(data[c['vertexBytes']:],'<u4').reshape(-1,3)
        selected=np.isin(v.view('<u4')[ix[:,0],6]&0x7fffffff,list(paving_material_ids(manifest)))
        if selected.any():
            world=v[:,:3][:,[0,2,1]]*[1,-1,1]+origin
            existing_paving.extend(sh.polygons(world[ix[selected],:2]))
    all_paving=sh.union_all([actual_path,*existing_paving])
    paving_check=paving_coverage(expected_path,all_paving)
    missing_paving=paving_check['uncoveredPavingAreaM2']
    assert paving_check['passed'],('Missing serialized paving',paving_check)
    overlap=actual_green.intersection(actual_path)
    # Float32 triangle clipping can accumulate a nonzero total area along many
    # kilometres of perimeter. Bound its WIDTH at the shared boundary instead
    # of allowing/disallowing an arbitrary total area for the whole city.
    overlap_check=overlap_precision(overlap,expected_green,origin)
    interior_overlap=overlap_check['interiorOverlapM2']
    assert overlap_check['passed'],('Interior green/path overlap or insufficient coordinate precision',overlap_check)
    # Every real green perimeter needs a vertical curb face. A mesh may have
    # correct top heights yet still omit its narrow sides at terrain cell cuts.
    print('VERIFY LANDSCAPE VERTICAL SIDES',flush=True)
    side_lines=projected_side_lines(sides)
    physical=expected_green.boundary.difference(sh.box(*city['boundsMSK']).boundary.buffer(.0001))
    missing_sides=uncovered_linework(physical,side_lines,.001).length
    assert missing_sides<.01,('Missing green curb side',missing_sides)
    # Coverage test is independent of source path-width synthesis: every retained
    # ground centreline inside the original lawn must be in serialized paving.
    print('VERIFY LANDSCAPE SOURCE PATHS',flush=True)
    source_green=sh.union_all([sh.geometry.shape(s['geometry']) for s in parent_city['surfaces'] if s['kind']=='land' and s['material']==2])
    missing=0.;checked=0;old_walk=None
    green_mask=SpatialMask(source_green);path_mask=SpatialMask(actual_path.buffer(.003))
    for f in city['features']:
        if not ground_path(f):continue
        line=sh.LineString(np.asarray(f['coordinates'])[:,:2])
        line=line.intersection(green_mask.near(line))
        if line.length<.001:continue
        path_cover=path_mask.near(line)
        absent=line.difference(path_cover).length
        # Lines already represented by detailed paving were clipped before
        # synthesis; allow their original 5 cm boundary tolerance explicitly.
        if absent>.001:
            if old_walk is None:
                old_walk=SpatialMask(sh.union_all([sh.geometry.shape(s['geometry']) for s in parent_city['surfaces'] if is_paving(s)]).buffer(.051))
            absent=line.difference(path_cover).difference(old_walk.near(line)).length
        assert absent<.01,(f['id'],'pedestrian line still covered by grass',absent)
        missing+=absent;checked+=1
    assert rail_proof==revision['railProof']
    assert manifest['materials'][revision['railMaterial']]['color']==RAIL_COLOR
    assert all(g['guardAboveLandM']==1. for g in city['tunnelWalls']['groups'])
    header_check=verify_headers(root,city,manifest)
    return dict(passed=True,type='landscape',preservedChunks=len(preserved),changedChunks=len(changes),newChunks=len(revision['newChunks']),
        sourcePathsChecked=checked,uncoveredPathLengthM=missing,uncoveredGreenBorderM=missing_sides,
        greenPathInteriorOverlapM2=interior_overlap,uncoveredPavingAreaM2=missing_paving,pavingCoverage=paving_check,
        raisedGreenInRailwayApproachM2=rail_green['resolvedOverlapM2'],railwayApproachBoundary=rail_green,
        raisedGreenOnLowRailDeckM2=low_green['resolvedOverlapM2'],lowRailDeckBoundary=low_green,railBridgeSlabsChecked=len(bridge_ids),
        packedBoundaryToleranceM=overlap_check['maxBoundaryToleranceM'],greenPathPrecision=overlap_check,
        maxGreenHeightErrorM=green_error,maxGuardHeightErrorM=guard_error,
        shiftedTreeInstances=len(instance_changes),confirmedRailSlabs=len(revision['railProof']),
        unchangedRoadPaintBuildingsRailUV=True,**header_check)
