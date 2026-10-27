"""Refine existing banks only; reuse terrain, water selection and every other mesh."""
import argparse,json,gzip,subprocess,shutil
from pathlib import Path
import numpy as np
import shapely as sh
from waterfront_finish import finished_bank,cornice_geometry,install_texture,MATERIAL,POLICY,TEXTURE
from object_geometry import pack,export_glb
from prepare_cemetery_cover import save,digest,raw
from flat_roofs import read_faces
from bvh_validation import validate as validate_bvh

def verify(base,root,old,scene,cid):
    assert old['instances']==scene['instances']
    assert old['materials'][:old['waterfront']['material']]==scene['materials'][:old['waterfront']['material']]
    assert digest(base/'canonical/terrain.npz')==digest(root/'canonical/terrain.npz')
    for c in old['chunks']:
        if c['id']==cid:continue
        assert c==scene['chunks'][c['id']]
        assert digest(base/'canonical/full'/Path(c['file']).name)==digest(root/'canonical/full'/Path(c['file']).name)
    before=json.loads((base/'tileset.json').read_text());after=json.loads((root/'tileset.json').read_text());previous={c['id']:c for c in before['chunks']}
    faces=read_faces(root/'canonical/full',scene['chunks'][cid]);q=faces.view('<f4')[:,:,:3].astype(float)
    area=np.linalg.norm(np.cross(q[:,1]-q[:,0],q[:,2]-q[:,0]),axis=1)/2;acc=np.zeros(len(q));allow=np.zeros(len(q));untouched=0;touched=set();maxdist=0.;maxuv=0.
    for c in after['chunks']:
        if c['sourceChunk']!=cid:
            assert c==previous[c['id']] and digest(root/c['file'])==digest(base/c['file']);untouched+=1;continue
        data=raw(root,c);assert __import__('hashlib').sha256(data).hexdigest()==c['sha256']
        vb,ib,nb=c['vertexBytes'],c['indexBytes'],c['nodeBytes'];w=np.frombuffer(data[:vb],'<u4').reshape(-1,8);ix=np.frombuffer(data[vb:vb+ib],'<u4').reshape(-1,3)
        p=w.view('<f4')[ix,:3].astype(float);lineage=np.frombuffer(data[vb+ib+nb:],'<u4');nodes=np.frombuffer(data[vb+ib:vb+ib+nb],'<f4').reshape(-1,8)
        validate_bvh(p,nodes,nodes.view('<u4'));source=q[lineage];n=np.cross(source[:,1]-source[:,0],source[:,2]-source[:,0]);ln=np.linalg.norm(n,axis=1)
        distance=abs(np.einsum('nki,ni->nk',p-source[:,0,None,:],n))/np.maximum(ln[:,None],1e-20);maxdist=max(maxdist,float(distance.max(initial=0)));assert maxdist<.001
        assert np.array_equal(w[ix[:,0],6],faces[lineage,0,6]);assert np.isfinite(w.view('<f4')[ix,4:6]).all()
        v=source[:,1]-source[:,0];u=source[:,2]-source[:,0];vv=(v*v).sum(1);uu=(u*u).sum(1);vu=(v*u).sum(1);det=vv*uu-vu*vu
        safe=(det>1e-10)&(np.linalg.norm(v,axis=1)>.01)
        dp=p-source[:,0,None,:];pv=np.einsum('nki,ni->nk',dp,v);pu=np.einsum('nki,ni->nk',dp,u)
        den=np.where(safe,det,1)[:,None];b1=(pv*uu[:,None]-pu*vu[:,None])/den;b2=(pu*vv[:,None]-pv*vu[:,None])/den
        uv=faces.view('<f4')[lineage,:,4:6].astype(float);expected=uv[:,0,None,:]+b1[:,:,None]*(uv[:,1]-uv[:,0])[:,None,:]+b2[:,:,None]*(uv[:,2]-uv[:,0])[:,None,:]
        maxuv=max(maxuv,float(abs(expected-w.view('<f4')[ix,4:6])[safe].max(initial=0)));assert maxuv<.02

        area2=np.linalg.norm(np.cross(p[:,1]-p[:,0],p[:,2]-p[:,0]),axis=1)/2
        epsilon=.5*np.linalg.norm(np.spacing(abs(p).astype('<f4').max(1)).astype(float),axis=1);perimeter=np.linalg.norm(p-np.roll(p,1,axis=1),axis=2).sum(1)
        np.add.at(acc,lineage,area2);np.add.at(allow,lineage,perimeter*epsilon+3*epsilon**2);touched.add(c['tileId'])
    assert np.all(abs(acc-area)<allow*1.02+1e-6)
    for a,b in zip(before['tiles'],after['tiles']):assert a['instances']==b['instances'] and a['boundsMSK']==b['boundsMSK']
    return dict(passed=True,changedSourceChunks=[cid],changedTiles=len(touched),preservedTileChunks=untouched,terrainWaterAndUnrelatedMeshesBitIdentical=True,tileAreaConservationPassed=True,packedBVHPassed=True,maxPackedPlaneDistanceM=maxdist,maxPackedUVError=maxuv,continuousUVPassed=True,highParapet=False,textureHorizontalRepeatM=4)

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--base',type=Path,required=True);ap.add_argument('--output',type=Path,required=True);ap.add_argument('--node',required=True);ap.add_argument('--resume',action='store_true');ap.add_argument('--skip-export',action='store_true');a=ap.parse_args()
    base,root=a.base,a.output;parent=json.loads((base/'validation.json').read_text());assert parent['passed']
    if not root.exists():subprocess.run(['/bin/cp','-cR',str(base),str(root)],check=True)
    elif not a.resume:raise ValueError('Output exists; use --resume')
    folder=root/'canonical/full';old=json.loads((base/'canonical/full/scene.json').read_text());scene=json.loads((folder/'scene.json').read_text());patchfile=root/'waterfront-finish-patch.json'
    if old['waterfront'].get('finish',{}).get('policy')==POLICY:
        print('BANK FINISH ALREADY CURRENT; validated copy retained',flush=True);return
    c=next(c for c in scene['chunks'] if c['name']=='waterfront-bank');cid=c['id']
    if patchfile.exists() and scene['waterfront'].get('finish',{}).get('policy',{}).get('version')!=POLICY['version']:
        scene=json.loads(json.dumps(old));c=scene['chunks'][cid];patchfile.unlink()
    if not patchfile.exists():
        banks=np.load(folder/'water-bank-segments.npz');domain=sh.from_wkb((folder/'water-bank-domain.wkb').read_bytes());wall=finished_bank(banks,scene['origin']);cornice,stats=cornice_geometry(banks,scene['origin'],domain)
        old_faces=read_faces(base/'canonical/full',old['chunks'][cid]);old_pos=old_faces.view('<f4')[:,:,:3]
        # Input pack drops only degenerate shore triangles.
        rounded=wall[:,:,:3].astype('<f4');n=np.cross(rounded[:,1]-rounded[:,0],rounded[:,2]-rounded[:,0]);valid=np.linalg.norm(n,axis=1)>1e-9
        assert np.array_equal(old_pos,wall[valid,:,:3].astype('<f4'))
        tri=np.concatenate([wall,cornice]);mid=scene['waterfront']['material'];mesh=pack(tri,np.full(len(tri),mid),folder/Path(c['file']).name)
        delta=mesh['triangles']-c['triangles'];c.update(mesh)
        for key in ['uniqueTriangles','expandedTriangles']:scene['stats'][key]+=delta
        scene['materials'][mid]=MATERIAL.copy();scene['textures'].update(install_texture(folder));shutil.copyfile(folder/TEXTURE,root/'textures'/TEXTURE)
        scene['waterfront']['finish']=dict(policy=POLICY,stats=stats);scene['waterfront']['stats']['bankTriangles']=mesh['triangles']
        rev=dict(type='waterfront-finish',version=POLICY['version'],parent=base.name,parentValidationSha256=digest(base/'validation.json'),policy=POLICY,previousRevision=parent.get('geometryRevision'))
        views=json.loads((base/'tileset.json').read_text()).get('witnessViews',{})
        # Closer than the former 28 m view so individual mooring rings read clearly.
        if 'waterfront-review' in views:views['waterfront-review']={**views['waterfront-review'],'distance':14.,'pitch':.22}
        patch=dict(changedChunks=[cid],geometryRevision=rev,witnessViews=views)
        save(folder/'scene.json',scene);save(patchfile,patch)
        report=json.loads((root/'canonical/validation.json').read_text());report['geometryRevision']=rev;report['export'].update(triangles=scene['stats']['uniqueTriangles'],expandedTriangles=scene['stats']['expandedTriangles']);save(root/'canonical/validation.json',report)
        # A cloned previous export must not masquerade as the new revision.
        for file in [folder/'model.glb',root/'merged/model.glb',root/'merged/metadata.json',root/'merged/validation.json',root/'merged/benchmark.json',root/'validation.json']:
            if file.exists():file.unlink()
        print('BANK FINISH BUILT',json.dumps(stats),flush=True)
    patch=json.loads(patchfile.read_text());current=json.loads((root/'tileset.json').read_text())
    if current.get('geometryRevision')!=patch['geometryRevision']:subprocess.run([a.node,str(Path(__file__).parent/'pack_tiles.mjs'),str(root),str(patchfile)],check=True)
    print('VERIFY BANK FINISH',flush=True);proof=verify(base,root,old,scene,cid);save(root/'waterfront-finish-proof.json',proof)
    tiles=json.loads((root/'tileset.json').read_text());parent.update(geometryRevision=patch['geometryRevision'],waterfrontFinish=proof,meshes=len(tiles['chunks']),triangles=tiles['stats']['fullTriangles'],bvhNodes=sum(c['nodeCount'] for c in tiles['chunks']))
    report=json.loads((root/'canonical/validation.json').read_text());report['waterfrontFinish']=proof
    if not a.skip_export:
        print('EXPORT CANONICAL GLB',flush=True);export_glb(scene,folder);report['export']['glbBytes']=(folder/'model.glb').stat().st_size
    save(root/'canonical/validation.json',report);save(root/'validation.json',parent);print('BANK FINISH PASSED',json.dumps(proof),flush=True)

if __name__=='__main__':main()
