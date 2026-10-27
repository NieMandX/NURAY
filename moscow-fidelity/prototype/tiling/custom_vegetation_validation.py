"""Only plant meshes/material additions may change in a library revision."""
import hashlib,json
from pathlib import Path
from custom_vegetation import verify
from vegetation_library import PALETTE
from canonical_store import load_canonical

def verify_revision(root,city,manifest):
    if city['objectLayer']['customLibrary'].get('version')==2:
        from approved_vegetation import verify_revision as verify_approved
        return verify_approved(root,city,manifest)
    rev=city['geometryRevision'];parent=root.parent/rev['parent']
    receipt=(parent/'validation.json').read_bytes()
    assert hashlib.sha256(receipt).hexdigest()==rev['parentValidationSha256'] and json.loads(receipt)['passed']
    before=load_canonical(parent/'canonical/urban-model.json')
    old=json.loads((parent/'canonical/full/scene.json').read_text())
    assert rev['previousRevision']==before['geometryRevision']
    assert set(city)==set(before)
    for k in city:
        if k not in {'geometryRevision','objectLayer'}:assert city[k]==before[k],k
    layer=city['objectLayer'];prior=before['objectLayer'];lib=layer['customLibrary']
    for k in set(layer)|set(prior):
        if k not in {'vegetation','templates','customLibrary','stats','policy'}:assert layer[k]==prior[k],k
    assert {k:v for k,v in layer['policy'].items() if k!='models'}==prior['policy']
    for k,v in prior['stats'].items():
        if k not in {'treeTemplates','materials','uniqueObjectTriangles','expandedObjectTriangles'}:assert layer['stats'][k]==v,k
    assert lib['sourceTemplates']==prior['templates']
    old_ids=set(prior['templates'].values())
    assert {r['id'] for r in rev['changedChunks']}==old_ids
    assert rev['newChunks']==list(range(len(old['chunks']),len(manifest['chunks'])))
    assert len(manifest['chunks'])==len(old['chunks'])+11
    assert lib['materialsOffset']==len(old['materials'])
    assert manifest['materials'][:len(old['materials'])]==old['materials']
    additions=manifest['materials'][len(old['materials']):]
    assert [(m['name'],m['color']) for m in additions]==PALETTE
    assert all(m['metallic']==0 and m['roughness']==.95 for m in additions)
    for model in lib['models']:
        source=old['chunks'][model['sourceChunk']]
        assert source['id'] in old_ids and model['sourceTemplate']==source['name']
        assert model['sourceBounds']==source['bounds']
    for c in old['chunks']:
        if c['id'] in old_ids:continue
        assert manifest['chunks'][c['id']]==c
        filename=Path(c['file']).name
        assert (root/'canonical/full'/filename).read_bytes()==(parent/'canonical/full'/filename).read_bytes()
    for k in manifest:
        if k not in {'chunks','materials','instances','stats'}:assert manifest[k]==old[k],k
    for name in old['textures']:
        assert (root/'textures'/name).read_bytes()==(parent/'textures'/name).read_bytes()
    terrain=(root/'canonical/terrain.npz').read_bytes()
    assert terrain==(parent/'canonical/terrain.npz').read_bytes()
    assert hashlib.sha256(terrain).hexdigest()==rev['terrainSha256']
    assert len(layer['vegetation'])==len(prior['vegetation'])
    changes={}
    for a,b in zip(prior['vegetation'],layer['vegetation']):
        excluded={'templates','sourceTemplates','customModel','renderInstances'}
        assert {k:v for k,v in a.items() if k not in excluded}=={k:v for k,v in b.items() if k not in excluded}
        assert b['sourceTemplates']==a['templates']
        assert len(a['renderInstances'])==len(b['renderInstances'])
        for i,j in zip(a['renderInstances'],b['renderInstances']):
            assert {k:v for k,v in i.items() if k!='mesh'}=={k:v for k,v in j.items() if k!='mesh'}
            changes[i['id']]=j
    assert manifest['instances']==[changes.get(i.get('id'),i) for i in old['instances']]
    from portal_validation import verify_revision as verify_parent
    inherited=verify_parent(parent,before,old)
    return dict(type='custom-vegetation',**verify(layer,manifest,root/'canonical/full'),
        placementsUnchanged=True,unrelatedGeometryUnchanged=True,inherited=inherited)
