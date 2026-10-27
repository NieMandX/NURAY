"""Align shared seat/swing fronts once, preserving all source placements."""
import argparse,gzip,json,shutil
from pathlib import Path
import numpy as np
from street_library import model,TEMPLATE_YAW
from object_geometry import pack,export_glb,decode_normals
from prepare_foundations import digest,save,refresh_stats


def build(base,out):
    assert base.resolve()!=out.resolve() and not out.exists()
    assert json.loads((base/'validation.json').read_text())['passed']
    city=json.loads((base/'canonical/urban-model.json').read_text());scene=json.loads((base/'canonical/full/scene.json').read_text())
    report=json.loads((base/'canonical/validation.json').read_text())
    out.mkdir()
    for name in ['canonical','textures','library']:
        if (base/name).exists():shutil.copytree(base/name,out/name)
    changes=[];layer=city['streetLayer']
    for name,yaw in TEMPLATE_YAW.items():
        if name not in layer['library']:continue
        item=layer['library'][name]
        if item.get('templateYawDegrees',0)==yaw:continue
        assert item.get('templateYawDegrees',0)==0
        t,m=model(name).arrays();chunk=scene['chunks'][item['mesh']]
        path=out/'canonical/full'/Path(chunk['file']).name
        changes.append(dict(id=chunk['id'],model=name,fromYaw=0,toYaw=yaw,beforeSha256=digest(path)))
        meta=pack(t,np.array(layer['materials'])[m],path)
        assert meta['triangles']==chunk['triangles']
        chunk.update(meta);item.update(displayBounds=meta['bounds'],templateYawDegrees=yaw)
    assert changes,'Template directions already aligned'
    rev=dict(version=1,type='street-template-directions',parent=base.name,
             parentValidationSha256=digest(base/'validation.json'),previousRevision=city['geometryRevision'],changedChunks=changes)
    city['geometryRevision']=rev;report['geometryRevision']=rev
    refresh_stats(scene,report,out);save(out/'canonical/full/scene.json',scene)
    export_glb(scene,out/'canonical/full');report['export']['glbBytes']=(out/'canonical/full/model.glb').stat().st_size
    save(out/'canonical/urban-model.json',city);save(out/'canonical/validation.json',report);save(out/'street-objects.json',layer)
    print('DIRECTIONS',changes,flush=True)


def mesh(root,c):
    raw=gzip.decompress((root/'canonical/full'/Path(c['file']).name).read_bytes())
    w=np.frombuffer(raw[:c['vertexBytes']],'<u4').reshape(-1,8);ix=np.frombuffer(raw[c['vertexBytes']:],'<u4').reshape(-1,3)
    return w,ix


def verify_revision(root,city,scene):
    rev=city['geometryRevision'];base=root.parent/rev['parent'];proof=(base/'validation.json').read_bytes()
    assert digest(base/'validation.json')==rev['parentValidationSha256'] and json.loads(proof)['passed']
    before=json.loads((base/'canonical/urban-model.json').read_text());old=json.loads((base/'canonical/full/scene.json').read_text())
    assert before['geometryRevision']==rev['previousRevision']
    def fields(c):
        return {**{k:v for k,v in c.items() if k!='geometryRevision'},'streetLayer':{k:v for k,v in c['streetLayer'].items() if k!='library'}}
    assert fields(city)==fields(before)
    assert {k:v for k,v in scene.items() if k not in {'chunks','stats'}}=={k:v for k,v in old.items() if k not in {'chunks','stats'}}
    changes={r['id']:r for r in rev['changedChunks']};assert len(scene['chunks'])==len(old['chunks'])
    for a,b in zip(old['chunks'],scene['chunks']):
        if a['id'] not in changes:
            assert a==b and (base/'canonical/full'/Path(a['file']).name).read_bytes()==(root/'canonical/full'/Path(b['file']).name).read_bytes();continue
        change=changes[a['id']];assert digest(base/'canonical/full'/Path(a['file']).name)==change['beforeSha256']
        w,ix=mesh(base,a);v,jx=mesh(root,b);p=w.view('<f4')[ix];q=v.view('<f4')[jx]
        assert len(ix)==len(jx)
        assert np.array_equal(p[:,:,:3]*[-1,1,-1],q[:,:,:3])
        assert np.array_equal(w[ix][:,:,4:],v[jx][:,:,4:]),'UV/materials changed'
        n=decode_normals(w[:,3])[ix];nn=decode_normals(v[:,3])[jx]
        assert np.allclose(n*[-1,1,-1],nn,atol=.0001)
        assert {k:x for k,x in a.items() if k not in {'bounds','vertexCount','vertexBytes'}}=={k:x for k,x in b.items() if k not in {'bounds','vertexCount','vertexBytes'}}
    for name,item in city['streetLayer']['library'].items():
        prior=before['streetLayer']['library'][name]
        if item['mesh'] not in changes:assert item==prior;continue
        assert item['templateYawDegrees']==180 and item['displayBounds']==scene['chunks'][item['mesh']]['bounds']
        assert {k:v for k,v in item.items() if k not in {'displayBounds','templateYawDegrees'}}=={k:v for k,v in prior.items() if k not in {'displayBounds','templateYawDegrees'}}
    for name in old['textures']:assert (base/'textures'/name).read_bytes()==(root/'textures'/name).read_bytes()
    assert (base/'canonical/terrain.npz').read_bytes()==(root/'canonical/terrain.npz').read_bytes()
    names={r['model'] for r in rev['changedChunks']}
    count=sum(o.get('model') in names for o in city['streetLayer']['objects'])
    return dict(passed=True,type=rev['type'],templates=len(changes),instances=count,sourcePlacementsUnchanged=True,
                inherited=json.loads(proof)['geometryRevision'])


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--base',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();build(a.base,a.output)
