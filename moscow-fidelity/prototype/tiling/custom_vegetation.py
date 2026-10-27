"""Install the original model library without changing any plant placement."""
import gzip,hashlib,json,math
from pathlib import Path
import numpy as np
from vegetation_library import catalog,PALETTE
from vegetation_variation import key_for,unit
from object_geometry import pack,export_glb,decode_normals

def install(layer,manifest,folder):
    from approved_vegetation import install as install_approved
    return install_approved(layer,manifest,folder)

def install_legacy(layer,manifest,folder):
    if layer.get('customLibrary'):raise ValueError('Build from original source templates, not an already replaced library')
    rows=catalog(manifest);offset=len(manifest['materials']);old_templates=dict(layer['templates'])
    materials=[dict(name=name,family='vegetation',color=color,roughness=.95,metallic=0,ior=1.5,kind=1,texture=None,alphaCutoff=0) for name,color in PALETTE]
    manifest['materials'].extend(materials);used=set();by_layer={};models=[];template_map={}
    library=folder.parent.parent/'library';library.mkdir(exist_ok=True)
    for row in rows:
        source=row['sourceChunk']
        if source not in used:idx=source;used.add(source)
        else:idx=len(manifest['chunks']);manifest['chunks'].append({})
        file=f'mesh-{idx:03d}.bin.gz'
        meta=pack(row['attributes'],row['materials']+offset,folder/file)
        assert meta and meta['triangles']==len(row['attributes'])
        manifest['chunks'][idx]=dict(id=idx,name=row['id'],category='vegetation',file=file,
            instanced=True,objectGeometry=True,**meta)
        template_map[row['id']]=idx;by_layer.setdefault(row['layer'],[]).append(row['id'])
        model={k:v for k,v in row.items() if k not in {'attributes','materials','components'}}
        model.update(mesh=idx,triangles=meta['triangles'],bounds=meta['bounds'],
            sha256=hashlib.sha256((folder/file).read_bytes()).hexdigest(),file=f"{row['id']}/model.glb")
        models.append(model)
        dest=library/row['id'];dest.mkdir(exist_ok=True)
        single=pack(row['attributes'],row['materials'],dest/'mesh-000.bin.gz')
        m=dict(origin=[0,0,0],materials=materials,textures={},chunks=[dict(id=0,name=row['id'],file='mesh-000.bin.gz',**single)],
            instances=[dict(mesh=0,matrix=[1,0,0,0,0,1,0,0,0,0,1,0])])
        export_glb(m,dest)
        np.savez(dest/'geometry.npz',attributes=row['attributes'],materials=row['materials'])
    instances={i['id']:i for i in manifest['instances'] if i.get('id')}
    counts={m['id']:0 for m in models}
    for plant in layer['vegetation']:
        choices=by_layer[plant['layer']];name=choices[min(len(choices)-1,math.floor(unit(key_for(plant),'model-choice')*len(choices)))]
        assert len(plant['renderInstances'])==1,'A multipart source plant needs a grouped-root adapter'
        plant['sourceTemplates']=list(plant['templates']);plant['templates']=[name];plant['customModel']=name
        for instance in plant['renderInstances']:
            instance['mesh']=template_map[name];instances[instance['id']]['mesh']=template_map[name]
        counts[name]+=1
    layer['templates']=template_map
    layer['customLibrary']=dict(version=1,name='NURAY · гранёная растительность',models=models,sourceTemplates=old_templates,
        materialsOffset=offset,modelsCount=len(models),uniqueTriangles=sum(m['triangles'] for m in models),instancesPerModel=counts,
        policy='Original closed faceted crowns and branched stems; fit every variant to measured 2GIS template min/max, preserving root X=Z=0; source per-plant transforms retained. Collada files were visual references only.')
    layer['policy']['models']=layer['customLibrary']['policy']
    (library/'catalog.json').write_text(json.dumps(layer['customLibrary'],ensure_ascii=False,indent=2))
    return layer['customLibrary']

def verify(layer,manifest,folder):
    if layer['customLibrary'].get('version')==2:
        from approved_vegetation import verify as verify_approved
        return verify_approved(layer,manifest,folder)
    lib=layer['customLibrary'];models={r['id']:r for r in lib['models']}
    assert len(models)==lib['modelsCount']==20
    assert len(layer['templates'])==20
    for name,r in models.items():
        c=manifest['chunks'][r['mesh']]
        assert c['name']==name and c['instanced'] and c['triangles']==r['triangles']<=400
        assert hashlib.sha256((folder/Path(c['file']).name).read_bytes()).hexdigest()==r['sha256']
        assert np.allclose(c['bounds']['min'],r['sourceBounds']['min'],rtol=0,atol=3e-6)
        assert np.allclose(c['bounds']['max'],r['sourceBounds']['max'],rtol=0,atol=3e-6)
        raw=gzip.decompress((folder/Path(c['file']).name).read_bytes())
        words=np.frombuffer(raw[:c['vertexBytes']],'<u4').reshape(-1,8)
        positions=words.view('<f4')[:,:3]
        indices=np.frombuffer(raw[c['vertexBytes']:],'<u4').reshape(-1,3)
        assert len(indices)==r['triangles'] and indices.max()<len(positions)
        assert np.isfinite(positions).all()
        assert np.array_equal(positions[indices].min((0,1)),c['bounds']['min'])
        assert np.array_equal(positions[indices].max((0,1)),c['bounds']['max'])
        tri=positions[indices];cross=np.cross(tri[:,1]-tri[:,0],tri[:,2]-tri[:,0])
        normals=decode_normals(words[:,3])[indices[:,0]]
        assert np.all(np.sum(cross*normals,axis=1)>1e-9)
        mats=words[:,6]&0x7fffffff
        assert np.all((mats>=lib['materialsOffset'])&(mats<lib['materialsOffset']+len(PALETTE)))
    counts={name:0 for name in models}
    for p in layer['vegetation']:
        names=[r['id'] for r in lib['models'] if r['layer']==p['layer']]
        chosen=names[min(len(names)-1,math.floor(unit(key_for(p),'model-choice')*len(names)))]
        assert p['customModel']==chosen and p['templates']==[chosen]
        assert all(i['mesh']==models[chosen]['mesh'] for i in p['renderInstances'])
        counts[chosen]+=1
    assert counts==lib['instancesPerModel']
    return dict(passed=True,models=len(models),uniqueTriangles=lib['uniqueTriangles'],plants=sum(counts.values()),usedModels=sum(n>0 for n in counts.values()),sourceEnvelopesMatched=True)
