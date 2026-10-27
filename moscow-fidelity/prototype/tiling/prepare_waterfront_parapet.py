"""Add the optional Moscow-style stone parapet to verified connected banks."""
import argparse,json,os,subprocess,gzip
from pathlib import Path
import numpy as np
import shapely as sh
from waterfront_parapet import parapet_geometry,POLICY,MATERIAL,JOINT_MATERIAL
from flat_roofs import read_faces,encode_faces
from prepare_cemetery_cover import save,digest
from prepare_waterfront_finish import verify

def append_faces(folder,chunk,tri,materials):
 """Retain every original packed attribute; encode only the added parapet."""
 inherited=read_faces(folder,chunk)
 added=encode_faces(tri[:,:,:3],0);added.view('<f4')[:,:,4:6]=tri[:,:,6:8]
 added[:,:,6]=np.asarray(materials,dtype='<u4')[:,None]|0x80000000
 xyz=added.view('<f4')[:,:,:3]
 keep=np.linalg.norm(np.cross(xyz[:,1]-xyz[:,0],xyz[:,2]-xyz[:,0]),axis=1)>1e-9
 faces=np.concatenate([inherited,added[keep]])
 vertices,indices=np.unique(faces.reshape(-1,8),axis=0,return_inverse=True);indices=indices.astype('<u4')
 assert np.array_equal(vertices[indices.reshape(-1,3)][:len(inherited)],inherited)
 with gzip.GzipFile(filename=str(folder/Path(chunk['file']).name),mode='wb',mtime=0,compresslevel=6) as f:
  f.write(vertices.tobytes());f.write(indices.tobytes())
 p=faces.view('<f4')[:,:,:3]
 return dict(vertexCount=len(vertices),vertexBytes=vertices.nbytes,triangles=len(faces),bounds=dict(min=p.min((0,1)).tolist(),max=p.max((0,1)).tolist()))


def main():
 ap=argparse.ArgumentParser();ap.add_argument('--base',type=Path,required=True);ap.add_argument('--output',type=Path,required=True);ap.add_argument('--resume',action='store_true');a=ap.parse_args()
 base,root=a.base,a.output;parent=json.loads((base/'validation.json').read_text());assert parent['passed']
 old=json.loads((base/'canonical/full/scene.json').read_text());assert not old['waterfront'].get('parapet')
 if not root.exists():subprocess.run(['/bin/cp','-cR',str(base),str(root)],check=True)
 else:assert a.resume
 (root/'validation.json').unlink(missing_ok=True)
 folder=root/'canonical/full';patchfile=root/'waterfront-parapet-patch.json';node=os.environ['NODE'];here=Path(__file__).parent
 if not patchfile.exists():
  scene=json.loads((folder/'scene.json').read_text());catalog=json.loads((root/'tileset.json').read_text())
  banks=np.load(folder/'water-bank-segments.npz');domain=sh.from_wkb((folder/'water-bank-domain.wkb').read_bytes())
  tri,joints,stats=parapet_geometry(banks,scene['origin'],domain,catalog['boundsMSK'])
  cid=next(c['id'] for c in scene['chunks'] if c['name']=='waterfront-bank');c=scene['chunks'][cid]
  mid=len(scene['materials']);scene['materials']+=[MATERIAL,JOINT_MATERIAL]
  mesh=append_faces(folder,c,tri,np.where(joints,mid+1,mid));delta=mesh['triangles']-c['triangles'];c.update(mesh)
  for key in ('uniqueTriangles','expandedTriangles'):scene['stats'][key]+=delta
  scene['waterfront']['parapet']=dict(policy=POLICY,stats=stats,materials=[mid,mid+1]);scene['waterfront']['stats']['bankTriangles']=mesh['triangles']
  rev=dict(type='waterfront-parapet',version=1,parent=base.name,parentValidationSha256=digest(base/'validation.json'),policy=POLICY,previousRevision=parent.get('geometryRevision'))
  views=dict(catalog.get('witnessViews',{}));view=dict(views['waterfront-review']);view.update(distance=18.,pitch=.22)
  target=list(view['target']);target[1]+=2.5;view['target']=target;views['waterfront-parapet-review']=view
  patch=dict(features=[],surfaces=[],changedChunks=[cid],sourceChunks=[{k:c[k] for k in ('id','name','triangles','instanced','sourceObjectIds') if k in c} for c in scene['chunks']],geometryRevision=rev,witnessViews=views,waterfront=scene['waterfront'])
  save(folder/'scene.json',scene);save(patchfile,patch)
  report=json.loads((root/'canonical/validation.json').read_text());report['geometryRevision']=rev;report['export'].update(triangles=scene['stats']['uniqueTriangles'],expandedTriangles=scene['stats']['expandedTriangles']);save(root/'canonical/validation.json',report)
  for file in [root/'validation.json',folder/'model.glb']:
   file.unlink(missing_ok=True)
  print('PARAPET BUILT',json.dumps(stats),flush=True)
 patch=json.loads(patchfile.read_text());scene=json.loads((folder/'scene.json').read_text());cid=patch['changedChunks'][0]
 current=json.loads((root/'tileset.json').read_text())
 if current.get('geometryRevision')!=patch['geometryRevision']:subprocess.run([node,str(here/'pack_tiles.mjs'),str(root),str(patchfile)],check=True)
 print('VERIFY PARAPET AND TILE SEAMS',flush=True)
 inherited=read_faces(base/'canonical/full',old['chunks'][cid])
 assert np.array_equal(read_faces(folder,scene['chunks'][cid])[:len(inherited)],inherited)
 proof=verify(base,root,old,scene,cid);proof.update(dict(inheritedBankAttributesBitIdentical=True,policy=POLICY,**scene['waterfront']['parapet']['stats']));save(root/'waterfront-parapet-proof.json',proof)
 for name in ('canonical/urban-model.json.gz','objects.json.gz'):subprocess.run([node,str(here/'restyle_registry.mjs'),str(base/name),str(root/name),str(patchfile)],check=True)
 tiles=json.loads((root/'tileset.json').read_text());tiles['waterfront']=scene['waterfront'];save(root/'tileset.json',tiles)
 report=json.loads((root/'canonical/validation.json').read_text());report['waterfrontParapet']=proof;save(root/'canonical/validation.json',report)
 parent.update(geometryRevision=patch['geometryRevision'],waterfrontParapet=proof,meshes=len(tiles['chunks']),triangles=tiles['stats']['fullTriangles'],bvhNodes=sum(c['nodeCount'] for c in tiles['chunks']));save(root/'validation.json',parent)
 print('PARAPET PASSED',json.dumps(proof),flush=True)
if __name__=='__main__':main()
