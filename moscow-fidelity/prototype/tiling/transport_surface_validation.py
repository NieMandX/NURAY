"""Independent release-scope, source-marking and serialized structure checks."""
import hashlib,json,pickle,tempfile,itertools
from pathlib import Path
import numpy as np
import shapely as sh
from streaming_json import Document
from prepare_foundations import digest
from prepare_transport_surfaces import STRUCTURES,POLICY,attrs,cells
from prepare_road_paint import read,world,actual_domain,serialization_xy_tolerance
from object_geometry import pack
from paint_binding import SOURCE_FLOOR
from paint_domain import Domain,GAP,HEIGHT_TOLERANCE,accepts,paint_projection_mask
from railway_surfaces import confirmed_owners
from build import z_at,plane as height_plane

def field_digest(doc,key):
    with doc.stream(key) as f:return hashlib.file_digest(f,'sha256').hexdigest()

def source_paint_check(root,scene,city,revision):
    print('VERIFY TRANSPORT PAINT preparing source and asphalt domains',flush=True)
    source=Path(revision['sourcePaintFolder'])
    assert digest(source/'corrected/manifest.json')==revision['sourcePaintManifestSha256']
    raw={}
    for row in json.loads((source/'corrected/manifest.json').read_text())['objects']:
        assert row['heightBinding']==SOURCE_FLOOR
        material={'white':3,'yellow':4,'blue':5}[row['materials'][0]]
        a=np.load(source/'corrected'/row['file'])
        for t,tiers in zip(a['triangles'],a['source_tiers']):
            poly=sh.Polygon(t[:,:2])
            if poly.area<1e-10:continue
            for tier in tiers:
                if tier!=-32768:raw.setdefault((material,int(tier)),[]).append(dict(poly=poly.buffer(.0002),plane=np.zeros(3)))
    domains={key:Domain(rs) for key,rs in raw.items()}
    floors=[{**s,'poly':sh.geometry.shape(s['geometry']),'plane':np.array(s['heightPlane'])}
            for s in city['surfaces'] if accepts(s) and s['kind']!='roadbed_flat']
    tree=sh.STRtree([s['poly'] for s in floors]);checked=0;missing=0.;outside_asphalt=0.
    physical=actual_domain(root,scene,np.asarray(city['originMSK']))
    margin=serialization_xy_tolerance(scene)
    physical=Domain([dict(c,poly=c['poly'].buffer(margin)) for c in physical.cells])
    for cid in revision['newChunks']:
        c=scene['chunks'][cid];assert c['name']=='paint'
        words=read(root,c)
        assert paint_projection_mask(words.view('<f4')[:,:,:3]).all(),'Serialized paint collapsed in projection'
        for t,w in zip(world(words,np.asarray(city['originMSK'])),words):
            p=sh.Polygon(t[:,:2]);point=p.representative_point();xy=[point.x,point.y]
            plane=height_plane(t);tiers=set()
            for i in tree.query(point,predicate='dwithin',distance=.0003):
                s=floors[int(i)]
                if abs(z_at(s['plane'],xy)+GAP-z_at(plane,xy))<.0021:tiers.update(s['tiers'])
            assert tiers,('Recovered paint has no tier-matched elevated source floor',cid,xy)
            flat=t.copy();flat[:,2]=GAP;material=int(w[0,6]&0x7fffffff)
            support=sh.union_all([domains[(material,tier)].supported(flat) for tier in tiers if (material,tier) in domains])
            lost=p.difference(support).area;missing+=lost;checked+=1
            assert lost<1e-7,('Recovered marking absent from source',cid,xy,lost)
            spill=p.difference(physical.supported(t,tolerance=HEIGHT_TOLERANCE+.00001)).area
            outside_asphalt+=spill
            assert spill<1e-7,('Recovered marking outside actual asphalt',cid,xy,spill)
            if checked%25000==0:print('VERIFY TRANSPORT PAINT',checked,flush=True)
    assert missing<1e-4
    assert outside_asphalt<1e-4
    return dict(passed=True,triangles=checked,areaOutsideSourceM2=missing,
                areaOutsideActualAsphaltM2=outside_asphalt)

def verify_revision(root,city,scene):
    r=city['geometryRevision'];base=root.parent/r['parent']
    assert digest(base/'validation.json')==r['parentValidationSha256']
    assert json.loads((base/'validation.json').read_text())['passed']
    before=Document(base/'canonical/urban-model.json');after=Document(root/'canonical/urban-model.json')
    assert before.read('geometryRevision')==r['previousRevision']
    allowed={'geometryRevision','overpassProfiles','surfaces','relationships','railwayLayer','roadPaint','rules','gradeConnections','roadInterfaces','landscape'}
    assert set(before.fields)==set(after.fields)
    for key in before.fields.keys()-allowed:assert field_digest(before,key)==field_digest(after,key),key
    assert city['rules']==dict(before.read('rules'),paintHeightBinding=SOURCE_FLOOR,physicalBridgeSheets=POLICY)
    features=[f for f in city['features'] if f['layer'] in {'Transport_Roadbed','Railroad_line','Railroad_tunnel_line'}]
    rail=confirmed_owners(features);owners={f['source'] for f in rail}
    assert city['railwayLayer']['baseRestyle']['confirmedSurfaces']==rail
    from railway_transitions import source_candidates,discover
    from transitions import interface_coverage
    extent=sh.box(*city['boundsMSK'])
    connections,interfaces=discover(source_candidates(features,extent),features,extent,1e-5,z_at)
    connections,interfaces=json.loads(json.dumps([connections,interfaces]))
    assert city['gradeConnections']==[c for c in before.read('gradeConnections') if c.get('peerKind')!='railway_ground']+connections
    assert city['roadInterfaces']==[r for r in before.read('roadInterfaces') if not any(e['kind']=='railway_ground' for e in r['ends'])]+interfaces
    assert interface_coverage(city['roadInterfaces'],city['gradeConnections'],1e-5)['passed']
    product_path=Path(r['structureProduct']);assert digest(product_path)==r['structureProductSha256']
    product=pickle.load(product_path.open('rb'))
    from transport_ground import plan as ground_plan,ground_words,GROUND
    ground_cut,ground_edits,ground_deleted,ground_restored,ground_proof=ground_plan(base,product['profiles'],before)
    assert json.loads(json.dumps(ground_proof))==r['groundPartition']
    print('VERIFY TRANSPORT GROUND',len(ground_edits),len(ground_restored),'holes',ground_proof['exposedGroundHoleM2'],flush=True)
    planting_removed=set();planting_rows=[];planting_extra={}
    if r.get('plantingRepartition'):
        from transport_planting import plan as planting_plan,generated,rebuilt_words
        from prepare_railway_entries import load_terrain
        dem,demtree=load_terrain(base)
        landscape,planting_proof,planting_sides=planting_plan(before,city['roadInterfaces'],dem,demtree)
        assert json.loads(json.dumps(landscape))==city['landscape']
        saved=r['plantingRepartition']
        assert json.loads(json.dumps(planting_proof))=={k:v for k,v in saved.items() if k!='targetChunks'}
        planting_removed=set(planting_proof['removedSurfaceIds']);planting_rows=planting_proof['newSurfaces']
        planting_extra=generated(planting_proof,planting_sides,np.asarray(city['originMSK']))
        assert set(planting_extra)==set(saved['targetChunks'])
        print('VERIFY TRANSPORT PLANTING',len(planting_rows),'lowered',planting_proof['loweredAreaM2'],flush=True)
    else:assert before.read('landscape')==city['landscape']
    ids=set(r['restyledSurfaceIds']);expected=set()
    kept=(a for a in before.items('surfaces') if a['id'] not in ground_deleted and a['id'] not in planting_removed)
    for a,b in zip(itertools.chain(kept,json.loads(json.dumps(ground_restored+planting_rows))),city['surfaces'],strict=True):
        if a['id'] in ground_edits:a=json.loads(json.dumps(ground_edits[a['id']]))
        if a['material']==12 and a['owner'] in owners:
            expected.add(a['id']);a=dict(a,material=r['railMaterial'],purpose='railway',surfaceType='dark-concrete')
        assert a==b,('Changed source floor geometry',a['id'])
    assert ids==expected
    print('VERIFY TRANSPORT SOURCE SURFACES',len(city['surfaces']),flush=True)
    old=json.loads((base/'canonical/full/scene.json').read_text());changes={c['id']:c for c in r['changedChunks']}
    fill_chunk=next(c['id'] for c in old['chunks'] if c['name']=='land')
    assert scene['materials']==old['materials'] and scene['textures']==old['textures']
    assert scene['instances'][:len(old['instances'])]==old['instances']
    assert r['newChunks']==list(range(len(old['chunks']),len(scene['chunks'])))
    for a,b in zip(old['chunks'],scene['chunks']):
        pa=base/'canonical/full'/Path(a['file']).name;pb=root/'canonical/full'/Path(b['file']).name
        if a['id'] not in changes:
            assert a==b and digest(pa)==digest(pb),('Unexpected mesh edit',a['id'])
            continue
        change=changes[a['id']];assert digest(pa)==change['beforeSha256'] and a['name']==b['name']
        if change['reason']=='rail-material':
            aa=read(base,a);bb=read(root,b)
            assert aa.shape==bb.shape and np.array_equal(aa[:,:,[0,1,2,3,4,5,7]],bb[:,:,[0,1,2,3,4,5,7]])
            ma=aa[:,:,6]&0x7fffffff;mb=bb[:,:,6]&0x7fffffff
            assert np.all((ma==mb)|((ma==12)&(mb==r['railMaterial'])))
        elif change['reason']=='bridge-ground-partition':
            assert a['name'] in GROUND
            expected_words=ground_words(read(base,a),np.asarray(city['originMSK']),ground_cut,
                                        ground_restored if a['id']==fill_chunk else [])
            assert expected_words is not None
            from prepare_road_paint import write
            with tempfile.TemporaryDirectory(prefix='nuray-ground-verify-') as temporary:
                path=Path(temporary)/Path(b['file']).name
                write(path,expected_words)
                assert digest(path)==digest(pb),('Ground clipping differs from changed bridge footprint',a['id'])
        elif change['reason']=='railway-planting-reservation':
            target=r['plantingRepartition']['targetChunks'][a['name']]
            extra=planting_extra[a['name']] if a['id']==target else np.empty((0,3,8),dtype='<u4')
            expected_words=rebuilt_words(read(base,a),a['name'],planting_proof,
                                        set(landscape['materials'].values()),extra,np.asarray(city['originMSK']))
            assert expected_words is not None
            from prepare_road_paint import write
            with tempfile.TemporaryDirectory(prefix='nuray-planting-verify-') as temporary:
                path=Path(temporary)/Path(b['file']).name
                write(path,expected_words)
                assert digest(path)==digest(pb),('Railway planting differs from source reservation',a['id'])
        else:assert change['reason']=='continuous-bridge-profile' and a['name'] in STRUCTURES
    assert digest(base/'canonical/terrain.npz')==digest(root/'canonical/terrain.npz')
    for name in scene['textures']:assert digest(base/'textures'/name)==digest(root/'textures'/name)
    print('VERIFY TRANSPORT MESH CHANGES',len(changes),flush=True)
    assert city['overpassProfiles']==json.loads(json.dumps(product['profiles']))
    assert all(p['passed'] for p in product['profiles'])
    recipe=hashlib.sha256();prototype=Path(__file__).resolve().parents[1]
    for name in ('overpasses.py','overpass_sheets.py','transitions.py','structure_clearance.py'):recipe.update((prototype/name).read_bytes())
    assert recipe.hexdigest()==r['structureRecipeSha256']==product['recipeSha256']
    by_name={}
    for (name,mid),faces in product['groups'].items():
        if faces:by_name.setdefault(name,[]).append((mid,np.asarray(faces)))
    with tempfile.TemporaryDirectory(prefix='nuray-structure-verify-') as temporary:
        for name,groups in by_name.items():
            ts=np.concatenate([t for mid,t in groups]);mids=np.concatenate([np.full(len(t),mid) for mid,t in groups])
            targets=[c for c in scene['chunks'] if c['name']==name]
            for c,ix in zip(targets,np.array_split(np.arange(len(ts)),len(targets))):
                path=Path(temporary)/Path(c['file']).name
                pack(attrs(ts[ix],np.asarray(city['originMSK'])),mids[ix],path)
                assert digest(path)==digest(root/'canonical/full'/path.name),('Serialized profile differs',c['id'])
    print('VERIFY TRANSPORT PROFILES',len(product['profiles']),flush=True)
    cleanup=r.get('paintProjectionCleanup')
    if cleanup:
        removed=0
        for witness in cleanup['chunks']:
            before_chunk=witness['before']
            assert digest(root/'canonical/full'/Path(before_chunk['file']).name)==witness['beforeSha256']
            original=read(root,before_chunk);keep=paint_projection_mask(original.view('<f4')[:,:,:3])
            assert int((~keep).sum())==witness['removedTriangles']
            assert np.array_equal(original[keep],read(root,scene['chunks'][witness['id']])), \
                'Projection cleanup changed a nondegenerate marking'
            removed+=witness['removedTriangles']
        assert removed==cleanup['removedTriangles']
    source=source_paint_check(root,scene,city,r)
    # Above, every old paint mesh is byte-identical to the validated parent,
    # and every asphalt vertex/material is unchanged (only white rail
    # materials may change). Reuse that established containment proof;
    # independently check every newly emitted marking against actual asphalt.
    inherited_paint=before.read('roadPaint')['validation']
    assert inherited_paint['passed']
    saved_paint=city['roadPaint']['validation'];assert saved_paint['passed']
    assert inherited_paint['trianglesChecked']+source['triangles']==saved_paint['trianglesChecked']
    return dict(passed=True,type=r['type'],sourceMarkings=source,profiles=len(product['profiles']),
                paintContainmentPassed=True,inheritedPaintTriangles=inherited_paint['trianglesChecked'],
                railTrianglesMaterialOnly=True,terrainHeightsBuildingsPlantsUnchanged=True,
                groundPartition=ground_proof,
                changedChunks=len(changes),newChunks=len(r['newChunks']))
