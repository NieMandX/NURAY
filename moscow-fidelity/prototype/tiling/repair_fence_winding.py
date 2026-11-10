"""Repair an incomplete release only after reconstructing every affected face.

Fresh builds use object_geometry.pack's general quantization rule. This recovery
path preserves a completed large fence build, with no source-ID/location list.
"""
import argparse,gzip,hashlib,json,tempfile
from pathlib import Path
import ijson
import numpy as np
from canonical_store import copy_asset
from fence_geometry import profile
from street_library import Mesh
from object_geometry import pack,clip_triangles
from prepare_fence_types import verify_mesh
from prepare_foundations import save
from quantized_winding import reversed_faces,repair_faces


def reconstruct(root,words,indices,rows):
    metadata=json.loads((root/'canonical/transport-metadata.json').read_text())
    ox,oy,_=metadata['originMSK'];b=metadata['boundsMSK'];box=[b[0]-ox,oy-b[3],b[2]-ox,oy-b[1]]
    path=root/'street-objects.json'
    with path.open('rb') as f:materials=next(ijson.items(f,'materials',use_float=True))
    bad=words[indices[rows]].copy();centers=bad.view('<f4')[:,:,:3].mean(1,dtype=float)[:,[0,2]]
    originals={};witnesses=[]
    with path.open('rb') as f,tempfile.TemporaryDirectory() as td:
        for row in ijson.items(f,'objects.item',use_float=True):
            if row['layer']!='Fence':continue
            coords=np.asarray(row['sourceCoordinates']);q=np.column_stack((coords[:,0]-ox,oy-coords[:,1]))
            # Conservative bound for every currently supported profile (largest
            # half-width 0.48 m). Exact geometry/attribute matching follows.
            candidates=np.flatnonzero(((centers>=q.min(0)-.6)&(centers<=q.max(0)+.6)).all(1))
            if not len(candidates):continue
            for pi,p in enumerate(row['groundProfile']):
                ab=np.array([p['a'],p['b']]);near=candidates[((centers[candidates]>=ab.min(0)-.6)&(centers[candidates]<=ab.max(0)+.6)).all(1)]
                if not len(near):continue
                mesh=Mesh();profile(mesh,p['a'],p['b'],*p['heights'],row['classification']);t,m=mesh.arrays()
                t,m=clip_triangles(t,m,box)
                output=Path(td)/'profile.gz';meta=pack(t,np.asarray(materials)[m],output)
                if meta is None:continue
                raw=gzip.decompress(output.read_bytes());v=np.frombuffer(raw,'<u4',count=meta['vertexBytes']//4).reshape(-1,8);ix=np.frombuffer(raw,'<u4',offset=meta['vertexBytes']).reshape(-1,3)
                expected=v[ix]
                for bi in near:
                    if not (expected==bad[bi,[0,2,1]]).all((1,2)).any():continue
                    matches=np.flatnonzero((t[:,:,:3].astype('<f4')==bad[bi].view('<f4')[:,:3]).all((1,2)))
                    assert len(matches)==1,('Ambiguous source profile',row['id'],pi)
                    original=t[matches[0]]
                    if int(bi) in originals:assert np.array_equal(originals[int(bi)],original)
                    originals[int(bi)]=original
                    witnesses.append(dict(triangle=int(rows[bi]),sourceId=row['id'],profileIndex=pi,
                                          freshPackAttributesMatch=True,maxCoordinateRoundingM=float(np.max(np.abs(original[:,:3]-original[:,:3].astype('<f4'))))))
    assert set(originals)==set(range(len(rows))),('Unproven reversed fence faces',len(rows)-len(originals))
    return np.array([originals[i] for i in range(len(rows))]),materials,witnesses


def repair(root,backup):
    root,backup=Path(root),Path(backup)
    assert not (root/'validation.json').exists(),'Never modify a validated release'
    assert not backup.exists(),'Keep the previous recovery snapshot immutable'
    scene_path=root/'canonical/full/scene.json';scene=json.loads(scene_path.read_text())
    chunk=next(c for c in scene['chunks'] if c['name']=='street-fences')
    path=root/'canonical/full'/chunk['file'];raw=bytearray(gzip.decompress(path.read_bytes()))
    before=hashlib.sha256(raw).hexdigest()
    words=np.frombuffer(raw,'<u4',count=chunk['vertexBytes']//4).reshape(-1,8)
    indices=np.frombuffer(raw,'<u4',offset=chunk['vertexBytes']).reshape(-1,3)
    rows=np.concatenate(list(reversed_faces(words,indices)))
    print('FENCE WINDING RECONSTRUCT',len(rows),'/',len(indices),flush=True)
    originals,materials,witnesses=reconstruct(root,words,indices,rows)
    old=indices[rows].copy();repair_faces(words,indices,rows,originals);new=indices[rows].copy()
    assert np.array_equal(np.sort(old,axis=1),np.sort(new,axis=1))
    verify_mesh(raw,chunk,materials)
    after=hashlib.sha256(raw).hexdigest()
    indices[rows]=old
    assert hashlib.sha256(raw).hexdigest()==before,'Unrelated packed attributes changed'
    indices[rows]=new
    assert hashlib.sha256(raw).hexdigest()==after
    backup.mkdir(parents=True);copy_asset(path,backup/path.name);copy_asset(scene_path,backup/'scene.json')
    temporary=path.with_suffix(path.suffix+'.tmp')
    with gzip.GzipFile(filename=str(temporary),mode='wb',mtime=0,compresslevel=6) as f:f.write(memoryview(raw))
    temporary.replace(path)
    chunk['quantizedWindingRepairs']=chunk.get('quantizedWindingRepairs',0)+len(rows)
    save(scene_path,scene)
    proof=dict(passed=True,changedChunks=[chunk['id']],repairedTriangles=len(rows),triangles=len(indices),
               beforeSha256=before,afterSha256=after,allVertexAttributesUnchanged=True,
               allOtherIndexBytesUnchanged=True,allFacesRetained=True,sourceWitnesses=witnesses,
               policy='Only Float32 conversion reversals, independently reconstructed from stored source profiles; swap corners 2/3')
    save(root/'fence-winding-repair.json',proof)
    print('FENCE WINDING REPAIRED',json.dumps(proof),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);p.add_argument('--backup',type=Path,required=True)
    a=p.parse_args();repair(a.root,a.backup)
