"""Material-only roof revision using canonical source ownership and tile lineage."""
import argparse, gzip, hashlib, json, os, subprocess
from pathlib import Path
import numpy as np
from pitched_roofs import install, select_faces, MATERIAL, POLICY
from material_remap import remap
from prepare_cemetery_cover import save, digest, raw, assert_appearance_only
from object_geometry import export_glb


def verify_revision(root, city, scene):
    rev=city['geometryRevision'];parent=root.parent/rev['parent']
    assert digest(parent/'validation.json')==rev['parentValidationSha256']
    old=json.loads((parent/'canonical/full/scene.json').read_text())
    patch=json.loads((root/'pitched-roof-patch.json').read_text());mid=patch['material']
    rows={r['id']:r for r in json.loads((root/'pitched-roof-input.json').read_text())}
    assert scene['materials']==old['materials']+[MATERIAL]
    assert scene['textures']==old['textures'] and scene['instances']==old['instances'] and scene['stats']==old['stats']
    assert len(old['chunks'])==len(scene['chunks'])
    labels={};faces=0
    for a,b in zip(old['chunks'],scene['chunks']):
        data=raw(parent,a,True) if a.get('category')=='building' else None
        mask,_=select_faces(data,a,rows) if data is not None else (np.zeros(a['triangles'],bool),{})
        if not mask.any():
            assert a==b and digest(parent/'canonical/full'/Path(a['file']).name)==digest(root/'canonical/full'/Path(b['file']).name)
            continue
        assert np.flatnonzero(mask).tolist()==patch['canonicalFaces'][str(a['id'])]
        labels[a['id']]=mask;faces+=int(mask.sum())
        assert_appearance_only(data,raw(root,b,True),a,b,mask,mid,True)
    assert set(map(int,patch['canonicalFaces']))==set(labels)
    assert digest(parent/'canonical/terrain.npz')==digest(root/'canonical/terrain.npz')
    for name in old['textures']:
        assert digest(parent/'textures'/name)==digest(root/'textures'/name)
    before=json.loads((parent/'tileset.json').read_text());after=json.loads((root/'tileset.json').read_text())
    assert before['tiles']==after['tiles'] and before['sourceChunks']==after['sourceChunks']
    assert len(before['chunks'])==len(after['chunks']) and after['materials']==scene['materials'] and after['textures']==scene['textures']
    touched=[];packed_faces=0
    for a,b in zip(before['chunks'],after['chunks']):
        if a['sourceChunk'] not in labels:
            assert a==b and digest(parent/a['file'])==digest(root/b['file']);continue
        data=raw(parent,a);lineage=np.frombuffer(data[-a['lineageBytes']:],'<u4');mask=labels[a['sourceChunk']][lineage]
        if not mask.any():
            assert a==b and digest(parent/a['file'])==digest(root/b['file']);continue
        updated=raw(root,b)
        assert hashlib.sha256(updated).hexdigest()==b['sha256'] and (root/b['file']).stat().st_size==b['downloadBytes']
        assert_appearance_only(data,updated,a,b,mask,mid,False)
        touched.append(a['tileId']);packed_faces+=int(mask.sum())
    return dict(passed=True,type='pitched-roof-materials',**patch['roofStats'],
                changedTiles=len(set(touched)),changedTileChunks=len(touched),packedTriangles=packed_faces,
                geometryCornersBitIdentical=True,normalsUVsTintAndTriangleOrderBitIdentical=True,
                bvhAndLineageBitIdentical=True,allOtherMeshesBitIdentical=True,
                flatRoofAndAllExistingMaterialsUnchanged=True,terrainTexturesAndInstancesUnchanged=True,policy=POLICY)


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--skip-glb",action="store_true",help="Defer optional canonical GLB; final merged export is built separately")
    for key in ('base','output','buildings'):ap.add_argument('--'+key,type=Path,required=True)
    ap.add_argument('--review-near',type=float,nargs=3,default=[0,0,0],metavar=('X','Y','Z'))
    a=ap.parse_args();assert not a.output.exists() and a.base.parent==a.output.parent
    validation=json.loads((a.base/'validation.json').read_text());assert validation['passed']
    scene=json.loads((a.base/'canonical/full/scene.json').read_text())
    assert not any(m.get('family')==MATERIAL['family'] for m in scene['materials'])
    tiles=json.loads((a.base/'tileset.json').read_text());rows=json.loads(a.buildings.read_text())
    report=json.loads((a.base/'canonical/validation.json').read_text())
    metadata=json.loads((a.base/'canonical/transport-metadata.json').read_text())
    subprocess.run(['/bin/cp','-cR',str(a.base),str(a.output)],check=True)
    (a.output/'validation.json').unlink();save(a.output/'pitched-roof-input.json',rows)
    folder=a.output/'canonical/full';result=install(rows,scene,folder);assert result['stats']['buildings']
    labels=result['labels'];mid=result['material']
    print('PITCHED ROOFS',json.dumps(result['stats']),flush=True)
    rev=dict(type='pitched-roof-materials',version=1,parent=a.base.name,parentValidationSha256=digest(a.base/'validation.json'),previousRevision=report['geometryRevision'],policy=POLICY)
    layer={k:result[k] for k in ('policy','material','stats')}
    patch=dict(features=[],surfaces=[],geometryRevision=rev,material=mid,roofStats=result['stats'],
               canonicalFaces={str(k):np.flatnonzero(v).tolist() for k,v in labels.items()},
               objectLayerUpdate=dict(buildings=result['buildings'],stats=dict(materials=len(scene['materials'])),pitchedRoofs=layer))
    tiles['materials']=scene['materials'];tiles['geometryRevision']=rev
    for item in (tiles['objectLayer'],metadata['objectLayer']):
        item['pitchedRoofs']=layer;item['stats']['materials']=len(scene['materials'])
    tiles['stats']['objectLayer']['materials']=len(scene['materials'])
    for c in tiles['chunks']:
        if c['sourceChunk'] not in labels:continue
        data=raw(a.base,c);lineage=np.frombuffer(data[-c['lineageBytes']:],'<u4');mask=labels[c['sourceChunk']][lineage]
        if not mask.any():continue
        updated,vb,_=remap(data,c['vertexBytes'],c['indexBytes'],mask,mid)
        signature=hashlib.sha256(updated).hexdigest();file=f'meshes/{signature}.bin.gz'
        encoded=gzip.compress(updated,compresslevel=6,mtime=0);(a.output/file).write_bytes(encoded)
        c.update(vertexBytes=vb,vertexCount=vb//32,file=file,sha256=signature,downloadBytes=len(encoded))
    for key,ids in [('fullDownloadBytes',{c for t in tiles['tiles'] for c in t['chunks']}),('coarseDownloadBytes',{c for t in tiles['tiles'] for c in t['coarseChunks']})]:
        ids|={i['mesh'] for t in tiles['tiles'] for i in t['instances']}
        tiles['stats'][key]=sum(c['downloadBytes'] for c in tiles['chunks'] if c['id'] in ids)
    # Choose a real sloping roof close to the review area; no fixed object IDs.
    candidates=[]
    for c in scene['chunks']:
        if c['id'] not in labels:continue
        data=raw(a.output,c,True);v=np.frombuffer(data[:c['vertexBytes']],'<f4').reshape(-1,8)
        ix=np.frombuffer(data[c['vertexBytes']:],'<u4').reshape(-1,3)
        for r in c['sourceObjectRanges']:
            indices=ix[r['first']:r['first']+r['count']][labels[c['id']][r['first']:r['first']+r['count']]]
            if not len(indices):continue
            p=v[indices,:3];lo=p.min((0,1));hi=p.max((0,1));size=max((hi-lo)[[0,2]]);target=(lo+hi)/2
            if 15<size<120:candidates.append((float(np.linalg.norm((target-a.review_near)[[0,2]])),r['id'],size,target))
    if candidates:
        _,owner,size,target=min(candidates,key=lambda x:x[0]);patch['reviewObject']=owner
        tiles.setdefault('witnessViews',{})['pitched-roof-review']=dict(yaw=-.6,pitch=.8,distance=float(size*1.8),target=target.tolist())
    save(folder/'scene.json',scene);save(a.output/'tileset.json',tiles)
    save(a.output/'canonical/transport-metadata.json',metadata);save(a.output/'pitched-roof-patch.json',patch)
    print('VERIFYING MATERIAL-ONLY CHANGE',flush=True)
    proof=verify_revision(a.output,{'geometryRevision':rev},scene);save(a.output/'pitched-roof-proof.json',proof)
    script=Path(__file__).with_name('restyle_registry.mjs')
    for name in ('canonical/urban-model.json.gz','objects.json.gz'):
        subprocess.run([os.environ.get('NODE','node'),str(script),str(a.base/name),str(a.output/name),str(a.output/'pitched-roof-patch.json')],check=True)
    if not a.skip_glb:
        print('UPDATING GLB MATERIAL ASSIGNMENTS',flush=True);export_glb(scene,folder)
    else:
        (folder/'model.glb').unlink(missing_ok=True)
    report['geometryRevision']=rev;report['pitchedRoofs']=proof;report['objectLayer']['materials']=len(scene['materials'])
    report['export']['objectLayer']['materials']=len(scene['materials']);report['export']['glbBytes']=((folder/'model.glb').stat().st_size if (folder/'model.glb').exists() else 0)
    report['export']['downloadBytes']=sum((folder/Path(c['file']).name).stat().st_size for c in scene['chunks'])
    save(a.output/'canonical/validation.json',report)
    validation['geometryRevision']=rev;validation['pitchedRoofs']=proof;validation['objectLayer']['materials']=len(scene['materials'])
    save(a.output/'validation.json',validation)
    print('PITCHED ROOFS PASSED',json.dumps(proof),flush=True)


if __name__=='__main__':main()
