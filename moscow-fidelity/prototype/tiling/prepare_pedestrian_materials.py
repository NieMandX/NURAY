"""Retype existing pedestrian faces from their final source ownership.

No terrain fitting, surface partitioning, triangulation or BVH reconstruction.
Five materials are appended, preserving all prior material IDs and colours.
"""
import argparse,gzip,json,os,subprocess,sys,hashlib,shutil
from pathlib import Path
from collections import Counter
import numpy as np
import shapely as sh
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from pedestrian_materials import RULES,TYPES,POLICY,materials,make_textures
from semantics import classify
from material_remap import remap_many
from object_geometry import export_glb
from prepare_cemetery_cover import save,digest,raw


def select(base,cache):
    signature=digest(base/'objects.json.gz')
    if cache.exists():
        result=json.loads(cache.read_text())
        if result.get('baseRegistrySha256')==signature:return result
    import ijson
    with gzip.open(base/'objects.json.gz','rb') as f:
        features=[r for r in ijson.items(f,'features.item',use_float=True) if r['layer'] in RULES]
    owners={r['id'] for r in features}
    with gzip.open(base/'objects.json.gz','rb') as f:
        surfaces=[s for s in ijson.items(f,'surfaces.item',use_float=True) if s['kind']=='land' and s['owner'] in owners]
    result=dict(baseRegistrySha256=signature,features=features,surfaces=surfaces)
    save(cache,result);return result


def choose_faces(data,c,origin,rows,owner_materials):
    u=np.frombuffer(data[:c['vertexBytes']],'<u4').reshape(-1,8)
    ix=np.frombuffer(data[c['vertexBytes']:],'<u4').reshape(-1,3)
    result=np.full(len(ix),-1,dtype=np.int32)
    polys=np.asarray([sh.geometry.shape(s['geometry']) for s in rows],dtype=object)
    tree=sh.STRtree(polys)
    planes=np.array([s['heightPlane'] for s in rows]);old=np.array([s['material'] for s in rows])
    new=np.array([owner_materials[s['owner']] for s in rows]);area=Counter();max_escape=0.
    for start in range(0,len(ix),16384):
        indices=ix[start:start+16384]
        xyz=u.view('<f4')[indices,:3].astype(float)[:,:,[0,2,1]]*[1,-1,1]+origin
        center=xyz.mean(1)
        hits=tree.query(sh.points(center[:,:2]),predicate='covered_by')
        if not hits.size:continue
        a,b=hits
        ok=(abs(np.sum(planes[b,:2]*center[a,:2],axis=1)+planes[b,2]-center[a,2])<.001)&((u[indices[a,0],6]&0x7fffffff)==old[b])
        a,b=a[ok],b[ok]
        for mid in np.unique(new[b]):
            mask=new[b]==mid;chosen=np.unique(a[mask])
            assert np.all((result[start+chosen]<0)|(result[start+chosen]==mid)), 'Ambiguous material ownership'
            result[start+chosen]=mid
            faces=sh.polygons(xyz[chosen,:,:2])
            domain=sh.union_all(polys[np.unique(b[mask])]).buffer(.0005)
            # Most faces are wholly contained. A prepared containment test
            # avoids expensive polygon overlays for every triangle of a city.
            sh.prepare(domain)
            outside=~sh.covers(domain,faces)
            escape=float(sh.area(sh.difference(faces[outside],domain)).max(initial=0))
            max_escape=max(max_escape,escape)
            assert escape<1e-6,('Face crosses final owned paving domain',int(mid),escape)
            area[int(mid)]+=float(sh.area(faces).sum())
    return result,area,max_escape


def verify_revision(root,city,scene):
    rev=city['geometryRevision'];parent=root.parent/rev['parent']
    assert digest(parent/'validation.json')==rev['parentValidationSha256']
    assert json.loads((parent/'validation.json').read_text())['passed']
    old=json.loads((parent/'canonical/full/scene.json').read_text())
    patch=json.loads((root/'pedestrian-material-patch.json').read_text())
    assert scene['materials']==old['materials']+materials(old['materials'][0]['color'])
    assert old['instances']==scene['instances']
    assert len(old['chunks'])==len(scene['chunks'])
    for name,meta in old['textures'].items():
        assert scene['textures'][name]==meta
        assert digest(parent/'textures'/name)==digest(root/'textures'/name)
    for name,meta in scene['textures'].items():
        assert digest(root/'textures'/name)==meta['sha256']
    changes={}
    for key,groups in patch['canonicalFaces'].items():
        idx=int(key);labels=np.full(old['chunks'][idx]['triangles'],-1,dtype=np.int32)
        for mid,faces in groups.items():labels[faces]=int(mid)
        changes[idx]=labels
    def check(before,after,a,b,targets,canonical):
        ib=a['triangles']*12 if canonical else a['indexBytes']
        expected,vb,_=remap_many(before,a['vertexBytes'],ib,targets)
        assert expected==after and vb==b['vertexBytes']
        allowed={'vertexBytes','vertexCount'}|({'file','sha256','downloadBytes'} if not canonical else set())
        assert {k:v for k,v in a.items() if k not in allowed}=={k:v for k,v in b.items() if k not in allowed}
    for a,b in zip(old['chunks'],scene['chunks']):
        if a['id'] not in changes:
            assert a==b and digest(parent/'canonical/full'/Path(a['file']).name)==digest(root/'canonical/full'/Path(b['file']).name)
        else:check(raw(parent,a,True),raw(root,b,True),a,b,changes[a['id']],True)
    old_tiles=json.loads((parent/'tileset.json').read_text());tiles=json.loads((root/'tileset.json').read_text())
    assert old_tiles['tiles']==tiles['tiles'] and old_tiles['sourceChunks']==tiles['sourceChunks']
    assert scene['materials']==tiles['materials'] and scene['textures']==tiles['textures']
    assert len(old_tiles['chunks'])==len(tiles['chunks'])
    touched=[];counts=Counter()
    for a,b in zip(old_tiles['chunks'],tiles['chunks']):
        if a==b:
            assert digest(parent/a['file'])==digest(root/b['file']);continue
        assert a['name']=='land' and a['sourceChunk'] in changes
        before=raw(parent,a);lineage=np.frombuffer(before[-a['lineageBytes']:],'<u4')
        targets=changes[a['sourceChunk']][lineage];assert np.any(targets>=0)
        after=raw(root,b)
        assert hashlib.sha256(after).hexdigest()==b['sha256']
        assert (root/b['file']).stat().st_size==b['downloadBytes']
        check(before,after,a,b,targets,False)
        touched.append(a['tileId']);counts.update(map(int,targets[targets>=0]))
    return dict(passed=True,type='pedestrian-materials',changedTiles=len(set(touched)),changedTileChunks=len(touched),
                recoloredTriangles=sum(counts.values()),trianglesByMaterial=dict(counts),geometryCornersBitIdentical=True,
                bvhAndLineageBitIdentical=True,allOtherMeshesBitIdentical=True,paintContainmentPassed=True,
                existingMaterialsUnchanged=True,inheritedParent=parent.name,policy=POLICY)


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--skip-glb",action="store_true",help="Defer optional canonical GLB; final merged export is built separately")
    for key in ('base','output','selection'):ap.add_argument('--'+key,type=Path,required=True)
    a=ap.parse_args();assert not a.output.exists() and a.base.parent==a.output.parent
    parent_validation=json.loads((a.base/'validation.json').read_text());assert parent_validation['passed']
    selected=select(a.base,a.selection);rows=selected['surfaces'];assert rows
    scene=json.loads((a.base/'canonical/full/scene.json').read_text());tiles=json.loads((a.base/'tileset.json').read_text())
    report=json.loads((a.base/'canonical/validation.json').read_text())
    first=len(scene['materials']);new=materials(scene['materials'][0]['color'])
    scene['materials']+=new;tiles['materials']=scene['materials']
    by_layer={layer:first+TYPES.index(rule['kind']) for layer,rule in RULES.items()}
    owner_materials={f['id']:by_layer[f['layer']] for f in selected['features']}
    owner_layers={f['id']:f['layer'] for f in selected['features']}
    rev=dict(type='pedestrian-materials',version=1,parent=a.base.name,parentValidationSha256=digest(a.base/'validation.json'),
             previousRevision=report['geometryRevision'],policy=POLICY)
    patch=dict(features=[],surfaces=[],geometryRevision=rev,canonicalFaces={},materialsByLayer=by_layer)
    for f in selected['features']:
        semantic=classify(f['layer'],f['properties'],'polygon');semantic['material']=by_layer[f['layer']]
        patch['features'].append(dict(id=f['id'],semantics=semantic))
    expected=Counter()
    for s in rows:
        layer=owner_layers[s['owner']];rule=RULES[layer];mid=by_layer[layer]
        patch['surfaces'].append(dict(id=s['id'],material=mid,surfaceType=rule['kind'],styleId=rule['styleId']))
        expected[mid]+=sh.geometry.shape(s['geometry']).area
    subprocess.run(['/bin/cp','-cR',str(a.base),str(a.output)],check=True)
    (a.output/'validation.json').unlink()
    folder=a.output/'canonical/full';textures=make_textures(folder)
    for name in textures:shutil.copy2(folder/name,a.output/'textures'/name)
    scene['textures'].update(textures);tiles['textures']=scene['textures']
    labels={};area=Counter();escape=0.
    for c in scene['chunks']:
        if c['name']!='land':continue
        data=raw(a.base,c,True);u=np.frombuffer(data[:c['vertexBytes']],'<u4').reshape(-1,8)
        if not np.isin(u[:,6]&0x7fffffff,list({s['material'] for s in rows})).any():continue
        flags,cover,escaped=choose_faces(data,c,np.asarray(scene['origin']),rows,owner_materials)
        if not np.any(flags>=0):continue
        labels[c['id']]=flags;area.update(cover);escape=max(escape,escaped)
        patch['canonicalFaces'][str(c['id'])]={str(mid):np.flatnonzero(flags==mid).tolist() for mid in np.unique(flags[flags>=0])}
        updated,vb,_=remap_many(data,c['vertexBytes'],c['triangles']*12,flags)
        (folder/Path(c['file']).name).write_bytes(gzip.compress(updated,compresslevel=6,mtime=0))
        c.update(vertexBytes=vb,vertexCount=vb//32)
        print('RECOLORED CANONICAL',c['id'],int((flags>=0).sum()),dict(cover),flush=True)
    for mid,value in expected.items():assert abs(area[mid]-value)<max(.03,value*1e-6),(mid,area[mid],value)
    for c in tiles['chunks']:
        if c['sourceChunk'] not in labels:continue
        data=raw(a.base,c);lineage=np.frombuffer(data[-c['lineageBytes']:],'<u4');flags=labels[c['sourceChunk']][lineage]
        if not np.any(flags>=0):continue
        updated,vb,_=remap_many(data,c['vertexBytes'],c['indexBytes'],flags)
        signature=hashlib.sha256(updated).hexdigest();filename=f'meshes/{signature}.bin.gz'
        encoded=gzip.compress(updated,compresslevel=6,mtime=0);(a.output/filename).write_bytes(encoded)
        c.update(vertexBytes=vb,vertexCount=vb//32,file=filename,sha256=signature,downloadBytes=len(encoded))
    files={c['file'] for c in tiles['chunks']}
    for p in (a.output/'meshes').iterdir():
        if 'meshes/'+p.name not in files:p.unlink()
    for key,ids in [('fullDownloadBytes',{c for t in tiles['tiles'] for c in t['chunks']}),('coarseDownloadBytes',{c for t in tiles['tiles'] for c in t['coarseChunks']})]:
        ids|={i['mesh'] for t in tiles['tiles'] for i in t['instances']}
        tiles['stats'][key]=sum(c['downloadBytes'] for c in tiles['chunks'] if c['id'] in ids)
    # Review locations are selected from final owned polygons, not invented paths.
    for kind in TYPES:
        mid=first+TYPES.index(kind);candidates=[s for s in rows if owner_materials[s['owner']]==mid]
        largest=max(candidates,key=lambda s:sh.geometry.shape(s['geometry']).area)
        poly=sh.geometry.shape(largest['geometry']);p=poly.representative_point();o=scene['origin']
        z=float(np.dot(largest['heightPlane'],[p.x,p.y,1]))
        tiles.setdefault('witnessViews',{})['paving-'+kind]=dict(yaw=-.4,pitch=.95,distance=100,target=[p.x-o[0],z-o[2],o[1]-p.y])
    save(folder/'scene.json',scene);save(a.output/'tileset.json',tiles);save(a.output/'pedestrian-material-patch.json',patch)
    print('VERIFYING GEOMETRY IDENTITY',flush=True)
    proof=verify_revision(a.output,{'geometryRevision':rev},scene)
    proof.update(sourceFeatures=len(selected['features']),surfaceCells=len(rows),areaM2ByMaterial=dict(area),
                 expectedAreaM2ByMaterial=dict(expected),maxEscapedTriangleAreaM2=escape,
                 textureBytes=sum(v['bytes'] for v in textures.values()))
    save(a.output/'pedestrian-material-proof.json',proof)
    script=Path(__file__).with_name('restyle_registry.mjs')
    for name in ('canonical/urban-model.json.gz','objects.json.gz'):
        subprocess.run([os.environ.get('NODE','node'),str(script),str(a.base/name),str(a.output/name),str(a.output/'pedestrian-material-patch.json')],check=True)
    if not a.skip_glb:
        print('UPDATING GLB EXPORT',flush=True);export_glb(scene,folder)
    else:
        (folder/'model.glb').unlink(missing_ok=True)
    report['geometryRevision']=rev;report['pedestrianMaterials']=proof
    report['export']['glbBytes']=((folder/'model.glb').stat().st_size if (folder/'model.glb').exists() else 0)
    report['export']['downloadBytes']=sum((folder/Path(c['file']).name).stat().st_size for c in scene['chunks'])
    save(a.output/'canonical/validation.json',report)
    parent_validation['geometryRevision']=proof;parent_validation['pedestrianMaterials']=proof
    save(a.output/'validation.json',parent_validation)
    print('PEDESTRIAN MATERIALS PASSED',json.dumps(proof),flush=True)

if __name__=='__main__':main()
