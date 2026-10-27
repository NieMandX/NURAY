"""Install reviewed workshop GLBs as shared meshes; never regenerate the plants."""
import gzip, hashlib, json, shutil, struct
from pathlib import Path
import numpy as np
from object_geometry import pack, decode_normals

ASSETS = Path(__file__).resolve().parents[2] / 'web-preview/vegetation-study/assets'
# Scene art direction, separate from the immutable workshop model and source
# instance scale. Apply about the template root, once, before tile packing.
SCENE_MODEL_SCALES = {'bush': 2.0, 'growth': 2.0, 'pine': 2.0, 'thuja': 2.0}
# Renderer coordinates are Y-up. Axis proportions are independent of the
# uniform species size and never modify the source instance transform.
SCENE_MODEL_AXIS_SCALES = {
    'open': [1.,2.,1.], 'compact': [1.,2.,1.], 'birch': [1.,2.,1.],
    'spruce': [2/3,1.,2/3],
}
FAMILIES = [
    ('Model_tree_shrubs_point', 'Template_autumn_bush.001', 'bush'),
    ('Model_tree_deciduous_point', 'Template_autumn_tree.001', 'open'),
    ('Model_tree_deciduous_growth_point', 'Template_autumn_porosl.001', 'growth'),
    ('Model_tree_deciduous_low_point', 'Template_autumn_listvennoe.001', 'low'),
    ('Model_tree_coniferous_point', 'Template_summer_pine.001', 'spruce'),
    ('Model_tree_deciduous_wide_crown_point', 'Template_autumn_bigtree.001', 'compact'),
    ('Model_tree_narrow_tall_point', 'Template_autumn_tuya.001', 'thuja'),
    ('Model_tree_birch_point', 'Template_autumn_birch.002', 'birch'),
    ('Model_tree_pine_point', 'Template_summer_sosna.001', 'pine'),
]

def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def read_glb(path):
    raw=Path(path).read_bytes()
    assert struct.unpack_from('<4sII',raw)==(b'glTF',2,len(raw))
    size=struct.unpack_from('<I',raw,12)[0];doc=json.loads(raw[20:20+size]);binary=raw[28+size:]
    def read(index):
        a=doc['accessors'][index];v=doc['bufferViews'][a['bufferView']]
        assert 'byteStride' not in v
        width={'VEC3':3,'SCALAR':1}[a['type']];dtype={5126:'<f4',5125:'<u4'}[a['componentType']]
        return np.frombuffer(binary,dtype,a['count']*width,v.get('byteOffset',0)+a.get('byteOffset',0)).reshape(-1,width)
    primitives=doc['meshes'][0]['primitives'];attrs=primitives[0]['attributes']
    p=read(attrs['POSITION']).reshape(-1,3,3);n=read(attrs['NORMAL']).reshape(-1,3,3)
    colors=read(attrs['COLOR_0']).reshape(-1,3,3);mats=np.full(len(p),-1,dtype=np.int32)
    for prim in primitives:
        assert prim['attributes']==attrs
        ix=read(prim['indices']).reshape(-1,3)
        assert np.all(ix[:,0]%3==0) and np.array_equal(ix[:,1:],ix[:,:1]+[1,2])
        assert np.all(mats[ix[:,0]//3]==-1)
        mats[ix[:,0]//3]=prim['material']
    assert np.all(mats>=0) and np.isfinite(p).all() and np.isfinite(n).all()
    return doc,p,n,colors,mats

def palette_for(base,hex_color):
    srgb=np.array([int(hex_color[k:k+2],16)/255 for k in (1,3,5)])
    linear=np.where(srgb<=.04045,srgb/12.92,((srgb+.055)/1.055)**2.4)
    reference=np.asarray(base[0]['color'])
    return [{**m,'color':np.minimum(1,np.asarray(m['color'])*linear/reference).tolist()} if i<4 else dict(m)
            for i,m in enumerate(base)]

def geometry(path,palette,scale,axis_scale=None):
    doc,p,n,colors,mats=read_glb(path)
    axes=np.asarray([1.,1.,1.] if axis_scale is None else axis_scale,dtype=float)
    assert axes.shape==(3,) and np.isfinite(axes).all() and np.all(axes>0)
    assert np.isfinite(scale) and scale>0
    # Inverse-transpose keeps the approved smoothing under nonuniform scaling.
    # Keep identity normals bit-exact for all historical uniform-only releases.
    if not np.array_equal(axes,[1.,1.,1.]):
        n=n.astype(float)/axes
        n=(n/np.linalg.norm(n,axis=2,keepdims=True)).astype('<f4')
    # A scalar tint reproduces the approved linear COLOR_0 without an RGB8 loss.
    factors=np.ones((len(p),3),dtype='<f4');foliage=mats<4
    bases=np.asarray([m['color'] for m in palette])[mats]
    factors[foliage]=(colors[foliage,:,1]/bases[foliage,None,1]).astype('<f4')
    actual=bases[:,None,:]*factors[:,:,None]
    expected=colors*np.asarray([m['pbrMetallicRoughness']['baseColorFactor'][:3] for m in doc['materials']])[mats,None,:]
    assert np.allclose(actual,expected,rtol=0,atol=8e-8), 'Approved color must survive scalar encoding'
    assert actual.max()<=.65, 'Road markings remain the brightest materials'
    a=np.concatenate([(p.astype(float)*scale*axes).astype('<f4'),n,np.zeros((len(p),3,2),dtype='<f4')],axis=2)
    return a,mats,factors,expected

def install(layer,manifest,folder):
    if layer.get('customLibrary'):raise ValueError('Install from source templates, never an already replaced library')
    choices=json.loads((ASSETS/'choices.json').read_text())
    index=json.loads((ASSETS/'library/index.json').read_text())
    catalog=json.loads((ASSETS/'catalog.json').read_text())
    selected={m['id']:m for m in index['models']};catalog_rows={m['id']:m for m in catalog['models']}
    assert all(model in choices and model in selected for _,_,model in FAMILIES)
    old_templates=dict(layer['templates']);offset=len(manifest['materials'])
    library=folder.parent.parent/'library';library.mkdir(exist_ok=True)
    shutil.copy2(ASSETS/'library/index.json',library/'approved-index.json')
    material_ids={};models=[];template_map={};by_layer={}
    for source_layer,template,model in FAMILIES:
        if template not in old_templates:continue
        approved=selected[model];source=ASSETS/approved['file']
        assert digest(source)==approved['glbSha256'] and choices[model]['selectedBy']=='user'
        idx=old_templates[template];source_chunk=manifest['chunks'][idx];study=catalog_rows[model]
        # Retain reviewed proportions and the source-class height normalization.
        # The airy tree represents ordinary deciduous, whose source template is
        # shorter than the wide-tree reference used in the workshop. Uniform
        # height normalization preserves the artist's proportions and root.
        source_height=source_chunk['bounds']['max'][1]-source_chunk['bounds']['min'][1]
        reference_height=study['sourceBounds']['max'][1]-study['sourceBounds']['min'][1]
        scale=source_height/reference_height if template!=study['sourceTemplate'] else 1.
        scene_scale=SCENE_MODEL_SCALES.get(model,1.)
        axis_scale=SCENE_MODEL_AXIS_SCALES.get(model,[1.,1.,1.])
        scale*=scene_scale
        palette=palette_for(catalog['materials'],approved['foliageColor']);remap=[]
        for material in palette:
            key=json.dumps(material,sort_keys=True)
            if key not in material_ids:
                material_ids[key]=len(manifest['materials']);manifest['materials'].append(material)
            remap.append(material_ids[key])
        a,mats,tints,_=geometry(source,palette,scale,axis_scale);file=f'mesh-{idx:03d}.bin.gz'
        meta=pack(a,np.asarray(remap)[mats],folder/file,tints=tints)
        assert meta['triangles']==approved['triangles']
        name='nuray-approved-'+model
        manifest['chunks'][idx]=dict(id=idx,name=name,category='vegetation',file=file,
            instanced=True,objectGeometry=True,vertexTint=True,**meta)
        dest=library/model;dest.mkdir(exist_ok=True)
        shutil.copy2(source,dest/'model.glb')
        shutil.copy2(ASSETS/'library'/model/'selection.json',dest/'selection.json')
        record=dict(id=name,model=model,label=approved['label'],layer=source_layer,mesh=idx,
            sourceTemplate=template,sourceChunk=idx,sourceBounds=source_chunk['bounds'],
            referenceTemplate=study['sourceTemplate'],referenceBounds=study['sourceBounds'],
            uniformTemplateScale=scale,sceneScale=scene_scale,sceneAxisScale=axis_scale,triangles=meta['triangles'],bounds=meta['bounds'],
            file=f'{model}/model.glb',approvedGlbSha256=approved['glbSha256'],
            variant=approved['variant'],smoothingAngle=approved['smoothingAngle'],
            foliageColor=approved['foliageColor'],curvatureStrength=approved['curvatureStrength'],
            materialIndices=remap,sha256=digest(folder/file))
        models.append(record);template_map[name]=idx;by_layer[source_layer]=name
    instances={i['id']:i for i in manifest['instances'] if i.get('id')};counts={m['id']:0 for m in models}
    for plant in layer['vegetation']:
        assert plant['layer'] in by_layer, 'Unmapped source vegetation class'
        name=by_layer[plant['layer']]
        assert len(plant['renderInstances'])==1, 'Multipart source plant needs a grouped-root adapter'
        plant['sourceTemplates']=list(plant['templates']);plant['templates']=[name];plant['customModel']=name
        for inst in plant['renderInstances']:
            inst['mesh']=template_map[name];instances[inst['id']]['mesh']=template_map[name]
        counts[name]+=1
    layer['templates']=template_map
    lib=dict(version=2,name='NURAY · утверждённая мастерская',models=models,sourceTemplates=old_templates,
        materialsOffset=offset,modelsCount=len(models),uniqueTriangles=sum(m['triangles'] for m in models),
        instancesPerModel=counts,libraryIndexSha256=digest(ASSETS/'library/index.json'),
        policy='Approved workshop GLBs with explicit per-species scene size/proportions and inverse-transpose normals; linear per-corner curvature tint in raster, ray tracing and GLB; unchanged instance matrices, roots, IDs, tile ownership and deterministic variation. Uniform source-class normalization when the workshop reference differs; no procedural regeneration.')
    layer['customLibrary']=lib;layer['policy']['models']=lib['policy']
    (library/'catalog.json').write_text(json.dumps(lib,ensure_ascii=False,indent=2)+'\n')
    return lib

def verify(layer,manifest,folder):
    lib=layer['customLibrary'];assert lib['version']==2
    assert digest(folder.parent.parent/'library/approved-index.json')==lib['libraryIndexSha256']
    assert len(lib['models'])==lib['modelsCount']==len(layer['templates'])
    mapping={source:(template,model) for source,template,model in FAMILIES}
    names={};max_color_error=0.;max_normal_error=0.
    for row in lib['models']:
        template,model=mapping[row['layer']];assert (template,model)==(row['sourceTemplate'],row['model'])
        names[row['layer']]=row['id'];source=folder.parent.parent/'library'/row['file']
        assert digest(source)==row['approvedGlbSha256']
        palette=[manifest['materials'][i] for i in row['materialIndices']]
        a,mats,tints,expected_colors=geometry(source,palette,row['uniformTemplateScale'],row.get('sceneAxisScale'))
        c=manifest['chunks'][row['mesh']];assert c['name']==row['id'] and c['vertexTint'] and c['instanced']
        assert c['triangles']==row['triangles']==len(a)
        assert digest(folder/Path(c['file']).name)==row['sha256']
        raw=gzip.decompress((folder/Path(c['file']).name).read_bytes())
        words=np.frombuffer(raw[:c['vertexBytes']],'<u4').reshape(-1,8);v=words.view('<f4')
        ix=np.frombuffer(raw[c['vertexBytes']:],'<u4').reshape(-1,3)
        assert np.array_equal(v[ix,:3],a[:,:,:3]), 'Approved positions changed'
        assert np.array_equal(v[ix,7],tints)
        assert np.array_equal(words[ix[:,0],6]&0x7fffffff,np.asarray(row['materialIndices'])[mats])
        normal_error=float(np.max(np.abs(decode_normals(words[:,3])[ix]-a[:,:,3:6])))
        assert normal_error<.00015, normal_error
        colors=np.asarray([m['color'] for m in palette])[mats,None,:]*v[ix,7,None]
        color_error=float(np.max(np.abs(colors-expected_colors)));assert color_error<8e-8
        max_color_error=max(max_color_error,color_error);max_normal_error=max(max_normal_error,normal_error)
        assert c['bounds']==row['bounds']
    counts={m['id']:0 for m in lib['models']}
    for p in layer['vegetation']:
        name=names[p['layer']];assert p['customModel']==name and p['templates']==[name]
        assert all(i['mesh']==layer['templates'][name] for i in p['renderInstances']);counts[name]+=1
    assert counts==lib['instancesPerModel']
    return dict(passed=True,models=len(counts),plants=sum(counts.values()),uniqueTriangles=lib['uniqueTriangles'],
        usedModels=sum(n>0 for n in counts.values()),approvedShapesPreserved=True,
        maxPackedNormalError=max_normal_error,maxLinearColorError=max_color_error)

def verify_revision(root,city,manifest):
    rev=city['geometryRevision'];parent=root.parent/rev['parent']
    assert digest(parent/'validation.json')==rev['parentValidationSha256']
    assert json.loads((parent/'validation.json').read_text())['passed']
    before=json.loads((parent/'canonical/urban-model.json').read_text())
    old=json.loads((parent/'canonical/full/scene.json').read_text())
    assert rev['previousRevision']==before['geometryRevision']
    assert {k:v for k,v in city.items() if k not in {'geometryRevision','objectLayer'}}=={k:v for k,v in before.items() if k not in {'geometryRevision','objectLayer'}}
    layer=city['objectLayer'];prior=before['objectLayer'];lib=layer['customLibrary']
    excluded={'vegetation','templates','customLibrary','stats','policy'}
    assert {k:v for k,v in layer.items() if k not in excluded}=={k:v for k,v in prior.items() if k not in excluded}
    assert {k:v for k,v in layer['policy'].items() if k!='models'}==prior['policy']
    for key,value in prior['stats'].items():
        if key not in {'treeTemplates','materials','uniqueObjectTriangles','expandedObjectTriangles'}:assert layer['stats'][key]==value
    assert lib['sourceTemplates']==prior['templates']
    changed=set(prior['templates'].values());assert {r['id'] for r in rev['changedChunks']}==changed
    assert rev['newChunks']==[] and len(manifest['chunks'])==len(old['chunks'])
    assert manifest['materials'][:len(old['materials'])]==old['materials']
    assert lib['materialsOffset']==len(old['materials'])
    for row in lib['models']:
        source=old['chunks'][row['sourceChunk']]
        assert row['sourceTemplate']==source['name'] and row['sourceBounds']==source['bounds']
    for c in old['chunks']:
        if c['id'] in changed:continue
        assert manifest['chunks'][c['id']]==c
        assert (root/'canonical/full'/Path(c['file']).name).read_bytes()==(parent/'canonical/full'/Path(c['file']).name).read_bytes()
    assert {k:v for k,v in manifest.items() if k not in {'chunks','materials','instances','stats'}}=={k:v for k,v in old.items() if k not in {'chunks','materials','instances','stats'}}
    assert (root/'canonical/terrain.npz').read_bytes()==(parent/'canonical/terrain.npz').read_bytes()
    assert digest(root/'canonical/terrain.npz')==rev['terrainSha256']
    for name in old['textures']:assert (root/'textures'/name).read_bytes()==(parent/'textures'/name).read_bytes()
    assert len(layer['vegetation'])==len(prior['vegetation']);updates={}
    for a,b in zip(prior['vegetation'],layer['vegetation']):
        excluded={'templates','sourceTemplates','customModel','renderInstances'}
        assert {k:v for k,v in a.items() if k not in excluded}=={k:v for k,v in b.items() if k not in excluded}
        assert b['sourceTemplates']==a['templates'] and len(a['renderInstances'])==len(b['renderInstances'])
        for i,j in zip(a['renderInstances'],b['renderInstances']):
            assert {k:v for k,v in i.items() if k!='mesh'}=={k:v for k,v in j.items() if k!='mesh'}
            updates[j['id']]=j
    assert manifest['instances']==[updates.get(i.get('id'),i) for i in old['instances']]
    from portal_validation import verify_revision as verify_parent
    inherited=verify_parent(parent,before,old)
    return dict(type='custom-vegetation',**verify(layer,manifest,root/'canonical/full'),
        placementsUnchanged=True,unrelatedGeometryUnchanged=True,inherited=inherited)
