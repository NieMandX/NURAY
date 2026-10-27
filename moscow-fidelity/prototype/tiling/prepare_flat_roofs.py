"""Incremental roof-only revision; preserve unrelated canonical and tile meshes."""
import argparse,json,gzip,subprocess,os,hashlib,tempfile,copy
from pathlib import Path
from collections import defaultdict,Counter
import numpy as np
from flat_roofs import install,read_faces,MATERIAL,POLICY
from prepare_cemetery_cover import save,digest,raw
from object_geometry import export_glb
from bvh_validation import validate as validate_bvh

def verify_revision(root,city,scene):
    rev=city['geometryRevision'];parent=root.parent/rev['parent'];patch=json.loads((root/'flat-roof-patch.json').read_text())
    assert digest(parent/'validation.json')==rev['parentValidationSha256']
    old=json.loads((parent/'canonical/full/scene.json').read_text());changed=set(patch['changedChunks'])
    assert scene['materials']==old['materials']+[MATERIAL] and scene['textures']==old['textures'] and scene['instances']==old['instances']
    # Recreate the scoped transformation independently of serialized output;
    # fixture tests additionally prove metric offsets, holes, winding and walls.
    with tempfile.TemporaryDirectory() as temp:
        folder=Path(temp);expected=copy.deepcopy(old);rows=json.loads((root/'roof-input-buildings.json').read_text())
        for c in old['chunks']:
            if c.get('category')=='building':subprocess.run(['/bin/cp','-c',str(parent/'canonical/full'/Path(c['file']).name),str(folder/Path(c['file']).name)],check=True)
        result=install(rows,expected,folder,patch['boundsMSK']);assert result['changedChunks']==patch['changedChunks']
        for a,b in zip(expected['chunks'],scene['chunks']):
            assert a==b
            if a['id'] in changed:assert digest(folder/Path(a['file']).name)==digest(root/'canonical/full'/Path(b['file']).name)
            else:assert digest(parent/'canonical/full'/Path(a['file']).name)==digest(root/'canonical/full'/Path(b['file']).name)
    assert digest(parent/'canonical/terrain.npz')==digest(root/'canonical/terrain.npz')
    old_tiles=json.loads((parent/'tileset.json').read_text());tiles=json.loads((root/'tileset.json').read_text())
    before={c['id']:c for c in old_tiles['chunks']};untouched=0;tile_ids=set();canonical={};areas={};rounding_bounds={};max_distance=0;max_edge_escape=0
    assert tiles['materials']==scene['materials'] and tiles['textures']==scene['textures']
    for c in scene['chunks']:
        if c['id'] in changed:
            f=read_faces(root/'canonical/full',c);p=f.view('<f4')[:,:,:3].astype(float)
            canonical[c['id']]=(p,f[:,0,6]);areas[c['id']]=np.zeros(len(f));rounding_bounds[c['id']]=np.zeros(len(f))
    for c in tiles['chunks']:
        if c['sourceChunk'] not in changed:
            assert c==before[c['id']] and digest(parent/c['file'])==digest(root/c['file']);untouched+=1;continue
        data=raw(root,c);assert hashlib.sha256(data).hexdigest()==c['sha256']
        vb=c['vertexBytes'];ib=c['indexBytes'];nb=c['nodeBytes']
        words=np.frombuffer(data[:vb],'<u4').reshape(-1,8);ix=np.frombuffer(data[vb:vb+ib],'<u4').reshape(-1,3)
        p=words.view('<f4')[ix,:3].astype(float);lineage=np.frombuffer(data[vb+ib+nb:],'<u4')
        nf=np.frombuffer(data[vb+ib:vb+ib+nb],'<f4').reshape(-1,8);nu=nf.view('<u4');validate_bvh(p,nf,nu)
        source,mids=canonical[c['sourceChunk']];assert lineage.max()<len(source)
        assert np.array_equal(words[ix[:,0],6],mids[lineage])
        q=source[lineage];a=q[:,1]-q[:,0];b=q[:,2]-q[:,0];normal=np.cross(a,b);length=np.linalg.norm(normal,axis=1)
        distance=abs(np.einsum('nki,ni->nk',p-q[:,0,None,:],normal))/np.maximum(length[:,None],1e-20)
        max_distance=max(max_distance,float(distance.max(initial=0)));assert max_distance<.001
        for edge in range(3):
            v=q[:,(edge+1)%3]-q[:,edge];cross=np.cross(v[:,None,:],p-q[:,edge,None,:])
            signed=np.einsum('nki,ni->nk',cross,normal)/np.maximum((np.linalg.norm(v,axis=1)*length)[:,None],1e-20)
            max_edge_escape=max(max_edge_escape,float((-signed).max(initial=0)))
        assert max_edge_escape<.001
        # Float32 rounding at 5 km can move a cut vertex by 0.25 mm.
        # Long, 40 cm-wide rim triangles need a perimeter-based area bound,
        # not a fixed relative-area tolerance intended for broad roof faces.
        epsilon=.5*np.linalg.norm(np.spacing(abs(p).astype('<f4').max(1)).astype(float),axis=1)
        perimeter=np.linalg.norm(p-np.roll(p,1,axis=1),axis=2).sum(1)
        np.add.at(rounding_bounds[c['sourceChunk']],lineage,perimeter*epsilon+3*epsilon**2)
        area=np.linalg.norm(np.cross(p[:,1]-p[:,0],p[:,2]-p[:,0]),axis=1)/2
        np.add.at(areas[c['sourceChunk']],lineage,area);tile_ids.add(c['tileId'])
    max_area_error=0.
    for idx,(p,_) in canonical.items():
        area=np.linalg.norm(np.cross(p[:,1]-p[:,0],p[:,2]-p[:,0]),axis=1)/2
        error=abs(area-areas[idx]);max_area_error=max(max_area_error,float(error.max(initial=0)))
        assert np.all(error<rounding_bounds[idx]*1.01+1e-6),(idx,float(error.max()))
    for a,b in zip(old_tiles['tiles'],tiles['tiles']):
        assert a['instances']==b['instances'] and a['boundsMSK']==b['boundsMSK']
    return dict(passed=True,type='flat-roofs',changedTiles=len(tile_ids),changedCanonicalChunks=len(changed),
                preservedTileChunks=untouched,terrainAndUnrelatedGeometryBitIdentical=True,
                instancesAndTexturesUnchanged=True,packedAreaConservationPassed=True,packedBVHPassed=True,
                maxPackedPlaneDistanceM=max_distance,maxPackedEdgeEscapeM=max_edge_escape,areaTolerance="sum of clipped triangle perimeters times their Float32 rounding bound",maxPackedTriangleAreaErrorM2=max_area_error,**patch['roofStats'])

def refresh_validation_totals(root):
    patch=json.loads((root/'flat-roof-patch.json').read_text());parent=root.parent/patch['geometryRevision']['parent']
    scene=json.loads((root/'canonical/full/scene.json').read_text());old=json.loads((parent/'canonical/full/scene.json').read_text())
    tiles=json.loads((root/'tileset.json').read_text());report=json.loads((root/'validation.json').read_text())
    def area_of_faces(f):
        p=f.view('<f4')[:,:,:3].astype(float)
        return float(np.linalg.norm(np.cross(p[:,1]-p[:,0],p[:,2]-p[:,0]),axis=1).sum()/2)
    source_delta=sum(area_of_faces(read_faces(root/'canonical/full',scene['chunks'][i]))-area_of_faces(read_faces(parent/'canonical/full',old['chunks'][i])) for i in patch['changedChunks'])
    # The new scoped proof certifies packed area within explicit rounding
    # bounds; retain the old all-city area report as historical evidence only.
    report['inheritedArea']=report.pop('area',report.get('inheritedArea',{}))
    report['flatRoofs']['canonicalAreaDeltaM2']=source_delta
    report.update(meshes=len(tiles['chunks']),triangles=tiles['stats']['fullTriangles'],bvhNodes=sum(c['nodeCount'] for c in tiles['chunks']))
    report['objectLayer'].update(patch['objectLayerUpdate']['stats'])
    report['bvhProofCache']={'reused':report['flatRoofs']['preservedTileChunks'],'newlyChecked':len(tiles['chunks'])-report['flatRoofs']['preservedTileChunks'],'policy':'parent proof for identical meshes; every modified roof mesh BVH traversed'}
    save(root/'validation.json',report)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--skip-glb",action="store_true",help="Defer optional canonical GLB; final merged export is built separately")
    for k in ('base','output','buildings'):ap.add_argument('--'+k,type=Path,required=True)
    ap.add_argument('--review-camera',type=Path,help='Optional viewer camera JSON for the roof review witness')
    ap.add_argument('--resume',action='store_true')
    a=ap.parse_args();parent_validation=json.loads((a.base/'validation.json').read_text());assert parent_validation['passed']
    node=os.environ['NODE'];here=Path(__file__).parent
    if a.output.exists():
        assert a.resume,'Use --resume only for an existing incomplete revision'
        folder=a.output/'canonical/full';scene=json.loads((folder/'scene.json').read_text());report=json.loads((a.output/'canonical/validation.json').read_text())
        patch=json.loads((a.output/'flat-roof-patch.json').read_text());rev=patch['geometryRevision']
        assert rev['parent']==a.base.name and rev['parentValidationSha256']==digest(a.base/'validation.json')
    else:
        subprocess.run(['/bin/cp','-cR',str(a.base),str(a.output)],check=True);(a.output/'validation.json').unlink()
        folder=a.output/'canonical/full';scene=json.loads((folder/'scene.json').read_text());old=json.loads(json.dumps(scene))
        metadata=json.loads((a.output/'canonical/transport-metadata.json').read_text());report=json.loads((a.output/'canonical/validation.json').read_text())
        rows=json.loads(a.buildings.read_text());save(a.output/'roof-input-buildings.json',rows)
        result=install(rows,scene,folder,metadata['boundsMSK']);assert result['stats']['buildings']
        print('ROOFS BUILT',json.dumps(result['stats']),flush=True)
        delta=result['stats']['addedTriangles']-result['stats']['removedTriangles']
        rev=dict(type='flat-roofs',version=POLICY['version'],parent=a.base.name,parentValidationSha256=digest(a.base/'validation.json'),previousRevision=report['geometryRevision'],policy=POLICY)
        scene['stats']['uniqueTriangles']+=delta;scene['stats']['expandedTriangles']+=delta
        stats=metadata['objectLayer']['stats'];stats['uniqueObjectTriangles']+=delta;stats['expandedObjectTriangles']+=delta;stats['materials']=len(scene['materials'])
        roof_layer={k:result[k] for k in ('policy','stats','records')};metadata['objectLayer']['roofs']=roof_layer
        sources=[{k:c[k] for k in ('id','name','triangles','instanced','sourceObjectIds') if k in c} for c in scene['chunks']]
        patch=dict(features=[],surfaces=[],geometryRevision=rev,sourceChunks=sources,changedChunks=result['changedChunks'],
                   boundsMSK=metadata['boundsMSK'],roofStats=result['stats'],objectLayerUpdate=dict(buildings=result['buildings'],stats=stats,roofs=roof_layer))
        # A real source roof near the current cemetery camera, large enough to read
        # a 40 cm rim without hiding it in a city-wide overview.
        witness=[]
        for r in result['records']:
            for p in r['patches']:
                x0,z0,x1,z1=p['bounds'];size=max(x1-x0,z1-z0)
                if 15<size<65 and p['areaM2']>150:witness.append((( (x0+x1)/2-1853)**2+((z0+z1)/2-837)**2,p))
        if witness:
            p=min(witness,key=lambda v:v[0])[1];x0,z0,x1,z1=p['bounds']
            patch['witnessViews']={'flat-roof-review':dict(yaw=-.5,pitch=.9,distance=max(x1-x0,z1-z0)*1.8,target=[(x0+x1)/2,p['heightM']-2,(z0+z1)/2])}
        if a.review_camera:
            camera=json.loads(a.review_camera.read_text())
            assert set(camera)=={'yaw','pitch','distance','target'} and len(camera['target'])==3
            assert np.isfinite([camera['yaw'],camera['pitch'],camera['distance'],*camera['target']]).all() and camera['distance']>0
            patch['witnessViews']={'flat-roof-review':camera}
        save(folder/'scene.json',scene);save(a.output/'canonical/transport-metadata.json',metadata);save(a.output/'flat-roof-patch.json',patch)
        report['geometryRevision']=rev;report['flatRoofs']=dict(passed=True,**result['stats']);report['export'].update(triangles=scene['stats']['uniqueTriangles'],expandedTriangles=scene['stats']['expandedTriangles'])
        save(a.output/'canonical/validation.json',report)
        node=os.environ['NODE'];here=Path(__file__).parent
        subprocess.run([node,str(here/'pack_tiles.mjs'),str(a.output),str(a.output/'flat-roof-patch.json')],check=True)
    print('VERIFYING ROOF GEOMETRY AND PACKING',flush=True)
    proof=verify_revision(a.output,{'geometryRevision':rev},scene);save(a.output/'flat-roof-proof.json',proof)
    for name in ('canonical/urban-model.json.gz','objects.json.gz'):
        subprocess.run([node,str(here/'restyle_registry.mjs'),str(a.base/name),str(a.output/name),str(a.output/'flat-roof-patch.json')],check=True)
    if not a.skip_glb:
        print('UPDATING ROOF GLB',flush=True);export_glb(scene,folder)
    else:
        (folder/'model.glb').unlink(missing_ok=True)
    report['objectLayer'].update(patch['objectLayerUpdate']['stats']);report['export']['objectLayer']=patch['objectLayerUpdate']['stats']
    report['flatRoofs']=proof;report['export']['glbBytes']=((folder/'model.glb').stat().st_size if (folder/'model.glb').exists() else 0)
    report['export']['downloadBytes']=sum((folder/Path(c['file']).name).stat().st_size for c in scene['chunks']);save(a.output/'canonical/validation.json',report)
    parent_validation['geometryRevision']=proof;parent_validation['flatRoofs']=proof;save(a.output/'validation.json',parent_validation)
    refresh_validation_totals(a.output)
    print('FLAT ROOFS PASSED',json.dumps(proof),flush=True)
if __name__=='__main__':main()
