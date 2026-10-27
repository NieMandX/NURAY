"""Prove large area deltas caused solely by float32 tile-cut vertices.

A long, thin triangle can change area by centimetres squared when a cut vertex
rounds by a fraction of a millimetre. Do not enlarge the global area tolerance:
recover each legal cut point independently, require half-ULP coordinate error,
then check conservation before quantization. Lost/duplicated faces still fail.
"""
import numpy as np


def area(triangles):
    return np.linalg.norm(np.cross(triangles[:,1]-triangles[:,0],
                                   triangles[:,2]-triangles[:,0]),axis=1)/2


def verify_quantized_partition(original, parts):
    original=np.asarray(original,dtype=float)
    candidates=list(original)
    planes={axis:sorted({float(v) for _,bounds in parts for v in (bounds['min'][axis],bounds['max'][axis])}) for axis in (0,2)}
    for a,b in zip(original,np.roll(original,-1,axis=0)):
        for axis,edges in planes.items():
            if a[axis]==b[axis]:continue
            for edge in edges:
                t=(edge-a[axis])/(b[axis]-a[axis])
                if 0<=t<=1:
                    p=a+(b-a)*t;p[axis]=edge;candidates.append(p)
    a,b=original[1]-original[0],original[2]-original[0]
    normal=np.cross(a,b)
    # A grid corner in the interior of a nonvertical source face.
    if abs(normal[1])>1e-12:
        unit=normal/np.linalg.norm(normal)
        for x in planes[0]:
            for z in planes[2]:
                y=original[0,1]-(normal[0]*(x-original[0,0])+normal[2]*(z-original[0,2]))/normal[1]
                p=np.array([x,y,z])
                sides=[np.cross(q-p0,p-p0)@unit for p0,q in zip(original,np.roll(original,-1,axis=0))]
                if min(sides)>=-1e-8:candidates.append(p)
    candidates=np.asarray(candidates)
    restored=[];max_error=0.
    for triangles,_ in parts:
        triangles=np.asarray(triangles,dtype=float)
        fixed=[]
        for point in triangles.reshape(-1,3):
            packed=point.astype(np.float32)
            ulp=np.maximum(np.nextafter(packed,np.float32(np.inf)).astype(float)-point,
                           point-np.nextafter(packed,np.float32(-np.inf)).astype(float))
            difference=np.abs(candidates-point)
            # A tiny double-precision allowance covers intersection arithmetic;
            # the main allowance is exactly the float32 rounding interval.
            valid=np.all(difference<=ulp*.5+1e-8,axis=1)
            if not valid.any():raise AssertionError(('Vertex is not a rounded source cut',point.tolist()))
            index=np.flatnonzero(valid)[np.argmin(np.linalg.norm(difference[valid],axis=1))]
            fixed.append(candidates[index]);max_error=max(max_error,float(difference[index].max()))
        fixed=np.asarray(fixed).reshape(-1,3,3)
        assert np.all(np.cross(fixed[:,1]-fixed[:,0],fixed[:,2]-fixed[:,0])@normal>=-1e-9),'Reversed cut face'
        restored.append(fixed)
    restored=np.concatenate(restored)
    expected=float(area(original[None])[0]);actual=float(area(restored).sum())
    assert abs(actual-expected)<max(1e-8,expected*1e-10),('Lost or duplicated source area before float32 rounding',expected,actual)
    return dict(maxCoordinateRoundingM=max_error,unquantizedAreaErrorM2=abs(actual-expected))


def verify_area_exceptions(root,canonical,manifest,sources,accumulated,threshold=.02):
    import gzip
    from pathlib import Path
    from collections import defaultdict
    failed={key:np.flatnonzero(np.abs(accumulated[key]-source['area'])>=threshold) for key,source in sources.items()}
    failed={key:indices for key,indices in failed.items() if len(indices)}
    originals={};parts=defaultdict(list);tiles={t['id']:t['bounds'] for t in manifest['tiles']}
    for c in canonical['chunks']:
        if c['id'] not in failed:continue
        raw=gzip.decompress((root/'canonical/full'/Path(c['file']).name).read_bytes())
        v=np.frombuffer(raw[:c['vertexBytes']],'<f4').reshape(-1,8)
        ix=np.frombuffer(raw[c['vertexBytes']:],'<u4').reshape(-1,3)
        for primitive in failed[c['id']]:originals[c['id'],int(primitive)]=v[ix[primitive],:3].astype(float)
    for c in manifest['chunks']:
        if c['sourceChunk'] not in failed:continue
        assert not c.get('instanced'),'Shared geometry must remain byte-identical'
        raw=gzip.decompress((root/c['file']).read_bytes());vb,ib,nb=[c[k] for k in ('vertexBytes','indexBytes','nodeBytes')]
        lineage=np.frombuffer(raw[vb+ib+nb:],'<u4')
        v=np.frombuffer(raw[:vb],'<f4').reshape(-1,8);ix=np.frombuffer(raw[vb:vb+ib],'<u4').reshape(-1,3)
        for primitive in failed[c['sourceChunk']]:
            mask=lineage==primitive
            if mask.any():parts[c['sourceChunk'],int(primitive)].append((v[ix[mask],:3].astype(float),tiles[c['tileId']]))
    proofs=[]
    for key,original in originals.items():
        if not parts[key]:raise AssertionError(('Missing complete source primitive',key))
        proof=verify_quantized_partition(original,parts[key])
        proofs.append(dict(sourceChunk=key[0],primitive=key[1],areaDeltaM2=float(accumulated[key[0]][key[1]]-sources[key[0]]['area'][key[1]]),**proof))
    return dict(passed=True,roundingExceptions=len(proofs),proofs=proofs)
