"""Incremental land-use appearance revision; never rebuild the city geometry."""
import argparse,gzip,hashlib,json,os,subprocess,sys
from pathlib import Path
import ijson
import numpy as np
import shapely as sh
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from cemetery_cover import LAYER,POLICY,material,owns_surface
from semantics import classify
from material_remap import remap
from object_geometry import export_glb

def save(path,value):path.write_text(json.dumps(value,ensure_ascii=False,separators=(',',':')))
def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        while block:=f.read(8*1024*1024):h.update(block)
    return h.hexdigest()

def select(base,cache):
    signature=digest(base/'objects.json.gz')
    if cache.exists():
        result=json.loads(cache.read_text())
        if result.get('baseRegistrySha256')==signature:return result
    with gzip.open(base/'objects.json.gz','rb') as f:
        features=[r for r in ijson.items(f,'features.item',use_float=True) if r['layer']==LAYER]
    owners={r['id'] for r in features}
    with gzip.open(base/'objects.json.gz','rb') as f:
        surfaces=[s for s in ijson.items(f,'surfaces.item',use_float=True) if owns_surface(s,owners)]
    result=dict(baseRegistrySha256=signature,features=features,surfaces=surfaces)
    save(cache,result);return result

def raw(root,c,canonical=False):
    path=root/'canonical/full'/Path(c['file']).name if canonical else root/c['file']
    return gzip.decompress(path.read_bytes())

def choose_faces(data,c,origin,rows):
    u=np.frombuffer(data[:c['vertexBytes']],'<u4').reshape(-1,8)
    ix=np.frombuffer(data[c['vertexBytes']:],'<u4').reshape(-1,3)
    result=np.zeros(len(ix),bool)
    polys=[sh.geometry.shape(s['geometry']) for s in rows];tree=sh.STRtree(polys)
    planes=np.array([s['heightPlane'] for s in rows]);old_materials=np.array([s['material'] for s in rows])
    selected_area=0.;max_escape=0.
    for start in range(0,len(ix),32768):
        indices=ix[start:start+32768]
        xyz=u.view('<f4')[indices,:3].astype(float)[:,:,[0,2,1]]*[1,-1,1]+origin
        center=xyz.mean(1)
        hits=tree.query(sh.points(center[:,:2]),predicate='covered_by')
        if not hits.size:continue
        a,b=hits
        ok=(abs(np.sum(planes[b,:2]*center[a,:2],axis=1)+planes[b,2]-center[a,2])<.001)&((u[indices[a,0],6]&0x7fffffff)==old_materials[b])
        chosen=np.unique(a[ok]);result[start+chosen]=True
        if not len(chosen):continue
        # Check whole triangles, not just their centres, against final owned
        # cells. A 0.5 mm envelope covers a single local Float32 rounding.
        face_polys=sh.polygons(xyz[chosen,:,:2]);near=np.unique(b[ok])
        domain=sh.union_all([polys[i] for i in near]).buffer(.0005)
        # Most selected faces lie entirely inside the owned domain. A prepared
        # predicate avoids repeating a large polygon overlay for every face;
        # retain the exact area check for any face that might escape.
        sh.prepare(domain)
        outside=~sh.covers(domain,face_polys)
        escape=sh.area(sh.difference(face_polys[outside],domain))
        max_escape=max(max_escape,float(escape.max(initial=0)))
        assert max_escape<1e-6,('Face crosses outside selected source surfaces',max_escape)
        selected_area+=float(sh.area(face_polys).sum())
    return result,selected_area,max_escape

def assert_appearance_only(before,after,a,b,selected,mid,canonical):
    vb=a['vertexBytes'];ib=a['triangles']*12 if canonical else a['indexBytes']
    expected,new_vb,_=remap(before,vb,ib,selected,mid)
    assert expected==after and new_vb==b['vertexBytes']
    allowed={'vertexBytes','vertexCount'}|({'file','sha256','downloadBytes'} if not canonical else set())
    assert {k:v for k,v in a.items() if k not in allowed}=={k:v for k,v in b.items() if k not in allowed}

def verify_revision(root,city,scene):
    rev=city['geometryRevision'];parent=root.parent/rev['parent']
    assert digest(parent/'validation.json')==rev['parentValidationSha256']
    parent_validation=json.loads((parent/'validation.json').read_text());assert parent_validation['passed']
    old=json.loads((parent/'canonical/full/scene.json').read_text())
    patch=json.loads((root/'cemetery-material-patch.json').read_text());mid=patch['material']
    assert scene['materials']==old['materials']+[material()]
    assert scene['instances']==old['instances'] and len(scene['chunks'])==len(old['chunks'])
    changes={int(k):np.asarray(v,dtype=int) for k,v in patch['canonicalFaces'].items()}
    for a,b in zip(old['chunks'],scene['chunks']):
        if a['id'] not in changes:
            assert a==b and digest(parent/'canonical/full'/Path(a['file']).name)==digest(root/'canonical/full'/Path(b['file']).name)
            continue
        selected=np.zeros(a['triangles'],bool);selected[changes[a['id']]]=True
        assert_appearance_only(raw(parent,a,True),raw(root,b,True),a,b,selected,mid,True)
    old_tiles=json.loads((parent/'tileset.json').read_text());tiles=json.loads((root/'tileset.json').read_text())
    assert tiles['tiles']==old_tiles['tiles'] and tiles['materials']==scene['materials']
    touched=[];faces=0
    for a,b in zip(old_tiles['chunks'],tiles['chunks']):
        if a==b:
            assert digest(parent/a['file'])==digest(root/b['file']);continue
        assert a['sourceChunk'] in changes and a['name']=='land'
        data=raw(parent,a);lineage=np.frombuffer(data[-a['lineageBytes']:],'<u4')
        selected=np.isin(lineage,changes[a['sourceChunk']])
        assert selected.any();after=raw(root,b)
        assert hashlib.sha256(after).hexdigest()==b['sha256']
        assert (root/b['file']).stat().st_size==b['downloadBytes']
        assert_appearance_only(data,after,a,b,selected,mid,False)
        touched.append(a['tileId']);faces+=int(selected.sum())
    return dict(passed=True,type='cemetery-cover',changedTiles=len(set(touched)),changedTileChunks=len(touched),
                recoloredTriangles=faces,geometryCornersBitIdentical=True,bvhAndLineageBitIdentical=True,
                allOtherAssetsBitIdentical=True,paintContainmentPassed=True,
                inheritedParent=parent.name,policy=POLICY)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--skip-glb",action="store_true",help="Defer optional canonical GLB; final merged export is built separately")
    for key in ('base','output','selection'):ap.add_argument('--'+key,type=Path,required=True)
    ap.add_argument('--camera',type=Path)
    a=ap.parse_args();assert not a.output.exists() and a.base.parent==a.output.parent
    parent_validation=json.loads((a.base/'validation.json').read_text());assert parent_validation['passed']
    selected=select(a.base,a.selection);rows=selected['surfaces'];assert rows
    scene=json.loads((a.base/'canonical/full/scene.json').read_text())
    tiles=json.loads((a.base/'tileset.json').read_text())
    report=json.loads((a.base/'canonical/validation.json').read_text())
    mid=len(scene['materials']);scene['materials'].append(material());tiles['materials']=scene['materials']
    rev=dict(type='cemetery-cover',version=1,parent=a.base.name,parentValidationSha256=digest(a.base/'validation.json'),
             previousRevision=report['geometryRevision'],policy=POLICY)
    patch=dict(material=mid,features=[],surfaceIds=[s['id'] for s in rows],geometryRevision=rev,canonicalFaces={})
    for f in selected['features']:
        semantics=classify(f['layer'],f['properties'],'polygon');semantics['material']=mid
        patch['features'].append(dict(id=f['id'],semantics=semantics))
    subprocess.run(['/bin/cp','-cR',str(a.base),str(a.output)],check=True)
    # A draft must not inherit the parent's final-release approval marker.
    (a.output/'validation.json').unlink()
    area=0.;escapes=0.
    for c in scene['chunks']:
        if c['name']!='land':continue
        data=raw(a.base,c,True)
        u=np.frombuffer(data[:c['vertexBytes']],'<u4').reshape(-1,8)
        if not np.isin(u[:,6]&0x7fffffff,[s['material'] for s in rows]).any():continue
        flags,cover,escape=choose_faces(data,c,np.asarray(scene['origin']),rows)
        if not flags.any():continue
        area+=cover;escapes=max(escapes,escape)
        patch['canonicalFaces'][str(c['id'])]=np.flatnonzero(flags).tolist()
        updated,vb,_=remap(data,c['vertexBytes'],c['triangles']*12,flags,mid)
        target=a.output/'canonical/full'/Path(c['file']).name;target.write_bytes(gzip.compress(updated,compresslevel=6,mtime=0))
        c.update(vertexBytes=vb,vertexCount=vb//32)
        print('RECOLORED CANONICAL',c['id'],int(flags.sum()),flush=True)
    expected_area=sum(sh.geometry.shape(s['geometry']).area for s in rows)
    assert abs(area-expected_area)<max(.02,expected_area*1e-6),(area,expected_area)
    for c in tiles['chunks']:
        ids=patch['canonicalFaces'].get(str(c['sourceChunk']))
        if ids is None:continue
        data=raw(a.base,c);lineage=np.frombuffer(data[-c['lineageBytes']:],'<u4');flags=np.isin(lineage,ids)
        if not flags.any():continue
        updated,vb,_=remap(data,c['vertexBytes'],c['indexBytes'],flags,mid)
        signature=hashlib.sha256(updated).hexdigest();file=f'meshes/{signature}.bin.gz'
        encoded=gzip.compress(updated,compresslevel=6,mtime=0);(a.output/file).write_bytes(encoded)
        c.update(vertexBytes=vb,vertexCount=vb//32,file=file,sha256=signature,downloadBytes=len(encoded))
    # Remove only copied, now-unreferenced packed payloads in the NEW release.
    files={c['file'] for c in tiles['chunks']}
    for p in (a.output/'meshes').iterdir():
        if 'meshes/'+p.name not in files:p.unlink()
    for key,ids in [('fullDownloadBytes',{c for t in tiles['tiles'] for c in t['chunks']}),
                    ('coarseDownloadBytes',{c for t in tiles['tiles'] for c in t['coarseChunks']})]:
        ids|={i['mesh'] for t in tiles['tiles'] for i in t['instances']}
        tiles['stats'][key]=sum(c['downloadBytes'] for c in tiles['chunks'] if c['id'] in ids)
    if a.camera:tiles.setdefault('witnessViews',{})['cemetery-review']=json.loads(a.camera.read_text())
    save(a.output/'canonical/full/scene.json',scene);save(a.output/'tileset.json',tiles)
    save(a.output/'cemetery-material-patch.json',patch)
    print('VERIFYING APPEARANCE ONLY',flush=True)
    proof=verify_revision(a.output,{'geometryRevision':rev},scene)
    proof.update(sourceFeatures=len(selected['features']),surfaceCells=len(rows),coveredAreaM2=area,
                 expectedAreaM2=expected_area,maxEscapedTriangleAreaM2=escapes)
    save(a.output/'cemetery-material-proof.json',proof)
    script=Path(__file__).with_name('restyle_registry.mjs')
    for name in ('canonical/urban-model.json.gz','objects.json.gz'):
        subprocess.run([os.environ.get('NODE','node'),str(script),str(a.base/name),str(a.output/name),str(a.output/'cemetery-material-patch.json')],check=True)
    if not a.skip_glb:
        print('UPDATING OPTIONAL GLB MATERIALS',flush=True);export_glb(scene,a.output/'canonical/full')
    else:
        (a.output/'canonical/full'/'model.glb').unlink(missing_ok=True)
    report['geometryRevision']=rev;report['cemeteryCover']=proof
    glb=a.output/'canonical/full/model.glb'
    report['export']['glbBytes']=glb.stat().st_size if glb.exists() else 0
    report['export']['downloadBytes']=sum((a.output/'canonical/full'/Path(c['file']).name).stat().st_size for c in scene['chunks'])
    save(a.output/'canonical/validation.json',report)
    parent_validation['geometryRevision']=proof;parent_validation['cemeteryCover']=proof
    save(a.output/'validation.json',parent_validation)
    print('CEMETERY APPEARANCE PASSED',json.dumps(proof),flush=True)

if __name__=='__main__':main()
