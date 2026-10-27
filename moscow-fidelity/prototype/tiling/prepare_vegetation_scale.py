"""Apply absolute per-species scene scales to immutable approved plant meshes.

The workshop GLBs and source instances stay unchanged. Rebuilding a release
uses its recorded multiplier, so running the rule again cannot compound it.
"""
import argparse,json,shutil
from pathlib import Path
import numpy as np
from approved_vegetation import SCENE_MODEL_SCALES,SCENE_MODEL_AXIS_SCALES,digest,geometry,verify
from object_geometry import pack,export_glb

def save(path,value):
    path.write_text(json.dumps(value,ensure_ascii=False,separators=(',',':')))

def build(base,out):
    assert base.resolve()!=out.resolve() and not out.exists()
    assert json.loads((base/'validation.json').read_text())['passed']
    city=json.loads((base/'canonical/urban-model.json').read_text())
    scene=json.loads((base/'canonical/full/scene.json').read_text())
    report=json.loads((base/'canonical/validation.json').read_text())
    out.mkdir()
    for name in ['canonical','textures','library']:
        shutil.copytree(base/name,out/name)
    if (base/'street-objects.json').exists():
        shutil.copy2(base/'street-objects.json',out/'street-objects.json')
    folder=out/'canonical/full';lib=city['objectLayer']['customLibrary'];changes=[]
    for model in lib['models']:
        prior=model.get('sceneScale',1.)
        target=SCENE_MODEL_SCALES.get(model['model'],1.)
        prior_axes=model.get('sceneAxisScale',[1.,1.,1.])
        target_axes=SCENE_MODEL_AXIS_SCALES.get(model['model'],[1.,1.,1.])
        if prior==target and prior_axes==target_axes:continue
        ratio=target/prior
        axis_ratio=np.asarray(target_axes)/prior_axes
        model['uniformTemplateScale']*=ratio
        palette=[scene['materials'][i] for i in model['materialIndices']]
        attrs,mats,tints,_=geometry(out/'library'/model['file'],palette,model['uniformTemplateScale'],target_axes)
        chunk=scene['chunks'][model['mesh']];path=folder/Path(chunk['file']).name
        changes.append(dict(model=model['model'],chunk=chunk['id'],fromScale=prior,toScale=target,
                            ratio=ratio,fromAxisScale=prior_axes,toAxisScale=target_axes,
                            axisRatio=axis_ratio.tolist(),beforeSha256=digest(path)))
        meta=pack(attrs,np.asarray(model['materialIndices'])[mats],path,tints=tints)
        assert meta['triangles']==chunk['triangles']==model['triangles']
        chunk.update(meta)
        model.update(sceneScale=target,sceneAxisScale=target_axes,bounds=meta['bounds'],sha256=digest(path))
    assert changes,'The requested scene scales are already installed'
    revision=dict(version=2,type='vegetation-size',parent=base.name,
        previousRevision=city['geometryRevision'],parentValidationSha256=digest(base/'validation.json'),
        changedModels=changes,rule='absolute per-species uniform and axis scales about root; inverse-transpose normals; source instances unchanged')
    city['geometryRevision']=revision;report['geometryRevision']=revision
    save(out/'library/catalog.json',lib)
    report['objectLayer']['customLibrary']=verify(city['objectLayer'],scene,folder)
    save(folder/'scene.json',scene)
    export_glb(scene,folder);report['export']['glbBytes']=(folder/'model.glb').stat().st_size
    save(out/'canonical/urban-model.json',city);save(out/'canonical/validation.json',report)
    print(json.dumps(changes,ensure_ascii=False),flush=True)

def verify_revision(root,city,scene):
    rev=city['geometryRevision'];parent=root.parent/rev['parent']
    assert digest(parent/'validation.json')==rev['parentValidationSha256']
    assert json.loads((parent/'validation.json').read_text())['passed']
    before=json.loads((parent/'canonical/urban-model.json').read_text())
    old=json.loads((parent/'canonical/full/scene.json').read_text())
    assert rev['previousRevision']==before['geometryRevision']
    # Only model metadata may change in the city; positions, source sizes,
    # terrain, roads, object inventories and random transforms remain identical.
    def without_model_rows(c):
        layer=c['objectLayer']
        library={k:v for k,v in layer['customLibrary'].items() if k!='models'}
        layer={**layer,'customLibrary':library}
        return {**{k:v for k,v in c.items() if k!='geometryRevision'},'objectLayer':layer}
    assert without_model_rows(city)==without_model_rows(before)
    assert {k:v for k,v in scene.items() if k!='chunks'}=={k:v for k,v in old.items() if k!='chunks'}
    changes={r['chunk']:r for r in rev['changedModels']};assert len(changes)==len(rev['changedModels'])
    assert len(scene['chunks'])==len(old['chunks'])
    for c,d in zip(old['chunks'],scene['chunks']):
        a=parent/'canonical/full'/Path(c['file']).name;b=root/'canonical/full'/Path(d['file']).name
        if c['id'] in changes:
            change=changes[c['id']];assert digest(a)==change['beforeSha256']
            # Inverse-transpose normals can separate formerly identical packed
            # vertices. The approved-library check below verifies every corner;
            # triangle topology is unchanged, but deduplicated counts may differ.
            mutable={'bounds','vertexBytes','vertexCount'}
            assert {k:v for k,v in c.items() if k not in mutable}=={k:v for k,v in d.items() if k not in mutable}
            for side in ['min','max']:
                assert np.allclose(np.array(c['bounds'][side])*change['ratio']*change.get('axisRatio',[1.,1.,1.]),d['bounds'][side],rtol=0,atol=2e-6)
        else:assert c==d and a.read_bytes()==b.read_bytes()
    old_models=before['objectLayer']['customLibrary']['models']
    for a,b in zip(old_models,city['objectLayer']['customLibrary']['models']):
        if b['mesh'] not in changes:assert a==b;continue
        change=changes[b['mesh']]
        assert b['model']==change['model'] and a.get('sceneScale',1.)==change['fromScale']
        assert b['sceneScale']==change['toScale'] and change['ratio']==change['toScale']/change['fromScale']
        if rev['version']>=2:
            assert a.get('sceneAxisScale',[1.,1.,1.])==change['fromAxisScale']
            assert b['sceneAxisScale']==change['toAxisScale']
            assert np.array_equal(change['axisRatio'],np.asarray(change['toAxisScale'])/change['fromAxisScale'])
        assert b['uniformTemplateScale']==a['uniformTemplateScale']*change['ratio']
        mutable={'sceneScale','sceneAxisScale','uniformTemplateScale','bounds','sha256'}
        assert {k:v for k,v in a.items() if k not in mutable}=={k:v for k,v in b.items() if k not in mutable}
    for name in old['textures']:
        assert (root/'textures'/name).read_bytes()==(parent/'textures'/name).read_bytes()
    assert (root/'canonical/terrain.npz').read_bytes()==(parent/'canonical/terrain.npz').read_bytes()
    library_check=verify(city['objectLayer'],scene,root/'canonical/full')
    ids={r['model'] for r in rev['changedModels']}
    count=sum(city['objectLayer']['customLibrary']['instancesPerModel'][r['id']]
              for r in city['objectLayer']['customLibrary']['models'] if r['model'] in ids)
    return dict(passed=True,type='vegetation-size',changedModels=len(changes),affectedPlants=count,
                rootsAndInstanceTransformsUnchanged=True,unrelatedGeometryUnchanged=True,
                approvedLibrary=library_check)

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--base',type=Path,required=True);ap.add_argument('--output',type=Path,required=True)
    a=ap.parse_args();build(a.base,a.output)
