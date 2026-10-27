"""Class-based physical mesh gate, including a checked legacy migration.

Never infer what to erase from height, size, location or a particular provider ID.
New builds record ownership after float32 packing; old builds require exact
inventory counts and source bounds before their primitive order is trusted.
"""
from pathlib import Path
import gzip, hashlib, json, sys
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from source_objects import partition, receipt, POLICY
from semantics import classify, audit
from canonical_store import load_canonical


def read(root, chunk):
    return gzip.decompress((root/'canonical/full'/Path(chunk['file']).name).read_bytes())


def arrays(raw, chunk):
    words=np.frombuffer(raw[:chunk['vertexBytes']], '<u4').reshape(-1,8)
    indices=np.frombuffer(raw[chunk['vertexBytes']:], '<u4').reshape(-1,3)
    assert len(indices)==chunk['triangles']
    return words,indices


def ranges(owners):
    result=[]
    for first,owner in enumerate(owners):
        if result and result[-1]['id']==owner:result[-1]['count']+=1
        else:result.append(dict(id=str(owner),first=first,count=1))
    return result


def ownership(root, city, manifest):
    rows=city['objectLayer']['buildings'];by_id={r['id']:r for r in rows}
    assert len(by_id)==len(rows)
    result={}
    for category in {r['category'] for r in rows}:
        chunks=[c for c in manifest['chunks'] if c.get('objectGeometry') and c['category']==category]
        legacy=[r['id'] for r in rows if r['category']==category for _ in range(r['retainedTriangles'])]
        offset=0
        if not all('sourceObjectRanges' in c for c in chunks):
            assert not any('sourceObjectRanges' in c for c in chunks), 'Mixed ownership versions'
            assert sum(c['triangles'] for c in chunks)==len(legacy), 'Ambiguous legacy ownership; re-extract with primitive ranges'
        for c in chunks:
            if 'sourceObjectRanges' in c:
                owners=[]
                for r in c['sourceObjectRanges']:
                    assert r['first']==len(owners) and r['count']>0
                    owners.extend([r['id']]*r['count'])
            else:owners=legacy[offset:offset+c['triangles']]
            offset+=c['triangles']
            assert len(owners)==c['triangles'] and set(owners)==set(c['sourceObjectIds'])
            words,ix=arrays(read(root,c),c)
            # Audit every assigned primitive, including neighbouring physical
            # meshes, against its original, rigidly placed source bounds.
            for r in ranges(owners):
                row=by_id[r['id']];assert row['category']==category
                p=words.view('<f4')[ix[r['first']:r['first']+r['count']],:3].astype(float)
                world=p[:,:,[0,2,1]]*[1,-1,1]+city['originMSK']
                world[:,:,2]-=row['placement']['shiftM']
                assert np.all(world>=np.array(row['bounds']['min'])-.005), ('ownership lower bound',row['id'])
                assert np.all(world<=np.array(row['bounds']['max'])+.005), ('ownership upper bound',row['id'])
            result[c['id']]=owners
    return result


def filter_mesh(raw, chunk, owners, excluded):
    words,ix=arrays(raw,chunk)
    keep=np.array([owner not in excluded for owner in owners])
    assert len(keep)==len(ix)
    if keep.all():return raw,dict(chunk)
    if not keep.any():
        raise ValueError('Entire legacy chunk is informational: rebuild with prepare_objects.py before packing')
    # Preserve all attributes bit-for-bit: do not recalculate normals or UVs.
    used,remap=np.unique(ix[keep],return_inverse=True)
    vertices=words[used].copy();indices=remap.reshape(-1,3).astype('<u4')
    retained=[owner for owner,ok in zip(owners,keep) if ok]
    p=vertices.view('<f4')[:,:3]
    metadata={**chunk,'vertexBytes':vertices.nbytes,'vertexCount':len(vertices),
              'triangles':len(indices),'bounds':dict(min=p.min(0).tolist(),max=p.max(0).tolist()),
              'sourceObjectIds':sorted(set(retained)),'sourceObjectRanges':ranges(retained)}
    return vertices.tobytes()+indices.tobytes(),metadata


def validate_policy(city,manifest):
    layer=city.get('objectLayer')
    if not layer:return dict(passed=True,buildingObjects=0)
    kept,excluded=partition(layer['buildings'])
    assert not excluded, 'Information-only object reached visible geometry'
    assert layer['sourceGeometry']['policy']==POLICY
    allowed={r['id'] for r in kept}
    for c in manifest['chunks']:
        if c.get('sourceObjectIds') and c.get('category') in {'building','landmark'}:
            assert set(c['sourceObjectIds'])<=allowed, ('Unregistered source mesh',c['id'])
    return dict(passed=True,buildingObjects=len(kept),informationObjectsRendered=0)


def verify_revision(root,city,manifest):
    revision=city['geometryRevision'];parent=root.parent/revision['parent']
    proof=(parent/'validation.json').read_bytes()
    assert hashlib.sha256(proof).hexdigest()==revision['parentValidationSha256'] and json.loads(proof)['passed']
    before=load_canonical(parent/'canonical/urban-model.json')
    old=json.loads((parent/'canonical/full/scene.json').read_text())
    assert revision['previousRevision']==before.get('geometryRevision')
    kept,excluded=partition(before['objectLayer']['buildings']);excluded_ids={r['id'] for r in excluded}
    own=ownership(parent,before,old);changed=[]
    assert len(old['chunks'])==len(manifest['chunks'])
    for a,b in zip(old['chunks'],manifest['chunks']):
        original=read(parent,a)
        expected,meta=filter_mesh(original,a,own[a['id']],excluded_ids) if a['id'] in own else (original,a)
        assert b==meta and read(root,b)==expected, ('Unexpected geometry change',a['id'])
        if expected!=original:changed.append(a['id'])
    assert changed==[r['id'] for r in revision['changedChunks']]
    for k in set(old)|set(manifest):
        if k not in {'chunks','stats'}:assert old[k]==manifest[k],k
    assert city['objectLayer']['buildings']==kept
    assert city['objectLayer']['sourceGeometry']==receipt(excluded)
    for k,v in before['objectLayer'].items():
        if k not in {'buildings','stats','sourceGeometry'}:assert city['objectLayer'][k]==v,k
    assert len(city['features'])==len(before['features'])
    for a,b in zip(before['features'],city['features']):
        assert b=={**a,'semantics':classify(a['layer'],a['properties'],a['geometryType'])}
    for k in set(before)|set(city):
        if k not in {'geometryRevision','objectLayer','features'}:assert city[k]==before[k],k
    for name in manifest.get('textures',{}):
        assert (root/'textures'/name).read_bytes()==(parent/'textures'/name).read_bytes()
    assert (root/'canonical/terrain.npz').read_bytes()==(parent/'canonical/terrain.npz').read_bytes()
    from portal_validation import verify_revision as verify_parent
    inherited=verify_parent(parent,before,old)
    return dict(type='physical-source',**validate_policy(city,manifest),
                removedObjects=len(excluded),removedTriangles=sum(r['retainedTriangles'] for r in excluded),
                physicalGeometryUnchanged=True,materialsAndPlacementsUnchanged=True,inherited=inherited)
