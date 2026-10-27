"""Resolve confirmed walking landings before all boundary solids and planting.

Immutable refinement of a fully assembled city. Source slabs, asphalt, paint,
rail UVs, building meshes, materials and instance transforms remain unchanged.
"""
import argparse,gzip,json,shutil,sys
from collections import defaultdict
from pathlib import Path
import numpy as np
import shapely as sh
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from build import triangulate,z_at,plane
from pedestrian import discover
from passage_space import stable_area,walking_reserve,POLICY
from transitions import parts,union,interface_coverage
from tunnel_walls import build as build_walls
from curbs import solid_sides
from landscape import plan,split_cell,sides,GREEN_RAISE
from railway_landscape import railway_reserve
from green_insets import protected_ground
from object_geometry import pack,export_glb
from prepare_foundations import save,digest,refresh_stats
from prepare_railway_entries import load_terrain,meshes
from prepare_landscape import WALLS
from transport_clearance_validation import audit
from spatial_mask import SpatialMask
from line_coverage import side_lines,uncovered_linework
from canonical_store import load_canonical, save_canonical, copy_asset
from canonical_parent import load_parent
import gc

ALLOWED=WALLS|{'curb_top','curb_bottom','curb_front','curb_back','land','green_curb_top','green_curb_side','pedestrian_path','railway_apron'}


def already_clear(city,connections,interfaces,actual):
    """A current, unchanged topology plus a fresh mesh audit needs no remesh.

    Older landscape/guard recipes still take the reconstruction path. A cached
    verdict alone cannot enable this path: the caller audits actual meshes.
    """
    landscape=city.get('landscape',{});walls=city.get('tunnelWalls',{})
    old_connections=[c for c in city['gradeConnections'] if c.get('peerKind')=='pedestrian_ground']
    old_interfaces=[r for r in city['roadInterfaces'] if any(e['kind']=='pedestrian_ground' for e in r['ends'])]
    return bool(old_connections==connections and old_interfaces==interfaces
        and landscape.get('version',0)>=2 and landscape.get('numericCleanup',{}).get('minResolvedWidthM')==.0001
        and walls.get('ruleVersion',0)>=4 and all(g['guardAboveLandM']==1. for g in walls['groups'])
        and actual['source']['passed'] and actual['fullWidth']['passed'])


def preserve_clear_version(base,out,city,scene,report,actual,connections,interfaces):
    """Record a verified no-op, preserving every source and generated mesh."""
    out.mkdir()
    for name in ('canonical','textures','library','fence-library'):
        if (base/name).exists():shutil.copytree(base/name,out/name,copy_function=copy_asset)
    if (base/'street-objects.json').exists():copy_asset(base/'street-objects.json',out/'street-objects.json')
    revision=dict(version=2,type='passage-clearance',mode='verified-unchanged',parent=base.name,
        parentValidationSha256=digest(base/'validation.json'),previousRevision=city['geometryRevision'],
        changedChunks=[],beforeClearance=actual,afterClearance=actual,connections=connections,interfaces=interfaces,
        removedNumericCurbAreaM2=0.,terrainSha256=digest(base/'canonical/terrain.npz'))
    city['geometryRevision']=revision;city['rules']['passageClearance']=POLICY;report['geometryRevision']=revision
    save_canonical(out/'canonical/urban-model.json',city);save(out/'canonical/validation.json',report)
    save(out/'clearance-diagnostic.json',actual)
    print('PASSAGE VERSION',out,'verified unchanged; all current source mouths are already clear',flush=True)


def discover_ground(city):
    extent=sh.box(*city['boundsMSK']);rows=[]
    for f in city['features']:
        if f.get('semantics',{}).get('purpose')!='pedestrian' or f['geometryType']!='polygon':continue
        if f['properties'].get('db_road_part') not in ('roadbed_overpass','roadbed_tunnel_descent'):continue
        xyz=np.asarray(f['coordinates']);patches=[]
        for i in range(len(xyz)-2):
            t=xyz[i:i+3];a=np.column_stack([t[:,:2],np.ones(3)])
            if abs(np.linalg.det(a))<1e-8:continue
            p=sh.set_precision(sh.make_valid(sh.Polygon(t[:,:2])),1e-5).intersection(extent)
            if p.area>1e-9:patches.append((p,np.linalg.solve(a,t[:,2])))
        if patches:rows.append(dict(id=f['id'],kind='road',transport='pedestrian',part=f['properties']['db_road_part'],
            tiers=f['properties'].get('db_tiers') or [0],poly=union([p for p,c in patches],1e-5),patches=patches))
    cs,ifs=discover(rows,city['features'],sh.geometry.shape(city['groundRoadGeometry']),extent,1e-5,z_at,
                    include_mixed_ground=True)
    # GeoJSON tuples become arrays on disk; compare the persisted form.
    return json.loads(json.dumps(cs)),json.loads(json.dumps(ifs))


def build(base,out):
    assert not out.exists() and base.parent==out.parent
    proof=json.loads((base/'validation.json').read_text());assert proof['passed']
    city=load_canonical(base/'canonical/urban-model.json');scene=json.loads((base/'canonical/full/scene.json').read_text())
    gc.freeze()
    report=json.loads((base/'canonical/validation.json').read_text());extent=sh.box(*city['boundsMSK']);dem,tree=load_terrain(base)
    before=audit(city,dem,tree,meshes(base,scene))
    print('BEFORE',[(r['interface'],r['blockingFaceAreaM2']) for r in before['partialContacts']],flush=True)
    cs,ifs=discover_ground(city)
    if already_clear(city,cs,ifs,before):
        preserve_clear_version(base,out,city,scene,report,before,cs,ifs)
        return
    old_cs=[c for c in city['gradeConnections'] if c.get('peerKind')=='pedestrian_ground'];old_ids={c['id'] for c in old_cs}
    city['gradeConnections']=[c for c in city['gradeConnections'] if c.get('peerKind')!='pedestrian_ground']+cs
    city['roadInterfaces']=[r for r in city['roadInterfaces'] if not any(e['kind']=='pedestrian_ground' for e in r['ends'])]+ifs
    city['relationships']=[r for r in city['relationships'] if not (r.get('type')=='grade-connection' and r.get('owner') in old_ids)]
    city['relationships'].extend(dict(type='grade-connection',owner=c['id'],parents=c['sourceParents']+c['peerParents'],
        evidence=c['evidence'],connectorAreaM2=0.) for c in cs)
    coverage=interface_coverage(city['roadInterfaces'],city['gradeConnections'],1e-5);assert coverage['passed']
    print('WALKING ENTRIES',len(old_cs),'->',len(cs),flush=True)
    rows=[dict(s,poly=sh.geometry.shape(s['geometry']),plane=np.asarray(s['heightPlane'])) for s in city['surfaces']]
    groups=defaultdict(list);mats=defaultdict(list)
    _,walls=build_walls(rows,city['features'],dem,tree,groups,extent,1e-5,city['gradeConnections'],city['sourceStyle'],triangulate,z_at,plane)
    assert walls['passed'];city['tunnelWalls']=walls;report['tunnelWalls']=walls
    # Drop detached sub-grid slivers before making either horizontal or vertical
    # faces. Do not globally round contours or remove legitimate narrow islands.
    curb_rows=[r for r in rows if r['kind']=='curb_top']
    curb_before=union([r['poly'] for r in curb_rows],1e-5)
    curb=stable_area(curb_before.difference(walking_reserve(city['gradeConnections'],1e-5)),1e-5)
    curb_removed=curb_before.difference(curb);new_curbs=[]
    curb_mask=SpatialMask(curb)
    for r in curb_rows:
        for p in parts(r['poly'].intersection(curb_mask.near(r['poly']))):
            if p.area<1e-9:continue
            s={k:v for k,v in r.items() if k not in ('poly','plane')};s['geometry']=sh.geometry.mapping(p);new_curbs.append(s)
            groups[('curb_top',9)].extend(triangulate(p,r['plane']))
            groups[('curb_bottom',9)].extend(t[::-1] for t in triangulate(p,r['plane']-[0,0,.1]))
    solid_sides(curb,sh.geometry.shape(city['groundRoadGeometry']),dem,tree,groups,z_at,extent)
    print('NUMERIC CURB AREA REMOVED',curb_removed.area,flush=True)
    # Repartition the retained original green cells, not the already raised
    # mesh. Existing paths participate too; no cumulative +10 cm displacement.
    green_rows=[]
    for r in rows:
        role=r.get('landscapeRole')
        if role not in ('green','curb','path','railway_apron'):continue
        green_rows.append(dict(r,plane=r['plane']-[0,0,GREEN_RAISE if role in ('green','curb') else 0]))
    green=union([r['poly'] for r in green_rows],1e-5)
    walk=union([r['poly'] for r in rows if r['kind']=='land' and r['material']==7 and not r.get('landscapeRole')],1e-5)
    layout,landscape=plan(city['features'],green,walk,extent,protected_ground(city),rail_apron=railway_reserve(city) if city['landscape'].get('railApronMaterial') is not None else None)
    owners={f['id']:f for f in city['features']};material_map=city['landscape']['materials'];new_green=[]
    for r in green_rows:
        for role,g,c in split_cell(r['poly'],r['plane'],layout):
            for p in parts(g):
                if p.area<1e-9:continue
                material=material_map[owners[r['owner']]['layer']] if role=='green' else 9 if role=='curb' else city['landscape']['railApronMaterial'] if role=='railway_apron' else 7
                s={k:v for k,v in r.items() if k not in ('poly','plane','geometry','heightPlane','landscapeRole')}
                s.update(id=f'passage-landscape:{len(new_green)}',geometry=sh.geometry.mapping(p),heightPlane=c.tolist(),material=material,
                         kind='green_curb_top' if role=='curb' else 'land',landscapeRole=role,
                         purpose='green-border' if role=='curb' else 'pedestrian' if role=='path' else 'railway' if role=='railway_apron' else 'vegetation-cover',
                         surfaceType='concrete' if role=='curb' else 'pedestrian-paving' if role=='path' else 'dark-concrete' if role=='railway_apron' else 'vegetation')
                if role=='path':s['replacedGreenOwner']=r['owner']
                new_green.append(s);name='green' if role=='green' else 'green_curb_top' if role=='curb' else 'railway_apron' if role=='railway_apron' else 'pedestrian_path'
                faces=triangulate(p,c);groups[(name,material)].extend(faces)
    groups[('green_curb_side',9)]=sides(layout,dem,tree,extent,triangulate,z_at)
    old_raised=sh.geometry.shape(city['landscape']['raisedGeometry']);changed_ground=old_raised.symmetric_difference(layout['raised'])
    # No object is allowed to become floating due to a changed landing. If a
    # future dataset puts one there, fail for placement resolution, don't hide it.
    for o in city.get('objectLayer',{}).get('vegetation',[]):
        assert not changed_ground.covers(sh.Point(o['position'][:2])),('Vegetation occupies a newly resolved landing',o.get('id'))
    landscape.update(materials=material_map,railApronMaterial=city['landscape'].get('railApronMaterial'),raisedGeometry=sh.geometry.mapping(layout['raised']),curbGeometry=sh.geometry.mapping(layout['band']),
        discardedNumericGeometry=sh.geometry.mapping(layout['discarded']),
        convertedGeometry=sh.geometry.mapping(sh.union_all([green,layout['filled']]).difference(layout['raised']).difference(layout['discarded'])),
        activePaths=sum(p['convertedGreenAreaM2']>.01 for p in landscape['sourcePaths']),passed=True,
        shiftedTreeInstances=city['landscape'].get('shiftedTreeInstances',0),insetRecovery=city['landscape'].get('insetRecovery'))
    city['landscape']=landscape;report['landscape']=landscape
    city['surfaces']=[{k:v for k,v in r.items() if k not in ('poly','plane')} for r in rows
                      if r['kind']!='curb_top' and not r.get('landscapeRole')]+new_curbs+new_green
    out.mkdir()
    for name in ('canonical','textures','library','fence-library'):
        if (base/name).exists():shutil.copytree(base/name,out/name,copy_function=copy_asset)
    if (base/'street-objects.json').exists():copy_asset(base/'street-objects.json',out/'street-objects.json')
    targets=defaultdict(list);green_materials=set(material_map.values());folder=out/'canonical/full';origin=np.array(city['originMSK'])
    for chunk in scene['chunks']:
        name=chunk['name']
        if name in WALLS|{'curb_top','curb_bottom','curb_front','curb_back','green_curb_top','green_curb_side','pedestrian_path','railway_apron'}:targets[name].append(chunk)
        elif name=='land':
            data=gzip.decompress((folder/Path(chunk['file']).name).read_bytes());u=np.frombuffer(data[:chunk['vertexBytes']],'<u4').reshape(-1,8)
            if set((u[:,6]&0x7fffffff).tolist())<=green_materials:targets['green'].append(chunk)
    changed=[]
    for name,chunks in targets.items():
        ff=[];mm=[]
        for (gname,mat),faces in groups.items():
            if name!=gname:continue
            ff.extend(faces);mm.extend([mat]*len(faces))
        ff=np.asarray(ff);mm=np.asarray(mm);assert len(ff)>=len(chunks),(name,len(ff))
        for chunk,ix in zip(chunks,np.array_split(np.arange(len(ff)),len(chunks))):
            path=folder/Path(chunk['file']).name;changed.append(dict(id=chunk['id'],name=chunk['name'],beforeSha256=digest(path)))
            xyz=(ff[ix]-origin)[:,:,[0,2,1]]*[1,1,-1]
            normals=np.cross(xyz[:,1]-xyz[:,0],xyz[:,2]-xyz[:,0]);normals/=np.maximum(np.linalg.norm(normals,axis=1,keepdims=True),1e-20)
            attrs=np.concatenate([xyz,np.repeat(normals[:,None,:],3,axis=1),xyz[:,:,[0,2]]],axis=2)
            meta=pack(attrs,mm[ix],path);assert meta;chunk.update(meta)
    after=audit(city,dem,tree,meshes(out,scene));print('AFTER CONTACTS',after['partialContacts'],flush=True)
    save(out/'clearance-diagnostic.json',after)
    assert after['source']['passed'] and after['fullWidth']['passed'],after['partialContacts']
    city['rules'].update(passageClearance=POLICY,tunnelWalls=walls['policy'])
    revision=dict(version=1,type='passage-clearance',parent=base.name,parentValidationSha256=digest(base/'validation.json'),
        previousRevision=city['geometryRevision'],changedChunks=changed,beforeClearance=before,afterClearance=after,
        connections=cs,interfaces=ifs,removedNumericCurbAreaM2=curb_removed.area,terrainSha256=digest(base/'canonical/terrain.npz'))
    city['geometryRevision']=revision;report['geometryRevision']=revision;report['gradeConnections']['interfaceCoverage']=coverage
    refresh_stats(scene,report,out);save(folder/'scene.json',scene)
    export_glb(scene,folder);report['export']['glbBytes']=(folder/'model.glb').stat().st_size
    save_canonical(out/'canonical/urban-model.json',city);save(out/'canonical/validation.json',report)
    print('PASSAGE VERSION',out,flush=True)


def verify_revision(root,city,scene):
    rev=city['geometryRevision'];base=root.parent/rev['parent'];proof=json.loads((base/'validation.json').read_text())
    assert proof['passed'] and digest(base/'validation.json')==rev['parentValidationSha256']
    old=json.loads((base/'canonical/full/scene.json').read_text())
    # A verified no-op changes only provenance/rules. The parent loader still
    # proves its complete byte hash, falling back on any unexpected difference.
    changed_keys=('geometryRevision','rules') if rev.get('mode')=='verified-unchanged' else None
    before=load_parent(base/'canonical/urban-model.json',city,changed_keys=changed_keys)
    assert rev['previousRevision']==before['geometryRevision']
    scope={'geometryRevision','gradeConnections','roadInterfaces','relationships','rules','surfaces','landscape','tunnelWalls'}
    assert {k:v for k,v in city.items() if k not in scope}=={k:v for k,v in before.items() if k not in scope}
    assert {k:v for k,v in scene.items() if k not in {'chunks','stats'}}=={k:v for k,v in old.items() if k not in {'chunks','stats'}}
    changes={r['id']:r for r in rev['changedChunks']};assert len(scene['chunks'])==len(old['chunks'])
    for a,b in zip(old['chunks'],scene['chunks']):
        pa=base/'canonical/full'/Path(a['file']).name;pb=root/'canonical/full'/Path(b['file']).name
        if a['id'] in changes:
            assert a['name']==b['name'] and a['name'] in ALLOWED
            assert digest(pa)==changes[a['id']]['beforeSha256']
        else:assert a==b and pa.read_bytes()==pb.read_bytes()
    # Physical transport floors and all unrelated canonical land are identical.
    def kept(s):return s['kind']!='curb_top' and not s.get('landscapeRole')
    assert [s for s in before['surfaces'] if kept(s)]==[s for s in city['surfaces'] if kept(s)]
    assert digest(base/'canonical/terrain.npz')==digest(root/'canonical/terrain.npz')==rev['terrainSha256']
    for n in old['textures']:assert digest(base/'textures'/n)==digest(root/'textures'/n)
    cs,ifs=discover_ground(city);assert cs==rev['connections'] and ifs==rev['interfaces']
    assert city['rules']==dict(before['rules'],passageClearance=POLICY,tunnelWalls=city['tunnelWalls']['policy'])
    assert all(g['passed'] and g['guardAboveLandM']==1. for g in city['tunnelWalls']['groups'])
    from portal_validation import verify_headers
    headers=verify_headers(root,city,scene)
    dem,tree=load_terrain(root);actual=audit(city,dem,tree,meshes(root,scene))
    assert actual['source']['passed'] and actual['fullWidth']['passed'],actual['partialContacts']
    assert rev['afterClearance']==actual
    if rev.get('mode')=='verified-unchanged':
        assert already_clear(before,cs,ifs,actual)
        assert not changes and scene==old
        assert {k:v for k,v in city.items() if k not in {'geometryRevision','rules'}}=={k:v for k,v in before.items() if k not in {'geometryRevision','rules'}}
        assert rev['beforeClearance']==actual and rev['removedNumericCurbAreaM2']==0.
        return dict(passed=True,type=rev['type'],mode=rev['mode'],groundWalkingEntries=len(cs),
            fullWidthClearance=actual,changedBoundaryChunks=0,allCanonicalGeometryUnchanged=True,
            **headers,inherited=proof['geometryRevision'])
    # Check the replacement surfaces, not merely the absence of barriers:
    # removed lawn must become pavement, and every remaining lawn edge must
    # retain a riser. The old land coverage cannot silently disappear.
    raised=[];paved=[];riser_lines=[];origin=np.asarray(city['originMSK']);max_height_error=0.
    green_mats=set(city['landscape']['materials'].values());terrain=np.asarray([c for p,c in dem])
    for chunk in scene['chunks']:
        if chunk['id'] not in changes or chunk['name'] not in {'land','pedestrian_path','railway_apron','green_curb_top','green_curb_side'}:continue
        raw=gzip.decompress((root/'canonical/full'/Path(chunk['file']).name).read_bytes())
        u=np.frombuffer(raw[:chunk['vertexBytes']],'<u4').reshape(-1,8);v=u.view('<f4');ix=np.frombuffer(raw[chunk['vertexBytes']:],'<u4').reshape(-1,3)
        xyz=v[ix,:3].astype(float)[:,:,[0,2,1]]*[1,-1,1]+origin
        if chunk['name']=='green_curb_side':
            riser_lines.extend(side_lines(xyz))
            continue
        if chunk['name']=='land':assert set((u[:,6]&0x7fffffff).tolist())<=green_mats
        target=paved if chunk['name'] in {'pedestrian_path','railway_apron'} else raised
        target.extend(sh.polygons(xyz[:,:,:2]))
        pts=np.unique(xyz.reshape(-1,3),axis=0);ids=tree.nearest(sh.points(pts[:,:2]))
        expected=(terrain[ids,:2]*pts[:,:2]).sum(1)+terrain[ids,2]+(.1 if chunk['name'] in {'pedestrian_path','railway_apron'} else .2)
        max_height_error=max(max_height_error,float(np.max(abs(expected-pts[:,2]))))
    green=sh.union_all(raised);walk=sh.union_all(paved);expected=sh.geometry.shape(city['landscape']['raisedGeometry'])
    missing=expected.difference(green.buffer(.0001)).area;excess=green.difference(expected.buffer(.0001)).area
    all_before=union([sh.geometry.shape(s['geometry']) for s in before['surfaces'] if s.get('landscapeRole')],1e-5)
    missing_land=all_before.difference(sh.union_all([green,walk]).buffer(.0001)).area
    lost_outside=sh.geometry.shape(before['landscape']['raisedGeometry']).difference(green.buffer(.0001)).difference(protected_ground(city).buffer(.0001)).area
    physical=expected.boundary.difference(sh.box(*city['boundsMSK']).boundary.buffer(.0001))
    missing_sides=uncovered_linework(physical,riser_lines,.001).length
    assert max_height_error<.003 and max(missing,excess,missing_land,lost_outside)<.01,(max_height_error,missing,excess,missing_land,lost_outside)
    assert missing_sides<.01,('Missing lawn risers',missing_sides)
    return dict(passed=True,type=rev['type'],groundWalkingEntries=len(cs),fullWidthClearance=actual,
        planting=dict(maxHeightErrorM=max_height_error,missingM2=missing,excessM2=excess,missingLandM2=missing_land,
                      lossOutsideProtectedApproachesM2=lost_outside,missingRiserM=missing_sides),
        changedBoundaryChunks=len(changes),roadFloorsPaintBuildingsInstancesRailUvUnchanged=True,**headers,inherited=proof['geometryRevision'])


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--base',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();build(a.base,a.output)
