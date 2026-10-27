"""Immutable railway-only revision. Terrain, structures and paint are copied."""
import argparse, copy, gzip, hashlib, json, subprocess
from pathlib import Path
import numpy as np
from streaming_json import Document
from railway_layer import select_input, generate
from railway_support import POLICY
from prepare_foundations import digest, save, refresh_stats
from object_geometry import pack, export_glb


def field_digest(doc,key):
    with doc.stream(key) as f:return hashlib.file_digest(f,'sha256').hexdigest()


def load_input(doc):
    return select_input({k:doc.read(k) for k in ('boundsMSK','originMSK')},
                        doc.items('features'),doc.items('surfaces'))


def install(base,out,data=None,resume=False):
    assert base.resolve()!=out.resolve()
    fresh=not out.exists()
    if not fresh:
        assert resume and not (out/'validation.json').exists(),'Only an unpublished draft may be rebuilt'
        previous=Document(out/'canonical/urban-model.json').read('geometryRevision')
        assert previous['type']=='railway-levels' and previous['parent']==base.name
    assert json.loads((base/'validation.json').read_text())['passed']
    doc=Document(base/'canonical/urban-model.json')
    print('READ EXISTING RAILWAY FLOORS',flush=True)
    data=data or load_input(doc)
    old_layer=doc.read('railwayLayer');old=json.loads((base/'canonical/full/scene.json').read_text())
    chunks,update=generate(data,old_layer['materials'])
    print('GENERATED RAILWAY OVERLAY',update['stats'],flush=True)
    out.mkdir(exist_ok=True)
    # APFS clones keep the large validated terrain/building assets untouched.
    for name in ('canonical','textures','library','fence-library'):
        if fresh and (base/name).exists():subprocess.run(['cp','-cR',str(base/name),str(out/name)],check=True)
    for name in ('street-objects.json',):
        if (base/name).exists():subprocess.run(['cp','-c',str(base/name),str(out/name)],check=True)
    scene=copy.deepcopy(old);report=json.loads((base/'canonical/validation.json').read_text())
    old_edges={e['source']:e for e in old_layer['edges']};changes=[];chunk_ids={}
    assert {s for s,_,_ in chunks}==set(old_edges)
    for source,tris,mats in chunks:
        cid=old_edges[source]['chunk'];chunk_ids[source]=cid
        if cid is None:
            assert not len(tris),('Unexpected new rail chunk',source)
            continue
        c=old['chunks'][cid];assert c['name']=='railway' and c['sourceObjectIds']==[source]
        path=out/'canonical/full'/Path(c['file']).name
        meta=pack(tris,mats,path);assert meta
        scene['chunks'][cid]=dict(c,**meta)
        before=digest(base/'canonical/full'/Path(c['file']).name);after=digest(path)
        if before!=after:changes.append(dict(id=cid,source=source,beforeSha256=before,afterSha256=after))
    layer=copy.deepcopy(old_layer);layer.update(version=2,**update)
    layer['stats']['textureBytes']=old_layer['stats']['textureBytes']
    layer['policy']['heightBinding']=POLICY
    for row in layer['edges']:row['chunk']=chunk_ids[row['source']]
    revision=dict(version=1,type='railway-levels',parent=base.name,
                  parentValidationSha256=digest(base/'validation.json'),
                  previousRevision=doc.read('geometryRevision'),changedChunks=changes,newChunks=[],
                  policy=POLICY,scope='Railway overlay only; all existing city surfaces and structural meshes are byte-identical.')
    refresh_stats(scene,report,out);save(out/'canonical/full/scene.json',scene)
    export_glb(scene,out/'canonical/full');report['export']['glbBytes']=(out/'canonical/full/model.glb').stat().st_size
    report['railwayLayer']=dict(passed=True,**layer['stats']);report['geometryRevision']=revision
    doc.rewrite(out/'canonical/urban-model.json',dict(railwayLayer=layer,geometryRevision=revision))
    save(out/'canonical/validation.json',report)
    print('RAILWAY LEVEL REVISION',len(changes),'changed railway chunks; all other geometry retained',flush=True)


def verify_revision(root,city,scene):
    revision=city['geometryRevision'];base=root.parent/revision['parent']
    assert revision['type']=='railway-levels' and revision['policy']==POLICY
    assert digest(base/'validation.json')==revision['parentValidationSha256']
    assert json.loads((base/'validation.json').read_text())['passed']
    before=Document(base/'canonical/urban-model.json');after=Document(root/'canonical/urban-model.json')
    assert set(before.fields)==set(after.fields)
    for key in before.fields.keys()-{'railwayLayer','geometryRevision'}:
        assert field_digest(before,key)==field_digest(after,key),('Non-railway city data changed',key)
    assert revision['previousRevision']==before.read('geometryRevision')
    old=json.loads((base/'canonical/full/scene.json').read_text())
    assert {k:v for k,v in old.items() if k not in {'chunks','stats'}}=={k:v for k,v in scene.items() if k not in {'chunks','stats'}}
    assert len(scene['chunks'])==len(old['chunks']) and revision['newChunks']==[]
    changes={c['id']:c for c in revision['changedChunks']}
    for a,b in zip(old['chunks'],scene['chunks'],strict=True):
        pa=base/'canonical/full'/Path(a['file']).name;pb=root/'canonical/full'/Path(b['file']).name
        if a['id'] not in changes:
            assert a==b and digest(pa)==digest(pb),('Unrelated mesh changed',a['id'])
        else:
            c=changes[a['id']]
            assert a['name']==b['name']=='railway' and a['sourceObjectIds']==b['sourceObjectIds']==[c['source']]
            assert digest(pa)==c['beforeSha256'] and digest(pb)==c['afterSha256']
    assert digest(base/'canonical/terrain.npz')==digest(root/'canonical/terrain.npz')
    for name in old['textures']:assert digest(base/'textures'/name)==digest(root/'textures'/name)
    print('VERIFY RAILWAY: terrain, buildings, roads, profiles, paint and all other meshes byte-identical',flush=True)
    data=select_input({k:city[k] for k in ('boundsMSK','originMSK')},city['features'],iter(city['surfaces']))
    chunks,update=generate(data,city['railwayLayer']['materials'])
    import tempfile
    edges={e['source']:e for e in city['railwayLayer']['edges']}
    max_grade=0.;max_rise=0.
    with tempfile.TemporaryDirectory(prefix='nuray-rail-verify-') as temporary:
        for source,tris,mats in chunks:
            cid=edges[source]['chunk']
            if cid is None:assert not len(tris);continue
            actual=scene['chunks'][cid]
            path=Path(temporary)/Path(actual['file']).name;meta=pack(tris,mats,path)
            assert all(actual[k]==v for k,v in meta.items()),('Rail geometry metadata',source)
            assert digest(path)==digest(root/'canonical/full'/Path(actual['file']).name),('Rail does not follow source tier',source)
            raw=gzip.decompress(path.read_bytes());v=np.frombuffer(raw[:actual['vertexBytes']],'<f4').reshape(-1,8)
            ix=np.frombuffer(raw[actual['vertexBytes']:],'<u4').reshape(-1,3);p=v[ix,:3].astype(float)
            delta=np.roll(p,-1,axis=1)-p;horizontal=np.linalg.norm(delta[:,:,[0,2]],axis=2)
            max_grade=max(max_grade,float((np.abs(delta[:,:,1])/np.maximum(horizontal,1e-8)).max()))
            max_rise=max(max_rise,float(np.abs(delta[:,:,1]).max()))
    expected=copy.deepcopy(before.read('railwayLayer'));expected.update(version=2,**update)
    expected['stats']['textureBytes']=before.read('railwayLayer')['stats']['textureBytes']
    expected['policy']['heightBinding']=POLICY
    for e in expected['edges']:e['chunk']=edges[e['source']]['chunk']
    assert json.loads(json.dumps(expected))==city['railwayLayer']
    return dict(passed=True,type='railway-levels',railwayChunks=len(chunks),changedChunks=len(changes),
                terrainAndAllNonRailwayGeometryUnchanged=True,paintContainmentPassed=True,
                maxTriangleEdgeGrade=max_grade,maxTriangleEdgeRiseM=max_rise,
                scope='Source-tier floor sampling and exact regenerated ribbon comparison; inherited parent checks only for byte-identical data and meshes.')


if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--base',type=Path,required=True);ap.add_argument('--output',type=Path,required=True);ap.add_argument('--resume',action='store_true')
    args=ap.parse_args();install(args.base,args.output,resume=args.resume)
