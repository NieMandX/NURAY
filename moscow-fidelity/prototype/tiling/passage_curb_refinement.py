"""Refine only curbs obstructing independently source-derived passage volumes.

The original terrain and complete land partition remain intact. Removed curb
tops become ordinary paving at the same height; local return faces are rebuilt
against the complete neighbouring curb boundary, never against a tile edge.
"""
from collections import defaultdict
import numpy as np
import shapely as sh
from build import triangulate,z_at
from curbs import solid_sides,LAND_RAISE
from transitions import union,parts
from transport_ground import clip_mesh,triangle_words
from passage_space import connected_approach
from pathlib import Path
import hashlib,json,shutil,gzip
from prepare_road_paint import read,write
from transport_ground import append_words
from canonical_store import copy_asset,save_canonical,canonical_digest,dump_compact
from prepare_foundations import save,digest,refresh_stats

CURBS={'curb_top','curb_bottom','curb_front','curb_back'}
CLEARANCE=.003  # Same construction allowance as passage_space.ground_landings.


def json_geometry(poly):
    # Canonical records use JSON arrays. Keep the same coordinates and order,
    # but normalize GEOS mapping tuples before exact serialized replay checks.
    return json.loads(json.dumps(sh.geometry.mapping(poly)))


def same_effective_entries(old,new):
    """A discarded disconnected apron island changes no usable ground entry."""
    if len(old)!=len(new):return False
    for a,b in zip(old,new):
        if {k:v for k,v in a.items() if k!='landingGeometry'}!={k:v for k,v in b.items() if k!='landingGeometry'}:return False
        if 'landingGeometry' not in a or 'landingGeometry' not in b:
            if a!=b:return False
            continue
        aa=connected_approach(sh.geometry.shape(a['mouthGeometry']),sh.geometry.shape(a['landingGeometry']))
        bb=connected_approach(sh.geometry.shape(b['mouthGeometry']),sh.geometry.shape(b['landingGeometry']))
        if not aa.equals(bb):return False
    return True


def plan(city,volumes,checks,dem,tree):
    failed={r['interface'] for r in checks if not r['passed']}
    assert failed
    for r in checks:
        if r['interface'] in failed:
            assert set(r['resolvedBlockingKinds'])<=CURBS,('Non-curb obstruction requires its own reconstruction',r)
    ox,oy,_=city['originMSK']
    gates=union([g for r,cells in volumes if r['id'] in failed for g,_ in cells],1e-5)
    cut=sh.transform(gates,lambda xy:xy*[1,-1]+[ox,oy]).buffer(CLEARANCE,join_style='mitre')
    cut=sh.set_precision(cut,1e-5)
    broad=sh.STRtree(list(sh.get_parts(cut.buffer(.2))))
    nearby=[];edits={};paving=[];removed=[]
    for s in city['surfaces']:
        if s['kind']!='curb_top':continue
        p=sh.geometry.shape(s['geometry'])
        if not len(broad.query(p,predicate='intersects')):continue
        nearby.append(p)
        loss=p.intersection(cut)
        if loss.area<1e-10:continue
        retained=p.difference(cut)
        edits[s['id']]=dict(s,geometry=json_geometry(retained)) if retained.area>1e-10 else None
        removed.append(loss)
        for i,part in enumerate(parts(loss)):
            paving.append(dict(s,id='passage-paving:'+s['id']+':'+str(i),kind='land',material=7,
                purpose='pedestrian',surfaceType='pedestrian-paving',geometry=json_geometry(part),
                replacedCurbSurface=s['id']))
    removed=union(removed,1e-5)
    assert not removed.is_empty,'Reported curb obstruction has no retained source curb top'
    old=union(nearby,1e-5);band=old.difference(cut)
    region=removed.buffer(.01,join_style='mitre')
    groups=defaultdict(list)
    solid_sides(band,sh.geometry.shape(city['groundRoadGeometry']),dem,tree,groups,z_at,
                sh.box(*city['boundsMSK']),boundary_region=region)
    return dict(cut=cut,sideRegion=region,removed=removed,oldBand=old,newBand=band,
                edits=edits,paving=paving,sides=groups,interfaces=sorted(failed))


def refine_words(name,words,origin,product):
    """Keep all unaffected packed attributes verbatim, including UVs/normals."""
    if name not in CURBS:return None
    cut=product['sideRegion'] if name in ('curb_front','curb_back') else product['cut']
    return clip_mesh(words,origin,cut)


def additions(product,origin):
    result=defaultdict(list)
    for (name,material),faces in product['sides'].items():
        if faces:result[name].append(triangle_words(faces,origin,material))
    for s in product['paving']:
        result['land'].append(triangle_words(triangulate(sh.geometry.shape(s['geometry']),np.asarray(s['heightPlane'])),origin,s['material']))
    return {name:np.concatenate(rows) for name,rows in result.items()}


def edited_surfaces(before,product):
    result=[]
    for s in before:
        row=product['edits'].get(s['id'],s)
        if row is not None:result.append(row)
    return result+product['paving']


def addition_targets(base,scene,extra):
    result={name:next(c['id'] for c in scene['chunks'] if c['name']==name) for name in extra}
    if 'land' in result:
        # Preserve homogeneous grass/territory batches. New paving belongs
        # to the existing paving batch, not the first chunk named "land".
        matches=[]
        for c in scene['chunks']:
            if c['name']!='land':continue
            remaining=c['vertexBytes'];valid=True
            with gzip.open(base/'canonical/full'/Path(c['file']).name,'rb') as f:
                while remaining:
                    block=f.read(min(remaining,32*65536));assert block
                    words=np.frombuffer(block,'<u4').reshape(-1,8)
                    if np.any((words[:,6]&0x7fffffff)!=7):valid=False;break
                    remaining-=len(block)
            if valid:matches.append(c)
        assert matches,'No existing paving batch for a local passage fill'
        result['land']=min(matches,key=lambda c:c['vertexCount'])['id']
    return result


def local_mesh_changes(base,out,scene,product,origin):
    extra=additions(product,origin)
    first=addition_targets(base,scene,extra)
    changes=[]
    for c in scene['chunks']:
        name=c['name'];added=extra.get(name) if first.get(name)==c['id'] else None
        if name not in CURBS and added is None:continue
        path=Path(c['file']).name;old=dict(c)
        # Appending paving preserves the entire existing land mesh bytewise.
        if name=='land':
            meta=append_words(base/'canonical/full'/path,out/'canonical/full'/path,c,added)
        else:
            words=read(base,c);changed=refine_words(name,words,origin,product)
            if changed is None and added is None:continue
            result=words if changed is None else changed
            if added is not None:result=np.concatenate([result,added])
            meta=write(out/'canonical/full'/path,result)
        c.update(meta)
        changes.append(dict(id=c['id'],name=name,beforeSha256=digest(base/'canonical/full'/path)))
        print('LOCAL CURB CHUNK',c['id'],name,old['triangles'],'->',c['triangles'],flush=True)
    return changes


def build_local(base,out,city,scene,report,actual,connections,interfaces,dem,tree):
    from transport_clearance_validation import volumes,audit
    from prepare_railway_entries import meshes
    from passage_space import POLICY
    old_connections=[c for c in city['gradeConnections'] if c.get('peerKind')=='pedestrian_ground']
    old_interfaces=[r for r in city['roadInterfaces'] if any(e['kind']=='pedestrian_ground' for e in r['ends'])]
    assert same_effective_entries(old_connections,connections),'Walking source connections changed beyond detached apron cleanup'
    assert same_effective_entries(old_interfaces,interfaces),'Walking source interfaces changed beyond detached apron cleanup'
    gates,_,source=volumes(city,dem,tree);assert source['passed']
    product=plan(city,gates,actual['fullWidth']['checks'],dem,tree)
    before_surfaces=[dict(index=i,row=s) for i,s in enumerate(city['surfaces']) if s['id'] in product['edits']]
    out.mkdir()
    for name in ('canonical','textures','library','fence-library'):
        if (base/name).exists():shutil.copytree(base/name,out/name,copy_function=copy_asset)
    if (base/'street-objects.json').exists():copy_asset(base/'street-objects.json',out/'street-objects.json')
    changes=local_mesh_changes(base,out,scene,product,np.asarray(city['originMSK']))
    city['surfaces']=edited_surfaces(city['surfaces'],product)
    after=audit(city,dem,tree,meshes(out,scene))
    save(out/'clearance-diagnostic.json',after)
    assert after['source']['passed'] and after['fullWidth']['passed'],after['partialContacts']
    revision=dict(version=3,type='passage-clearance',mode='localized-curbs',parent=base.name,
        parentValidationSha256=digest(base/'validation.json'),parentCanonicalSha256=canonical_digest(base/'canonical/urban-model.json'),
        previousRevision=city['geometryRevision'],beforeRules=city['rules'],changedChunks=changes,
        beforeSurfaces=before_surfaces,pavingIds=[s['id'] for s in product['paving']],
        cutGeometry=sh.geometry.mapping(product['cut']),removedCurbAreaM2=product['removed'].area,
        constructionClearanceM=CLEARANCE,beforeClearance=actual,afterClearance=after,
        connections=connections,interfaces=interfaces,terrainSha256=digest(base/'canonical/terrain.npz'))
    city['geometryRevision']=revision;city['rules']=dict(city['rules'],passageClearance=POLICY)
    report['geometryRevision']=revision
    refresh_stats(scene,report,out);save(out/'canonical/full/scene.json',scene)
    save_canonical(out/'canonical/urban-model.json',city);save(out/'canonical/validation.json',report)
    # Existing tile packing has a source-byte cache; unchanged layers reuse it.
    print('LOCAL PASSAGE VERSION',out,'changed surfaces',len(before_surfaces),'area',product['removed'].area,flush=True)


def restored_parent(city):
    rev=city['geometryRevision'];before=dict(city)
    ids={p['row']['id'] for p in rev['beforeSurfaces']}|set(rev['pavingIds'])
    surfaces=[s for s in city['surfaces'] if s['id'] not in ids]
    for patch in sorted(rev['beforeSurfaces'],key=lambda p:p['index']):surfaces.insert(patch['index'],patch['row'])
    before.update(surfaces=surfaces,geometryRevision=rev['previousRevision'],rules=rev['beforeRules'])
    digest=hashlib.sha256()
    class Writer:
        def write(self,text):digest.update(text.encode('utf-8'))
    dump_compact(before,Writer())
    assert digest.hexdigest()==rev['parentCanonicalSha256'],'Local reconstruction changed unrelated canonical data'
    return before


def verify_local(root,city,scene):
    from transport_clearance_validation import audit,volumes
    from prepare_railway_entries import load_terrain,meshes
    from prepare_passage_clearance import discover_ground
    from passage_space import POLICY
    from portal_validation import verify_headers
    rev=city['geometryRevision'];base=root.parent/rev['parent']
    proof=json.loads((base/'validation.json').read_text())
    assert proof['passed'] and digest(base/'validation.json')==rev['parentValidationSha256']
    assert canonical_digest(base/'canonical/urban-model.json')==rev['parentCanonicalSha256']
    before=restored_parent(city)
    assert city['rules']==dict(before['rules'],passageClearance=POLICY)
    original=json.loads((base/'canonical/full/scene.json').read_text())
    assert {k:v for k,v in scene.items() if k not in {'chunks','stats'}}=={k:v for k,v in original.items() if k not in {'chunks','stats'}}
    assert len(scene['chunks'])==len(original['chunks'])
    assert digest(base/'canonical/terrain.npz')==digest(root/'canonical/terrain.npz')==rev['terrainSha256']
    for name in original['textures']:assert digest(base/'textures'/name)==digest(root/'textures'/name)
    cs,ifs=discover_ground(before)
    assert cs==rev['connections'] and ifs==rev['interfaces']
    assert same_effective_entries([c for c in before['gradeConnections'] if c.get('peerKind')=='pedestrian_ground'],cs)
    assert same_effective_entries([r for r in before['roadInterfaces'] if any(e['kind']=='pedestrian_ground' for e in r['ends'])],ifs)
    dem,tree=load_terrain(root)
    before_actual=audit(before,dem,tree,meshes(base,original))
    assert before_actual==rev['beforeClearance']
    gates,_,_=volumes(before,dem,tree)
    product=plan(before,gates,before_actual['fullWidth']['checks'],dem,tree)
    assert sh.geometry.shape(rev['cutGeometry']).equals(product['cut'])
    assert abs(rev['removedCurbAreaM2']-product['removed'].area)<1e-9
    assert city['surfaces']==edited_surfaces(before['surfaces'],product)
    extra=additions(product,np.asarray(city['originMSK']))
    first=addition_targets(base,original,extra)
    changes={c['id']:c for c in rev['changedChunks']}
    for a,b in zip(original['chunks'],scene['chunks']):
        pa=base/'canonical/full'/Path(a['file']).name;pb=root/'canonical/full'/Path(b['file']).name
        if a['id'] not in changes:
            assert a==b and digest(pa)==digest(pb)
            continue
        assert a['name']==b['name'] and a['name'] in CURBS|{'land'}
        assert digest(pa)==changes[a['id']]['beforeSha256']
        words=read(base,a);refined=refine_words(a['name'],words,np.asarray(city['originMSK']),product)
        expected=words if refined is None else refined
        if first.get(a['name'])==a['id']:expected=np.concatenate([expected,extra[a['name']]])
        if a['name']!='land':
            pts=expected.view('<f4')[:,:,:3]
            expected=expected[np.linalg.norm(np.cross(pts[:,1]-pts[:,0],pts[:,2]-pts[:,0]),axis=1)>1e-9]
        assert np.array_equal(expected,read(root,b)),('Local curb serialized reconstruction mismatch',a['id'])
    actual=audit(city,dem,tree,meshes(root,scene))
    assert actual==rev['afterClearance'] and actual['source']['passed'] and actual['fullWidth']['passed']
    headers=verify_headers(root,city,scene)
    return dict(passed=True,type=rev['type'],mode=rev['mode'],changedBoundaryChunks=len(changes),
        removedCurbAreaM2=product['removed'].area,fullWidthClearance=actual,
        originalTerrainLandscapeBuildingsPlantsMaterialsPreserved=True,
        sameHeightPavingReplacesEveryRemovedCurbTop=True,**headers,inherited=proof['geometryRevision'])
