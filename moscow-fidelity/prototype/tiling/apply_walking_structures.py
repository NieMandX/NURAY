"""Apply a verified source-mouth rebuild to an unvalidated initial city only.

Triangle ownership is proved against regenerated old Float32 positions before
replacement. Unselected structures and all source floors retain packed bytes.
"""
import argparse,copy,gc,json,pickle,shutil
from collections import defaultdict
from pathlib import Path
import numpy as np
import shapely as sh
from canonical_store import load_canonical,save_canonical,canonical_digest,copy_asset
from walking_structure_refresh import position_keys,replacement_mask,connection_digest,serialized_words,refresh_connections
from prepare_road_paint import read,write
from prepare_foundations import digest,refresh_stats,save
from prepare_railway_entries import load_terrain,meshes
from repair_initial_structures import MemoryDocument
from transport_ground import triangle_words,plan,apply,initial_curb_faces
from interface_validation import passage_volumes,check_interfaces


def replace_structural_meshes(base,out,scene,old_scene,product,origin):
    folder=out/'canonical/full';changes=[];matches=[]
    originals={c['id']:c for c in old_scene['chunks']}
    new_groups=product['new']['groups'];old_groups=product['old']['groups']
    assert set(new_groups)<=set(old_groups),'New structural category needs explicit allocation'
    for key,faces in old_groups.items():
        if not len(faces):continue
        name,material=key;expected=position_keys(serialized_words(faces,origin,material))
        found=[];targets=[]
        for c in scene['chunks']:
            if c['name']!=name:continue
            # A preceding material may already have changed the metadata for
            # another chunk with this name. Always decode the immutable parent
            # with its own vertexBytes/index boundary.
            words=read(base,originals[c['id']])
            assert len(np.unique(words[:,0,6]&0x7fffffff))==1,'Mixed structural materials need a combined chunk replacement'
            mask=replacement_mask(words,expected)&((words[:,0,6]&0x7fffffff)==material)
            if mask.any():targets.append((c,words,mask));found.extend(position_keys(words[mask]))
        assert np.array_equal(np.sort(expected),np.sort(np.asarray(found,dtype='V36'))),(key,len(expected),len(found))
        extra=serialized_words(new_groups.get(key,[]),origin,material)
        for index,(c,words,mask) in enumerate(targets):
            result=np.concatenate([words[~mask],extra]) if index==0 else words[~mask]
            assert len(result),'Structural chunk became empty; handle explicit instance removal'
            before=digest(base/'canonical/full'/Path(c['file']).name)
            c.update(write(folder/Path(c['file']).name,result))
            changes.append(dict(id=c['id'],name=name,beforeSha256=before,removedTriangles=int(mask.sum()),
                                addedTriangles=len(extra) if index==0 else 0))
        matches.append(dict(name=name,material=material,exactOldTriangles=len(expected),replacementTriangles=len(extra)))
        print('WALKING REPLACED',matches[-1],flush=True)
    return changes,matches


def main():
    ap=argparse.ArgumentParser()
    for flag in ('base','output','product'):ap.add_argument('--'+flag,type=Path,required=True)
    ap.add_argument('--resume-initial',action='store_true',help='Resume only a draft retaining its exact parent canonical registry')
    args=ap.parse_args();base=args.base.resolve();out=args.output.resolve()
    assert base.parent==out.parent and base!=out
    assert not (base/'validation.json').exists() or not json.loads((base/'validation.json').read_text()).get('passed')
    with args.product.open('rb') as f:product=pickle.load(f)
    assert product['parentCanonicalSha256']==canonical_digest(base/'canonical/urban-model.json')
    assert all(p['passed'] for p in product['new']['profiles']) and all(m['exact'] for m in product['matches'])
    report=json.loads((base/'canonical/validation.json').read_text());assert report['passed']
    scene=json.loads((base/'canonical/full/scene.json').read_text());old_scene=copy.deepcopy(scene)
    origin=np.asarray(scene['origin']);folder=out/'canonical/full'
    if args.resume_initial:
        assert out.exists() and not (out/'initial-walking-repair.json').exists()
        assert not (out/'validation.json').exists()
        canonical='canonical/urban-model.json'
        if not (base/canonical).exists():canonical+='.gz'
        assert digest(base/canonical)==digest(out/canonical),'Draft canonical registry has already changed'
        assert digest(base/'canonical/validation.json')==digest(out/'canonical/validation.json')
    else:
        assert not out.exists();out.mkdir()
        for name in ('canonical','textures','library','fence-library'):
            if (base/name).exists():shutil.copytree(base/name,out/name,copy_function=copy_asset)
    # Complete and verify buffer replacement before loading the large registry.
    changes,matches=replace_structural_meshes(base,out,scene,old_scene,product,origin)
    save(out/'walking-mesh-replacement.json',dict(changes=changes,matches=matches,parentCanonicalSha256=product['parentCanonicalSha256']))
    print('WALKING APPLY LOAD CITY',flush=True)
    city=load_canonical(base/'canonical/urban-model.json');gc.freeze()
    assert not city.get('geometryRevision') and not city.get('landscape')
    assert np.array_equal(origin,city['originMSK'])
    old_profiles=city['overpassProfiles']
    def profile_key(p):return (p['transport'],tuple(p['level']),tuple(p['sourceParents']))
    old_keys={profile_key(p) for p in product['old']['profiles']}
    selected={i for i,p in enumerate(old_profiles) if profile_key(p) in old_keys}
    assert len(selected)==len(old_keys),'Selective source sheets do not match canonical profiles'
    city['overpassProfiles']=[p for i,p in enumerate(old_profiles) if i not in selected]+product['new']['profiles']
    _,_,coverage=refresh_connections(city)
    assert city['gradeConnections']==product['connections'],'Source walking connections changed after product generation'
    terrain=load_terrain(base);dem,tree=terrain
    print('WALKING APPLY TERRAIN',len(dem),flush=True)
    source=base/'canonical/urban-model.json'
    if not source.exists():source=Path(str(source)+'.gz')
    cut,edits,deleted,restored,ground=plan(base,city['overpassProfiles'],MemoryDocument(city,source),out/'walking-ground-scan.json',
        terrain=terrain,old_profiles=old_profiles,allow_unrefined_green=True,allow_initial_curbs=True)
    existing={s['id'] for s in city['surfaces']}
    assert not existing.intersection(s['id'] for s in restored),'Ground restoration IDs collide'
    curb_faces,side_region=initial_curb_faces(ground,restored,sh.geometry.shape(city['groundRoadGeometry']),dem,tree,sh.box(*city['boundsMSK']))
    changes.extend(apply(base,out,scene,old_scene,origin,cut,restored,curb_faces=curb_faces,curb_side_region=side_region))
    city['surfaces']=[edits.get(s['id'],s) for s in city['surfaces'] if s['id'] not in deleted]+restored
    added=sh.union_all([sh.geometry.shape(s['geometry']) for s in restored if s['kind']=='curb_top'])
    if 'curbBandGeometry' in city:
        city['curbBandGeometry']=sh.geometry.mapping(sh.geometry.shape(city['curbBandGeometry']).difference(cut).union(added))
    for target in (city,report):
        if 'curbs' in target:
            target['curbs']['topAreaM2']+=added.area-ground['removedCurbTopAreaM2']
            target['curbs']['serializedSideTriangles']=sum(c['triangles'] for c in scene['chunks'] if c['name'] in ('curb_front','curb_back'))
            target['curbs']['walkingRepair']=ground['curbRepair']
    if 'transitionTerrainCutGeometry' in city:
        removed=sh.geometry.shape(ground['delta']['removed']['groundContactGeometry'])
        city['transitionTerrainCutGeometry']=sh.geometry.mapping(sh.geometry.shape(city['transitionTerrainCutGeometry']).difference(removed).union(cut))
    changed_ids={c['id'] for c in changes}
    for old,new in zip(old_scene['chunks'],scene['chunks']):
        if old['id'] in changed_ids:continue
        assert old==new and digest(base/'canonical/full'/Path(old['file']).name)==digest(folder/Path(new['file']).name)
    assert old_scene['instances']==scene['instances'] and old_scene['materials']==scene['materials']
    assert digest(base/'canonical/terrain.npz')==digest(out/'canonical/terrain.npz')
    save(folder/'scene.json',scene)
    print('WALKING CHECK ALL CANONICAL INTERFACES',flush=True)
    actual=check_interfaces(passage_volumes(city),meshes(out,scene))
    save(out/'walking-interface-audit.json',actual)
    assert actual['passed'],[r for r in actual['checks'] if not r['passed']]
    proof=dict(version=1,parent=base.name,parentCanonicalSha256=product['parentCanonicalSha256'],
        connectionsSha256=connection_digest(city['gradeConnections']),changedChunks=changes,matches=matches,
        selectedSourceParents=sorted({o for p in product['new']['profiles'] for o in p['sourceParents']}),
        ground=ground,canonicalInterfaces=actual,passed=True,
        policy='Rebuild source-dependent complete structural sheets; exact old serialized triangle ownership; all unrelated assets retained.')
    city['initialWalkingRepair']=proof;report['initialWalkingRepair']=proof
    report['gradeConnections']['interfaceCoverage']=coverage
    report['overpassProfiles']=[{k:v for k,v in p.items() if 'Geometry' not in k and k!='extensionHeightCells'} for p in city['overpassProfiles']]
    refresh_stats(scene,report,out);save(folder/'scene.json',scene)
    save_canonical(out/'canonical/urban-model.json',city);save(out/'canonical/validation.json',report)
    save(out/'initial-walking-repair.json',proof)
    print('WALKING STRUCTURES REPAIRED; INDEPENDENT PACKED AUDIT REQUIRED',len(changed_ids),flush=True)


if __name__=='__main__':main()
