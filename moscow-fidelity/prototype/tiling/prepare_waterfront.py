"""Incremental connected-water revision; all unaffected assets stay identical."""
import argparse,gzip,hashlib,json,os,subprocess,shutil
from pathlib import Path
import ijson
import numpy as np
import shapely as sh
from waterfront import install,DEPTH,MATERIAL,TEXTURE
from flat_roofs import read_faces
from prepare_cemetery_cover import save,digest,raw
from object_geometry import export_glb
from bvh_validation import validate as validate_bvh

def rows(path,key):
    if not path.exists() and path.suffix=='.gz':path=path.with_suffix('')
    opener=gzip.open if path.suffix=='.gz' else open
    with opener(path,'rb') as stream:yield from ijson.items(stream,key+'.item',use_float=True)

def verify_bridge_geometry(root,scene,patch):
    added=patch.get('newSurfaces',[])
    if not added:return {}
    folder=root/'canonical/full'
    cells=sh.from_geojson([json.dumps(r['geometry']) for r in added]);planes=np.asarray([r['heightPlane'] for r in added])
    fill=sh.from_wkb((folder/'water-bridge-continuation.wkb').read_bytes())
    assert abs(sh.area(cells).sum()-fill.area)<max(.1,fill.area*1e-6)
    c=next(c for c in scene['chunks'] if c['name']=='water-bridge-continuation')
    faces=read_faces(folder,c);v=faces.view('<f4')[:,:,:3].astype(float);ox,oy,oz=scene['origin']
    xy=np.stack([v[:,:,0]+ox,oy-v[:,:,2]],axis=2);footprints=sh.polygons(xy)
    area_error=float(abs(sh.area(footprints).sum()-fill.area));assert area_error<max(.5,fill.area*1e-5)
    idx=sh.STRtree(cells).nearest(sh.points(xy.mean(1)))
    expected=np.einsum('nki,ni->nk',xy,planes[idx,:2])+planes[idx,2,None]-oz
    height_error=float(abs(expected-v[:,:,1]).max());assert height_error<.001
    assert ((faces[:,:,6]&0x7fffffff)==added[0]['material']).all()
    assert sh.covered_by(sh.points(xy.mean(1)),fill.buffer(.001)).all()
    return dict(bridgeWaterCoveragePassed=True,bridgeWaterHeightErrorM=height_error,bridgeWaterAreaErrorM2=area_error)

def verify_revision(root,city,scene):
    rev=city['geometryRevision'];parent=root.parent/rev['parent'];patch=json.loads((root/'waterfront-patch.json').read_text())
    assert digest(parent/'validation.json')==rev['parentValidationSha256']
    old=json.loads((parent/'canonical/full/scene.json').read_text());changed=set(patch['changedChunks'])
    assert scene['materials']==old['materials']+[MATERIAL]
    extra=len(scene['chunks'])-len(old['chunks']);assert extra in (1,2)
    assert scene['instances'][:-extra]==old['instances']
    assert digest(parent/'canonical/terrain.npz')==digest(root/'canonical/terrain.npz')
    network=sh.from_wkb((root/'canonical/full/water-network.wkb').read_bytes())
    sh.prepare(network)
    assert sh.from_wkb((root/'canonical/full/water-bank-domain.wkb').read_bytes()).is_valid
    canonical={};areas={};errors={};preserved=lowered=0
    for c in scene['chunks']:
        if c['id'] not in changed:
            assert c==old['chunks'][c['id']]
            assert digest(parent/'canonical/full'/Path(c['file']).name)==digest(root/'canonical/full'/Path(c['file']).name)
            continue
        f=read_faces(root/'canonical/full',c);p=f.view('<f4')[:,:,:3].astype(float)
        canonical[c['id']]=(p,f);areas[c['id']]=np.zeros(len(f));errors[c['id']]=np.zeros(len(f))
        if c['id']>=len(old['chunks']):continue
        before=read_faces(parent/'canonical/full',old['chunks'][c['id']]);q=before.view('<f4')[:,:,:3].astype(float)
        assert np.array_equal(f[:,:,[0,2,3,4,5,6,7]],before[:,:,[0,2,3,4,5,6,7]])
        d=q[:,:,1]-p[:,:,1];is_lowered=np.isclose(d,DEPTH,atol=2e-6).all(1);unchanged=(d==0).all(1)
        assert (is_lowered|unchanged).all()
        center=q.mean(1);selected=sh.covers(network,sh.points(np.column_stack([center[:,0]+scene['origin'][0],scene['origin'][1]-center[:,2]])))
        assert np.array_equal(selected,is_lowered)
        lowered+=int(is_lowered.sum());preserved+=int(unchanged.sum())
    banks=np.load(root/'canonical/full/water-bank-segments.npz');a=banks['a'];b=banks['b'];bounds=patch['boundsMSK']
    for axis,edge in [(0,bounds[0]),(0,bounds[2]),(1,bounds[1]),(1,bounds[3])]:
        assert not ((abs(a[:,axis]-edge)<2e-5)&(abs(b[:,axis]-edge)<2e-5)).any()
    fill=sh.from_wkb((root/'canonical/full/water-bridge-continuation.wkb').read_bytes())
    spans=sh.from_wkb((root/'canonical/full/water-bridge-spans.wkb').read_bytes())
    domain=sh.from_wkb((root/'canonical/full/water-bank-domain.wkb').read_bytes())
    assert fill.difference(spans.buffer(2e-5)).area<1e-6 and fill.difference(domain.buffer(2e-5)).area<1e-6
    # Interior bridge cross-sections may not become vertical granite barriers.
    assert not sh.contains(spans.buffer(-.01),sh.points((a+b)/2)).any()
    assert np.allclose(np.diff(banks['chainage'],axis=1).ravel(),np.linalg.norm(b-a,axis=1))
    for name in old['textures']:assert digest(parent/'textures'/name)==digest(root/'textures'/name)
    old_tiles=json.loads((parent/'tileset.json').read_text());tiles=json.loads((root/'tileset.json').read_text());before={c['id']:c for c in old_tiles['chunks']}
    untouched=0;touched=set();max_dist=0.;max_uv_error=0.
    for c in tiles['chunks']:
        if c['sourceChunk'] not in changed:
            assert c==before[c['id']] and digest(parent/c['file'])==digest(root/c['file']);untouched+=1;continue
        data=raw(root,c);assert hashlib.sha256(data).hexdigest()==c['sha256']
        vb,ib,nb=c['vertexBytes'],c['indexBytes'],c['nodeBytes']
        w=np.frombuffer(data[:vb],'<u4').reshape(-1,8);ix=np.frombuffer(data[vb:vb+ib],'<u4').reshape(-1,3)
        p=w.view('<f4')[ix,:3].astype(float);lineage=np.frombuffer(data[vb+ib+nb:],'<u4')
        nodes=np.frombuffer(data[vb+ib:vb+ib+nb],'<f4').reshape(-1,8);validate_bvh(p,nodes,nodes.view('<u4'))
        source,attributes=canonical[c['sourceChunk']];q=source[lineage]
        assert np.array_equal(w[ix[:,0],6],attributes[lineage,0,6])
        v=q[:,1]-q[:,0];u=q[:,2]-q[:,0];n=np.cross(v,u);length=np.linalg.norm(n,axis=1)
        distance=abs(np.einsum('nki,ni->nk',p-q[:,0,None,:],n))/np.maximum(length[:,None],1e-20)
        max_dist=max(max_dist,float(distance.max(initial=0)));assert max_dist<.001
        epsilon=.5*np.linalg.norm(np.spacing(abs(p).astype('<f4').max(1)).astype(float),axis=1)
        perimeter=np.linalg.norm(p-np.roll(p,1,axis=1),axis=2).sum(1)
        np.add.at(errors[c['sourceChunk']],lineage,perimeter*epsilon+3*epsilon**2)
        area=np.linalg.norm(np.cross(p[:,1]-p[:,0],p[:,2]-p[:,0]),axis=1)/2
        np.add.at(areas[c['sourceChunk']],lineage,area);touched.add(c['tileId'])
        if c['name']=='waterfront-bank':
            # For every clipped bank vertex verify the original affine UV field.
            vv=(v*v).sum(1);uu=(u*u).sum(1);vu=(v*u).sum(1);det=vv*uu-vu**2
            dp=p-q[:,0,None,:];pv=np.einsum('nki,ni->nk',dp,v);pu=np.einsum('nki,ni->nk',dp,u)
            s=(pv*uu[:,None]-pu*vu[:,None])/det[:,None];t=(pu*vv[:,None]-pv*vu[:,None])/det[:,None]
            uv=attributes.view('<f4')[lineage,:,4:6].astype(float)
            expected=uv[:,0,None,:]+s[:,:,None]*(uv[:,1]-uv[:,0])[:,None,:]+t[:,:,None]*(uv[:,2]-uv[:,0])[:,None,:]
            observed=w.view('<f4')[ix,4:6];valid=np.linalg.norm(v,axis=1)>.01
            max_uv_error=max(max_uv_error,float(abs(expected-observed)[valid].max(initial=0)))
    for idx,(p,_) in canonical.items():
        area=np.linalg.norm(np.cross(p[:,1]-p[:,0],p[:,2]-p[:,0]),axis=1)/2
        assert np.all(abs(area-areas[idx])<errors[idx]*1.02+1e-6),(idx,float(abs(area-areas[idx]).max()))
    assert max_uv_error<.02
    for a,b in zip(old_tiles['tiles'],tiles['tiles']):assert a['instances']==b['instances'] and a['boundsMSK']==b['boundsMSK']
    assert tiles['objectLayer']['pitchedRoofs']==old_tiles['objectLayer']['pitchedRoofs']
    bridge_proof=verify_bridge_geometry(root,scene,patch)
    return dict(passed=True,**bridge_proof,type='connected-waterfront',changedTiles=len(touched),preservedTileChunks=untouched,loweredWaterTriangles=lowered,preservedWaterTriangles=preserved,terrainAndUnrelatedGeometryBitIdentical=True,bankAreaConservationPassed=True,packedBVHPassed=True,noWallsOnAcquisitionCut=True,continuousBankUVPassed=True,maxPackedPlaneDistanceM=max_dist,maxPackedUVError=max_uv_error,**{k:v for k,v in scene['waterfront']['stats'].items() if k not in {'loweredWaterTriangles','preservedWaterTriangles'}})

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--skip-glb",action="store_true",help="Defer optional canonical GLB; final merged export is built separately")
    for k in ('base','output'):ap.add_argument('--'+k,type=Path,required=True)
    ap.add_argument('--water-input',type=Path);ap.add_argument('--source-input',type=Path);ap.add_argument('--resume',action='store_true')
    ap.add_argument('--node',default=os.environ.get('NODE',shutil.which('node')))
    args=ap.parse_args();base=args.base;root=args.output;here=Path(__file__).parent;node=args.node
    if not node:ap.error('Node.js is required')
    parent=json.loads((base/'validation.json').read_text());assert parent['passed']
    if not root.exists():
        subprocess.run(['/bin/cp','-cR',str(base),str(root)],check=True);(root/'validation.json').unlink()
    else:assert args.resume
    folder=root/'canonical/full';patchfile=root/'waterfront-patch.json'
    if not patchfile.exists():
        # Resume an interrupted build from the immutable parent water meshes;
        # a failure before the patch was saved may already have lowered them.
        scene=json.loads((base/'canonical/full/scene.json').read_text());metadata=json.loads((base/'canonical/transport-metadata.json').read_text());report=json.loads((base/'canonical/validation.json').read_text())
        for c in scene['chunks']:
            if c.get('category',c['name'])=='water':shutil.copyfile(base/'canonical/full'/Path(c['file']).name,folder/Path(c['file']).name)
        features=json.loads(args.source_input.read_text()) if args.source_input else [r for r in rows(base/'canonical/urban-model.json.gz','features') if r.get('layer') in {'Water_area','Water_line','Bridge_area','Pier_quarter'}]
        water=json.loads(args.water_input.read_text()) if args.water_input else [r for r in rows(base/'objects.json.gz','surfaces') if r.get('kind')=='water']
        save(root/'waterfront-source-input.json',features);save(root/'waterfront-water-input.json',water)
        bank_key=digest(base/'validation.json')+digest(base/'objects.json.gz')+digest(base/'canonical/terrain.npz')
        result=install(features,water,rows(base/'objects.json.gz','surfaces'),scene,folder,metadata['boundsMSK'],bank_cache_key=bank_key)
        if result is None:
            save(root/'validation.json',parent);print('NO BOUNDARY-CONNECTED WATER; unchanged validated scene',flush=True);return
        rev=dict(type='connected-waterfront',version=2,parent=base.name,parentValidationSha256=digest(base/'validation.json'),previousRevision=report['geometryRevision'],policy=scene['waterfront']['policy'])
        sources=[{k:c[k] for k in ('id','name','triangles','instanced','sourceObjectIds') if k in c} for c in scene['chunks']]
        patch=dict(features=[],**result,sourceChunks=sources,geometryRevision=rev,boundsMSK=metadata['boundsMSK'])
        # Use this region's shoreline, without inheriting another city's camera.
        bank=np.load(folder/'water-bank-segments.npz');a=bank['a'];b=bank['b'];mid=(a+b)/2
        distance=np.linalg.norm(mid-np.asarray(scene['origin'][:2]),axis=1);distance[np.linalg.norm(b-a,axis=1)<1]=np.inf;i=int(distance.argmin())
        tangent=b[i]-a[i];outward=np.array([tangent[1],-tangent[0]])/np.linalg.norm(tangent)
        # View from water towards the bank; controls use Y up and Z south.
        waterward=-outward;view=np.array([waterward[0],-waterward[1]])
        patch['witnessViews']={'waterfront-review':dict(yaw=float(np.arctan2(view[0],view[1])),pitch=.35,distance=28.,target=[float(mid[i,0]-scene['origin'][0]),float(bank['base'][i].mean()-1-scene['origin'][2]),float(scene['origin'][1]-mid[i,1])])}
        bridge=next((c for c in scene['chunks'] if c['name']=='water-bridge-continuation'),None)
        if bridge:
            lo=np.asarray(bridge['bounds']['min']);hi=np.asarray(bridge['bounds']['max'])
            patch['witnessViews']['waterfront-bridge-review']=dict(yaw=-.7,pitch=.48,distance=float(max(85.,np.linalg.norm((hi-lo)[[0,2]])*.65)),target=((lo+hi)/2).tolist())
        save(folder/'scene.json',scene);save(patchfile,patch)
        report['geometryRevision']=rev;report['waterfront']=dict(passed=True,**result['waterfront']['stats']);report['export'].update(triangles=scene['stats']['uniqueTriangles'],expandedTriangles=scene['stats']['expandedTriangles'])
        save(root/'canonical/validation.json',report)
        (root/'textures'/TEXTURE).write_bytes((folder/TEXTURE).read_bytes())
        print('WATERFRONT BUILT',json.dumps(scene['waterfront']['stats']),flush=True)
    patch=json.loads(patchfile.read_text());rev=patch['geometryRevision'];scene=json.loads((folder/'scene.json').read_text());report=json.loads((root/'canonical/validation.json').read_text())
    assert rev['parent']==base.name and rev['parentValidationSha256']==digest(base/'validation.json')
    current=json.loads((root/'tileset.json').read_text())
    if current.get('geometryRevision',{}).get('type')!='connected-waterfront':subprocess.run([node,str(here/'pack_tiles.mjs'),str(root),str(patchfile)],check=True)
    print('VERIFYING WATERFRONT',flush=True);proof=verify_revision(root,{'geometryRevision':rev},scene);save(root/'waterfront-proof.json',proof)
    for name in ('canonical/urban-model.json.gz','objects.json.gz'):
        source=base/name
        if not source.exists():source=source.with_suffix('')
        subprocess.run([node,str(here/'restyle_registry.mjs'),str(source),str(root/name),str(patchfile)],check=True)
    plain=root/'canonical/urban-model.json'
    if plain.exists():plain.unlink()
    if not args.skip_glb:
        print('EXPORTING WATERFRONT GLB',flush=True);export_glb(scene,folder)
    else:
        (folder/'model.glb').unlink(missing_ok=True)
    report['export'].update(triangles=scene['stats']['uniqueTriangles'],expandedTriangles=scene['stats']['expandedTriangles'])
    report['waterfront']=proof;report['export']['glbBytes']=((folder/'model.glb').stat().st_size if (folder/'model.glb').exists() else 0)
    report['export']['downloadBytes']=sum((folder/Path(c['file']).name).stat().st_size for c in scene['chunks']);save(root/'canonical/validation.json',report)
    tiles=json.loads((root/'tileset.json').read_text());parent['geometryRevision']=rev;parent['waterfront']=proof
    parent['inheritedArea']=parent.pop('area',parent.get('inheritedArea',{}));parent.update(meshes=len(tiles['chunks']),triangles=tiles['stats']['fullTriangles'],bvhNodes=sum(c['nodeCount'] for c in tiles['chunks']))
    save(root/'validation.json',parent);print('WATERFRONT PASSED',json.dumps(proof),flush=True)

if __name__=='__main__':main()
