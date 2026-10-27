"""Independent checks of the serialized additions and immutable parent geometry."""
import gzip, hashlib, json
from pathlib import Path
import numpy as np
from street_placement import owner, transform, SurfaceSampler, GROUND_NAMES
from canonical_store import load_canonical

def verify_revision(root,city,manifest):
    revision=city['geometryRevision'];parent=root.parent/revision['parent'];layer=city['streetLayer']
    proof=(parent/'validation.json').read_bytes()
    assert hashlib.sha256(proof).hexdigest()==revision['parentValidationSha256'] and json.loads(proof)['passed']
    old=json.loads((parent/'canonical/full/scene.json').read_text());before=load_canonical(parent/'canonical/urban-model.json')
    # A fresh canonical/object/rail build has no earlier refinement revision.
    assert before.get('geometryRevision')==revision['previousRevision']
    for k in set(before)|set(city):
        if k not in {'geometryRevision','streetLayer'}:assert city[k]==before[k],('Changed existing city',k)
    assert manifest['materials'][:len(old['materials'])]==old['materials'] and manifest['textures']==old['textures']
    assert manifest['instances'][:len(old['instances'])]==old['instances']
    assert manifest['chunks'][:len(old['chunks'])]==old['chunks']
    for c in old['chunks']:
        filename=Path(c['file']).name
        assert (parent/'canonical/full'/filename).read_bytes()==(root/'canonical/full'/filename).read_bytes(),c['name']
    for name in old['textures']:
        assert (parent/'textures'/name).read_bytes()==(root/'textures'/name).read_bytes()
    assert (parent/'canonical/terrain.npz').read_bytes()==(root/'canonical/terrain.npz').read_bytes()
    additions=manifest['chunks'][len(old['chunks']):]
    assert revision['addedChunks']==[c['id'] for c in additions]
    for c in additions:
        raw=gzip.decompress((root/'canonical/full'/Path(c['file']).name).read_bytes());u=np.frombuffer(raw[:c['vertexBytes']],'<u4').reshape(-1,8)
        assert c['streetGeometry'] and np.isfinite(u.view('<f4')[:,:3]).all()
        assert np.all((u[:,6]&0x7fffffff)>=len(old['materials']))
        assert np.all((u[:,6]&0x7fffffff)<len(manifest['materials']))
    evidence=(root/'canonical/street-source-evidence.json.gz').read_bytes()
    assert hashlib.sha256(evidence).hexdigest()==layer['sourceEvidenceSha256']
    records={r['sourceRecordId']:r for r in json.loads(gzip.decompress(evidence))['records']}
    assert not any(r['layer']=='Traffic_light' for r in records.values())
    assert set(records)=={a['sourceRecordId'] for a in layer['accounting']}
    assert len(records)==len(layer['accounting'])
    ground=SurfaceSampler(parent,old,GROUND_NAMES);deck=SurfaceSampler(parent,old,{'overpass_bottom'})
    by_id={i.get('id'):i for i in manifest['instances'] if i.get('id')}
    ox,oy,oz=city['originMSK'];points=0
    for o in layer['objects']:
        r=records[o['sourceRecordId']];assert o['source']==r['source'] and o['layer']==r['layer']!='Traffic_light'
        if 'sourcePoint' in o:assert o['sourcePoint'] in r['coordinatesMSK']
        if o['layer']=='Fence':
            assert o['sourceCoordinates']==r['coordinatesMSK'] and o['heightStatus']=='display-default'
            assert abs(o['phaseM']-r['properties'].get('componentDistanceStart',0)*r['source']['coordinateStepM'])<1e-8
        for inst in o.get('renderInstances',[]):
            assert by_id[inst['id']]==inst
            p=o['sourcePoint'];x,z=p[0]-ox,oy-p[1];hit=ground.ground(x,z);assert hit
            assert abs(hit['height']-o['placement']['surface']['height'])<1e-8
            assert inst['matrix']==transform(o['rotationDegrees'],o['sourceScale'],[x,hit['height'],z])
            assert inst['tileId']==owner(p[0],p[1],city['boundsMSK'],city.get('transportTileSizeM',250))
            points+=1
        if o['layer']=='Road_support_column':
            p=o['placement'];assert p['ground']['height']<p['top']<=p['surface']['height']
        if o['layer']=='Road_support_crossbar':
            p=o['placement'];assert len(p['profile'])>=4
            for sample in p['profile']:
                expected=deck.deck_profile(sample['x'],sample['z'],p['surface'])
                assert abs(expected['height']-sample['surface']['height'])<1e-8
    assert points==len(layer['instances'])==layer['stats']['pointInstances']
    assert len(layer['objects'])==layer['stats']['objects']
    # All parent chunks, placements, terrain, textures and city fields were
    # checked byte-for-byte above. Reuse its hashed successful proof instead of
    # rerunning unrelated, already validated landscape/vegetation revisions.
    inherited=json.loads(proof)['geometryRevision']
    return dict(type='street-objects',passed=True,**layer['stats'],sourceXYVerified=points,
                existingGeometryAndInstancesUnchanged=True,trafficLights=0,inherited=inherited)
