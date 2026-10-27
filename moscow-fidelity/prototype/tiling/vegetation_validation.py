"""Instance-only revision: preserve geometry and check every seeded transform."""
import hashlib,json
from pathlib import Path
import numpy as np
from vegetation_variation import parameters,transform,verify
from canonical_store import load_canonical

def verify_revision(root,city,manifest):
    rev=city['geometryRevision'];parent=root.parent/rev['parent']
    receipt=(parent/'validation.json').read_bytes()
    assert hashlib.sha256(receipt).hexdigest()==rev['parentValidationSha256'] and json.loads(receipt)['passed']
    old=json.loads((parent/'canonical/full/scene.json').read_text())
    before=load_canonical(parent/'canonical/urban-model.json')
    assert rev['previousRevision']==before.get('geometryRevision')
    assert set(city)==set(before)
    for k in city:
        if k not in {'geometryRevision','objectLayer','rules'}:assert city[k]==before[k],k
    assert {k:v for k,v in city['rules'].items() if k!='vegetationVariation'}=={k:v for k,v in before['rules'].items() if k!='vegetationVariation'}
    for k in manifest:
        if k!='instances':assert manifest[k]==old[k],k
    for c in old['chunks']:
        filename=Path(c['file']).name
        assert (root/'canonical/full'/filename).read_bytes()==(parent/'canonical/full'/filename).read_bytes()
    for name in old['textures']:
        assert (root/'textures'/name).read_bytes()==(parent/'textures'/name).read_bytes()
    assert (root/'canonical/terrain.npz').read_bytes()==(parent/'canonical/terrain.npz').read_bytes()
    layer=city['objectLayer'];old_layer=before['objectLayer']
    for k in layer:
        if k not in {'vegetation','policy','variation'}:assert layer[k]==old_layer[k],k
    assert {k:v for k,v in layer['policy'].items() if k!='vegetation'}=={k:v for k,v in old_layer['policy'].items() if k!='vegetation'}
    assert len(layer['vegetation'])==len(old_layer['vegetation'])
    changed={}
    for a,b in zip(old_layer['vegetation'],layer['vegetation']):
        assert {k:v for k,v in a.items() if k not in {'variation','renderInstances'}}=={k:v for k,v in b.items() if k not in {'variation','renderInstances'}}
        assert len(a['renderInstances'])==len(b['renderInstances'])
        for i,j in zip(a['renderInstances'],b['renderInstances']):
            matrix,base=transform(i['matrix'],parameters(a),i.get('variationBaseLinear'))
            assert j=={**i,'matrix':matrix,'variationBaseLinear':base}
            assert j['matrix'][3::4]==i['matrix'][3::4]
            changed[i['id']]=j
    assert len(manifest['instances'])==len(old['instances'])
    assert manifest['instances']==[changed.get(i.get('id'),i) for i in old['instances']]
    # Validate inherited landscape rules from their actual immutable files.
    from portal_validation import verify_revision as verify_parent
    inherited=verify_parent(parent,before,old)
    return dict(type='vegetation-variation',**verify(layer,manifest),preservedChunks=len(old['chunks']),
        originalPlacementsUnchanged=True,geometryMaterialsTexturesUnchanged=True,inherited=inherited)
