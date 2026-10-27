"""Raise only provenance-tagged generated parapets; retain all roof floors."""
import argparse,copy,json,subprocess,os
from pathlib import Path
from collections import defaultdict
import numpy as np
from flat_roofs import read_faces,store_faces,raise_existing,RAISE,PARAPET_HEIGHT,POLICY
from prepare_cemetery_cover import save,digest,raw
from bvh_validation import validate as validate_bvh

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--base',type=Path,required=True);ap.add_argument('--output',type=Path,required=True);a=ap.parse_args()
 assert not (a.output/'parapet-height-patch.json').exists()
 validation=json.loads((a.base/'validation.json').read_text());assert validation['passed']
 scene=json.loads((a.base/'canonical/full/scene.json').read_text());old=copy.deepcopy(scene)
 roof=json.loads((a.base/'flat-roof-patch.json').read_text());rows={r['id']:r for r in roof['objectLayerUpdate']['buildings']}
 mid=next(i for i,m in enumerate(scene['materials']) if m.get('family')=='recessed-flat-roof')
 if not a.output.exists():subprocess.run(['/bin/cp','-cR',str(a.base),str(a.output)],check=True)
 for name in ('validation.json','canonical/full/model.glb','merged/model.glb','merged/metadata.json','merged/validation.json','merged/benchmark.json'):(a.output/name).unlink(missing_ok=True)
 folder=a.output/'canonical/full';faces={};ranges=defaultdict(list)
 for c in scene['chunks']:
  if c.get('category')!='building':continue
  faces[c['id']]=read_faces(folder,c)
  for r in c.get('sourceObjectRanges',[]):
   if r['id'] in rows:ranges[r['id']].append((c['id'],r['first'],r['count']))
 changes={};updates=[];delta=0;floor_count=0;changed=[]
 for owner,items in ranges.items():
  row=rows[owner];policy=row['flatRoof'];words=np.concatenate([faces[c][i:i+n] for c,i,n in items]);out=raise_existing(words,policy['patches'],mid,policy.get('raiseM',0))
  floor=(words[:,0,6]&0x7fffffff)==mid
  assert np.array_equal(out[:len(words)][floor],words[floor]);floor_count+=int(floor.sum())
  assert np.array_equal(out[:len(words),:,[0,2,3,4,5,6,7]],words[:,:,[0,2,3,4,5,6,7]])
  delta+=len(out)-len(words);offset=0
  for j,(c,i,n) in enumerate(items):
   data=out[offset:offset+n];offset+=n
   if j==0:data=np.concatenate([data,out[len(words):]])
   changes[(c,i)]=data
  update=dict(id=owner,retainedTriangles=len(out),flatRoof={**policy,**POLICY})
  for p in update['flatRoof']['patches']:p.update(parapetHeightM=PARAPET_HEIGHT,raiseM=RAISE)
  updates.append(update)
 print('RAISED',len(updates),'buildings, extra triangles',delta,flush=True)
 for c in scene['chunks']:
  if c['id'] not in faces or not any((c['id'],r['first']) in changes for r in c['sourceObjectRanges']):continue
  output=[];owners=[]
  for r in c['sourceObjectRanges']:
   data=changes.get((c['id'],r['first']),faces[c['id']][r['first']:r['first']+r['count']]);output.append(data);owners.append((r['id'],len(data)))
  store_faces(folder,c,np.concatenate(output),owners);changed.append(c['id'])
 rev=dict(type='parapet-height',version=1,parent=a.base.name,parentValidationSha256=digest(a.base/'validation.json'),previousRevision=validation['geometryRevision'],policy=POLICY)
 for k in ('uniqueTriangles','expandedTriangles'):scene['stats'][k]+=delta
 metadata=json.loads((a.base/'canonical/transport-metadata.json').read_text());report=json.loads((a.base/'canonical/validation.json').read_text())
 stats=metadata['objectLayer']['stats']
 for k in ('uniqueObjectTriangles','expandedObjectTriangles'):stats[k]+=delta
 metadata['objectLayer']['roofs']['policy']=POLICY
 patch=dict(features=[],surfaces=[],geometryRevision=rev,changedChunks=changed,sourceChunks=[{k:c[k] for k in ('id','name','triangles','instanced','sourceObjectIds') if k in c} for c in scene['chunks']],objectLayerUpdate=dict(buildings=updates,stats=stats,roofs=metadata['objectLayer']['roofs']))
 save(folder/'scene.json',scene);save(a.output/'canonical/transport-metadata.json',metadata);save(a.output/'parapet-height-patch.json',patch)
 report['geometryRevision']=rev;report['export'].update(triangles=scene['stats']['uniqueTriangles'],expandedTriangles=scene['stats']['expandedTriangles']);save(a.output/'canonical/validation.json',report)
 node=os.environ['NODE'];here=Path(__file__).parent
 subprocess.run([node,str(here/'pack_tiles.mjs'),str(a.output),str(a.output/'parapet-height-patch.json')],check=True)
 tiles=json.loads((a.output/'tileset.json').read_text());before=json.loads((a.base/'tileset.json').read_text());old_chunks={c['id']:c for c in before['chunks']};checked=0;untouched=0;tile_ids=set()
 for c in scene['chunks']:
  if c['id'] not in changed:assert c==old['chunks'][c['id']] and digest(folder/Path(c['file']).name)==digest(a.base/'canonical/full'/Path(c['file']).name)
 for c in tiles['chunks']:
  if c['sourceChunk'] not in changed:
   assert c==old_chunks[c['id']] and digest(a.output/c['file'])==digest(a.base/c['file']);untouched+=1;continue
  data=raw(a.output,c);vb=c['vertexBytes'];ib=c['indexBytes'];nb=c['nodeBytes'];u=np.frombuffer(data[:vb],'<u4').reshape(-1,8);ix=np.frombuffer(data[vb:vb+ib],'<u4').reshape(-1,3);p=u.view('<f4')[ix,:3].astype(float);nf=np.frombuffer(data[vb+ib:vb+ib+nb],'<f4').reshape(-1,8)
  validate_bvh(p,nf,nf.view('<u4'));checked+=1;tile_ids.add(c['tileId'])
 assert scene['materials']==old['materials'] and scene['textures']==old['textures'] and scene['instances']==old['instances']
 assert digest(a.base/'canonical/terrain.npz')==digest(a.output/'canonical/terrain.npz')
 for name in ('canonical/urban-model.json.gz','objects.json.gz'):subprocess.run([node,str(here/'restyle_registry.mjs'),str(a.base/name),str(a.output/name),str(a.output/'parapet-height-patch.json')],check=True)
 # Keep provenance current for idempotent future revisions.
 roof['objectLayerUpdate']['buildings']=updates;roof['objectLayerUpdate']['roofs']['policy']=POLICY;save(a.output/'flat-roof-patch.json',roof)
 proof=dict(passed=True,buildings=len(updates),parapetHeightM=PARAPET_HEIGHT,raiseM=RAISE,roofFloorTrianglesUnchanged=floor_count,existingFacadesUnchanged=True,terrainUnchanged=True,materialsAndInstancesUnchanged=True,changedTiles=len(tile_ids),changedChunks=changed,checkedBVHs=checked,preservedPackedChunks=untouched,addedTriangles=delta)
 save(a.output/'parapet-height-proof.json',proof)
 validation.update(geometryRevision=rev,parapets=proof,triangles=tiles['stats']['fullTriangles'],meshes=len(tiles['chunks']),bvhNodes=sum(c['nodeCount'] for c in tiles['chunks']));validation['objectLayer'].update(stats);save(a.output/'validation.json',validation)
 report['parapets']=proof;report['objectLayer'].update(stats);report['export']['glbBytes']=0;save(a.output/'canonical/validation.json',report)
 print('PARAPETS PASSED',json.dumps(proof),flush=True)
if __name__=='__main__':main()
