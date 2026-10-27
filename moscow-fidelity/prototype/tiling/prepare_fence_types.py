"""Replace only canonical fence geometry using preserved source lines and types."""
import argparse, gzip, json, shutil
from pathlib import Path
import numpy as np
from fence_geometry import build as build_fences, EXTRA_MATERIALS, POLICY, resolve
from street_placement import SurfaceSampler, GROUND_NAMES
from object_geometry import pack, export_glb, clip_triangles, decode_normals
from prepare_foundations import digest, save, refresh_stats, rounded_ground_contact
from canonical_store import load_canonical, save_canonical, copy_asset
from canonical_parent import load_parent
import gc


def profile_ground(ground, profile, station):
    """Retain the declared support at a rounded shared surface boundary."""
    a,b=np.asarray(profile['a']),np.asarray(profile['b']);offset=np.asarray(profile['groundOffsetM'])
    q=a*(1-station)+b*station+offset
    scale=max(1.,float(np.max(np.abs([a,b,q]))))
    # Unlike foundation panel endpoints, fence profiles have no decimal snap.
    return rounded_ground_contact(ground,q,np.sqrt(2.)*16*np.spacing(scale),tuple(profile['ground']))


def build(base,out,inventory):
    assert not out.exists() and base.parent==out.parent
    proof=json.loads((base/'validation.json').read_text());assert proof['passed']
    city=load_canonical(base/'canonical/urban-model.json');scene=json.loads((base/'canonical/full/scene.json').read_text())
    gc.freeze()
    report=json.loads((base/'canonical/validation.json').read_text());catalog=json.loads(inventory.read_text())
    rules=[r for r in catalog['sourceRulesByLayer']['Fence'] if r['type']=='model' and r['style'].get('visibility','visible')=='visible']
    records=json.loads(gzip.decompress((base/'canonical/street-source-evidence.json.gz').read_bytes()))['records']
    ground=SurfaceSampler(base,scene,GROUND_NAMES);mesh,objects,account,views,stats=build_fences(records,city,ground,rules)
    out.mkdir()
    for name in ['canonical','textures','library']:
        if (base/name).exists():shutil.copytree(base/name,out/name,copy_function=copy_asset)
    layer=city['streetLayer'];assert len(layer['materials']) in (9,11)
    if len(layer['materials'])==9:
        layer['materials'].extend(range(len(scene['materials']),len(scene['materials'])+len(EXTRA_MATERIALS)))
        scene['materials'].extend(EXTRA_MATERIALS)
    else:assert [scene['materials'][i] for i in layer['materials'][9:]]==EXTRA_MATERIALS
    chunks=[c for c in scene['chunks'] if c['name']=='street-fences'];assert len(chunks)==1
    chunk=chunks[0];t,m=mesh.arrays();ox,oy,_=city['originMSK'];b=city['boundsMSK']
    t,m=clip_triangles(t,m,[b[0]-ox,oy-b[3],b[2]-ox,oy-b[1]])
    meta=pack(t,np.array(layer['materials'])[m],out/'canonical/full'/Path(chunk['file']).name);assert meta
    chunk.update(meta)
    layer['objects']=[o for o in layer['objects'] if o['layer']!='Fence']+objects
    ids={r['sourceRecordId'] for r in records if r['layer']=='Fence'}
    layer['accounting']=[a for a in layer['accounting'] if a['sourceRecordId'] not in ids]+account
    layer['deferred']=[a for a in layer['deferred'] if a['sourceRecordId'] not in ids]+[a for a in account if a['status']=='deferred']
    layer['witnessViews']=[v for v in layer['witnessViews'] if not v['key'].startswith('fence:')]+views
    layer['stats'].update(objects=len(layer['objects']),deferredRecords=len(layer['deferred']),uniqueTriangles=sum(c['triangles'] for c in scene['chunks'] if c.get('streetGeometry')))
    layer['stats']['byLayer']['Fence']=len(objects)
    layer['fences']=dict(policy=POLICY,stats=stats)
    save(out/'canonical/fence-source-rules.json',dict(rules=rules,sourceInventorySha256=digest(inventory),sourceStyleSha256=catalog['provenance']['stylesSha256']))
    revision=dict(version=1,type='fence-types',parent=base.name,previousRevision=city['geometryRevision'],parentValidationSha256=digest(base/'validation.json'),
        changedChunks=[chunk['id']],sourceRulesSha256=digest(out/'canonical/fence-source-rules.json'))
    city['geometryRevision']=revision;report['geometryRevision']=revision
    refresh_stats(scene,report,out);save(out/'canonical/full/scene.json',scene)
    export_glb(scene,out/'canonical/full');report['export']['glbBytes']=(out/'canonical/full/model.glb').stat().st_size
    save_canonical(out/'canonical/urban-model.json',city);save(out/'canonical/validation.json',report);save(out/'street-objects.json',layer)
    print('FENCES',json.dumps(stats),flush=True)


def verify_revision(root,city,scene):
    rev=city['geometryRevision'];base=root.parent/rev['parent'];proof=json.loads((base/'validation.json').read_text())
    assert proof['passed'] and digest(base/'validation.json')==rev['parentValidationSha256']
    before=load_parent(base/'canonical/urban-model.json',city,changed_keys=('geometryRevision','streetLayer'));old=json.loads((base/'canonical/full/scene.json').read_text())
    assert before['geometryRevision']==rev['previousRevision']
    assert {k:v for k,v in before.items() if k not in {'geometryRevision','streetLayer'}}=={k:v for k,v in city.items() if k not in {'geometryRevision','streetLayer'}}
    a,b=before['streetLayer'],city['streetLayer']
    for key in ['library','instances','policy','sourceEvidenceSha256','sourceInventorySha256']:assert a[key]==b[key],key
    assert [o for o in a['objects'] if o['layer']!='Fence']==[o for o in b['objects'] if o['layer']!='Fence']
    added=EXTRA_MATERIALS if len(a['materials'])==9 else []
    assert scene['materials']==old['materials']+added
    assert b['materials']==a['materials']+list(range(len(old['materials']),len(scene['materials'])))
    assert {k:v for k,v in scene.items() if k not in {'chunks','materials','stats'}}=={k:v for k,v in old.items() if k not in {'chunks','materials','stats'}}
    assert len(old['chunks'])==len(scene['chunks']) and len(rev['changedChunks'])==1
    for x,y in zip(old['chunks'],scene['chunks']):
        if x['id'] in rev['changedChunks']:
            assert x['name']==y['name']=='street-fences';continue
        assert x==y and (base/'canonical/full'/Path(x['file']).name).read_bytes()==(root/'canonical/full'/Path(y['file']).name).read_bytes()
    for name in old['textures']:assert (base/'textures'/name).read_bytes()==(root/'textures'/name).read_bytes()
    for f in ['terrain.npz','street-source-evidence.json.gz']:assert (base/'canonical'/f).read_bytes()==(root/'canonical'/f).read_bytes()
    assert digest(root/'canonical/fence-source-rules.json')==rev['sourceRulesSha256']
    rules=json.loads((root/'canonical/fence-source-rules.json').read_text())['rules']
    records={r['sourceRecordId']:r for r in json.loads(gzip.decompress((root/'canonical/street-source-evidence.json.gz').read_bytes()))['records']}
    assert len(b['accounting'])==len(records)==len({r['sourceRecordId'] for r in b['accounting']})
    ground=SurfaceSampler(root,scene,GROUND_NAMES);checks=0
    for o in b['objects']:
        if o['layer']!='Fence':continue
        r=records[o['sourceRecordId']]
        assert o['source']==r['source'] and o['sourceCoordinates']==r['coordinatesMSK']
        assert o['classification']==resolve(r,rules)
        assert o['heightStatus']=='display-default' and o['heightM']==o['classification']['heightM']
        assert abs(o['phaseM']-r['properties'].get('componentDistanceStart',0)*r['source']['coordinateStepM'])<1e-8
        for p in o['groundProfile']:
            for u in [.1,.5,.9]:
                offset=np.array(p['groundOffsetM']);assert np.linalg.norm(offset)<=.02500001
                hit=profile_ground(ground,p,u);assert hit
                assert abs(hit['height']-np.dot(p['heights'],[1-u,u]))<1e-5;checks+=1
        for p in o['uprights']:
            offset=np.array(p['groundOffsetM']);assert np.linalg.norm(offset)<=.02500001
            hit=ground.ground(*(np.array(p['point'])+offset));assert hit and abs(hit['height']-p['height'])<1e-7
    c=scene['chunks'][rev['changedChunks'][0]];raw=gzip.decompress((root/'canonical/full'/Path(c['file']).name).read_bytes())
    w=np.frombuffer(raw[:c['vertexBytes']],'<u4').reshape(-1,8);ix=np.frombuffer(raw[c['vertexBytes']:],'<u4').reshape(-1,3)
    assert np.isin(w[:,6]&0x7fffffff,b['materials']).all()
    p=w.view('<f4')[ix,:3].astype(float);n=np.cross(p[:,1]-p[:,0],p[:,2]-p[:,0]);valid=np.linalg.norm(n,axis=1)>1e-9
    assert np.all(np.sum(n[valid]*decode_normals(w[:,3])[ix[valid,0]],axis=1)>0)
    assert b['fences']['policy']==POLICY
    assert len([o for o in b['objects'] if o['layer']=='Fence'])==b['fences']['stats']['placed']
    return dict(passed=True,type=rev['type'],**b['fences']['stats'],groundProfileChecks=checks,unrelatedGeometryUnchanged=True,inherited=proof['geometryRevision'])


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--base',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--inventory',type=Path,required=True)
    a=p.parse_args();build(a.base,a.output,a.inventory)
