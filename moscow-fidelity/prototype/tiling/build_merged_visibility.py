"""Recover semantic visibility groups without changing an existing merged GLB.

Replay the exporter's bounded batches, welding and material order, verifying
both buffers against the published trace manifest. Mixed fence batches get
vertex ranges; pure batches need only a category. No coordinate/feature IDs.
"""
import argparse,gzip,hashlib,json
from pathlib import Path
import numpy as np
LIMIT=4_000_000

def category(c):
    name=c['name']
    if c.get('category')=='vegetation' or name.startswith('nuray-approved-'):return 'vegetation'
    if name=='street-fences':return 'fences'
    if name.startswith('street-lamppost'):return 'lights'
    if name.startswith(('street-swing','street-slide','street-trampoline')):return 'playgrounds'
    return None

def runs(ids):
    if not len(ids):return []
    cuts=np.flatnonzero(np.diff(ids)!=1)+1
    starts=np.r_[0,cuts];ends=np.r_[cuts,len(ids)]
    return [[int(ids[a]),int(b-a)] for a,b in zip(starts,ends)]

def build(source,output,merged=None):
    merged=merged or source/'merged'
    scene=json.loads((source/'canonical/full/scene.json').read_text())
    trace=json.loads((merged/'trace/manifest.json').read_text())
    meta=json.loads((merged/'metadata.json').read_text())
    records={d['id']:d for d in trace['draws']};result=[];pending=[];count=0;draw=0
    def flush():
        nonlocal count,draw
        if not pending:return
        d=meta['draws'][draw];record=records[draw];cats={c for _,_,c in pending}
        item={'id':draw,'name':d['name']}
        if len(cats)==1:
            item['layer']=next(iter(cats))
            assert sum(len(ix) for _,ix,_ in pending)==d['triangles']
            if item['layer']:
                words=np.concatenate([v for v,_,_ in pending]);ix=np.concatenate([i for _,i,_ in pending])
                unique,inverse=np.unique(words.view('V32').ravel(),return_inverse=True)
                vertices=unique.view('<u4').reshape(-1,8);indices=inverse[ix].astype('<u4')
                indices=indices[np.argsort(vertices[indices[:,0],6]&0x7fffffff,kind='stable')]
                assert hashlib.sha256(vertices.tobytes()).hexdigest()==record['vertexSha256']
                assert hashlib.sha256(indices.tobytes()).hexdigest()==record['indexSha256']
        else:
            words=np.concatenate([v for v,_,_ in pending]);ix=np.concatenate([i for _,i,_ in pending]);flags=np.concatenate([np.full(len(v),c=='fences',dtype=np.uint8) for v,_,c in pending])
            unique,first,inverse=np.unique(words.view('V32').ravel(),return_index=True,return_inverse=True)
            flags_unique=flags[first];assert np.array_equal(flags,flags_unique[inverse]),'Cross-category welded vertex'
            vertices=unique.view('<u4').reshape(-1,8);indices=inverse[ix].astype('<u4')
            materials=vertices[indices[:,0],6]&0x7fffffff
            indices=indices[np.argsort(materials,kind='stable')]
            assert hashlib.sha256(vertices.tobytes()).hexdigest()==record['vertexSha256']
            assert hashlib.sha256(indices.tobytes()).hexdigest()==record['indexSha256']
            assert (flags_unique[indices]==flags_unique[indices[:,0],None]).all(),'Triangle crosses layer'
            ids=np.flatnonzero(flags_unique);assert (vertices[ids,7]==0).all(),'Fence tint must be zero'
            if len(ids):item['fenceVertexRanges']=runs(ids);item['fenceTriangles']=int(flags_unique[indices[:,0]].sum())
        result.append(item);print(draw,item.get('layer'),len(item.get('fenceVertexRanges',[])),flush=True)
        pending.clear();count=0;draw+=1
    static=[c for c in scene['chunks'] if not c.get('instanced')]
    for c in static:
        data=gzip.decompress((source/'canonical/full'/Path(c['file']).name).read_bytes());words=np.frombuffer(data[:c['vertexBytes']],'<u4').reshape(-1,8);ix=np.frombuffer(data[c['vertexBytes']:],'<u4').reshape(-1,3)
        for start in range(0,len(ix),500000):
            block=ix[start:start+500000];ids,remap=np.unique(block,return_inverse=True);vertices=words[ids].copy()
            if count+len(vertices)>LIMIT:flush()
            pending.append((vertices,remap.reshape(-1,3).astype('<u4')+count,category(c)));count+=len(vertices)
    flush()
    for c in (c for c in scene['chunks'] if c.get('instanced')):
        d=meta['draws'][draw];assert d['name']==c['name'];result.append({'id':draw,'name':d['name'],'layer':category(c)});draw+=1
    assert draw==len(meta['draws'])
    proof={'format':'nuray-merged-visibility-v1','headerSha256':trace['headerSha256'],'draws':result}
    output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(proof,separators=(',',':'))+'\n')
    print('Visibility verified',output,output.stat().st_size,flush=True)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();build(a.source,a.output)
