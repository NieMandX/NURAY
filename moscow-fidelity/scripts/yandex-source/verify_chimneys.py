"""Prove shaft replacement preserves all other packed faces and instance data."""
import gzip,hashlib,json
import numpy as np
from apply_crossfall import unpack


def verify(root):
    report=json.loads((root/'industrial-chimneys.json').read_text());base=root.parent/report['parent']
    old=json.loads((base/'canonical/full/scene.json').read_text());new=json.loads((root/'canonical/full/scene.json').read_text())
    path=root/'canonical/chimney-retained-primitives.npz'
    assert hashlib.sha256(path.read_bytes()).hexdigest()==report['retainedPrimitivesSha256']
    kept=dict(np.load(path));changed={r['chunk'] for r in report['changedBuildingBatches']}
    for a,b in zip(old['chunks'],new['chunks']):
        assert a['id']==b['id'] and a['name']==b['name']
        before=gzip.decompress((base/'canonical/full'/a['file']).read_bytes());after=gzip.decompress((root/'canonical/full'/b['file']).read_bytes())
        if a['id'] not in changed:assert before==after,a['id'];continue
        assert a['vertexBytes']==b['vertexBytes'] and before[:a['vertexBytes']]==after[:b['vertexBytes']]
        ix=np.frombuffer(before[a['vertexBytes']:],'<u4').reshape(-1,3);actual=np.frombuffer(after[b['vertexBytes']:],'<u4').reshape(-1,3)
        ids=kept[str(a['id'])];assert len(np.unique(ids))==len(ids) and np.all(ids<len(ix))
        np.testing.assert_array_equal(actual,ix[ids])
        # Every deleted face is in the tall circular shaft volume; low
        # adjoining building faces, including shared footprint edges, survive.
        removed=np.ones(len(ix),bool);removed[ids]=False
        v=np.frombuffer(before[:a['vertexBytes']],'<f4').reshape(-1,8);tri=v[ix[removed],:3]
        valid=np.zeros(len(tri),bool)
        for g in report['groups']:
            center=np.array(g['centerEastNorth'])*[1,-1]
            inside=(np.linalg.norm(tri[:,:,[0,2]]-center,axis=2)<g['baseRadiusM']*1.12).all(1)
            valid|=inside&(tri[:,:,1].max(1)>g['baseLocalM']+g['lowestStepHeightM']-2)
        assert valid.all(),'Removed faces outside shaft envelope'
    assert old['instances']==new['instances'][:len(old['instances'])]
    assert old['materials']==new['materials'][:len(old['materials'])]
    assert old['textures']==new['textures'] and old['origin']==new['origin']
    for c in new['chunks'][len(old['chunks']):]:
        assert c['name']=='industrial-chimneys'
        t,m,_=unpack(root/'canonical/full',c);cross=np.cross(t[:,1,:3]-t[:,0,:3],t[:,2,:3]-t[:,0,:3])
        assert np.all((cross*t[:,:,3:6].mean(1)).sum(1)>0)
        assert all(new['materials'][int(i)]['family']=='IndustrialChimney' for i in np.unique(m))
    return kept
