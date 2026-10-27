"""Stateless vegetation variation in the renderer's Y-up coordinate frame.

Source point indices and transport tiles are NOT persistent provider IDs.
Until an explicit sourceObjectId is supplied, use original MSK77 XY (1 mm)
and source class. Ignore terrain Z, import order, model variant and crop origin.
"""
import hashlib
import json
import math
import numpy as np

SEED = 'nuray-vegetation-v1'
POLICY = dict(version=1,seed=SEED,hash='SHA-256',scaleMin=.92,scaleMax=1.08,
    yawRangeDegrees=[-180,180],coordinateGridM=.001,namespace='2gis:MSK77',
    identity='explicit sourceObjectId, else source layer + original MSK77 XY at 1 mm; never import index or transport tile',
    transform='world-vertical yaw and uniform scale about the source model origin; original placement and source linear transform retained')

def key_for(row):
    provider=row.get('sourceObjectId')
    if provider is not None:
        identity=['2gis:MSK77','object',str(provider)]
    else:
        xy=[math.floor(float(x)*1000+.5) for x in row['position'][:2]]
        identity=['2gis:MSK77','point',row['layer'],*xy]
    return json.dumps(identity,ensure_ascii=False,separators=(',',':'))

def unit(key,channel):
    payload=json.dumps([SEED,key,channel],ensure_ascii=False,separators=(',',':')).encode('utf-8')
    # A precisely defined 53-bit fraction, independent of Python hash seeds,
    # RNG state, machine byte order, frame time or enumeration order.
    return (int.from_bytes(hashlib.sha256(payload).digest()[:8],'big')>>11)/2**53

def parameters(row):
    key=key_for(row)
    return dict(version=1,key=key,yawDegrees=360*unit(key,'yaw')-180,
                scale=.92+.16*unit(key,'scale'))

def transform(matrix,p,base_linear=None):
    m=np.asarray(matrix,dtype=float).reshape(3,4).copy()
    base=m[:,:3].copy() if base_linear is None else np.asarray(base_linear,dtype=float).reshape(3,3)
    a=math.radians(p['yawDegrees']);c,s=math.cos(a),math.sin(a)
    yaw=np.array([[c,0,s],[0,1,0],[-s,0,c]])
    m[:,:3]=(yaw@base)*p['scale']
    return m.ravel().tolist(),base.ravel().tolist()

def apply(layer,manifest):
    by_id={i['id']:i for i in manifest['instances'] if i.get('id')}
    for row in layer['vegetation']:
        p=parameters(row);row['variation']=p
        for instance in row['renderInstances']:
            matrix,base=transform(instance['matrix'],p,instance.get('variationBaseLinear'))
            instance.update(matrix=matrix,variationBaseLinear=base)
            by_id[instance['id']].update(matrix=list(matrix),variationBaseLinear=list(base))
    layer['variation']=dict(POLICY)
    layer['policy']['vegetation']='source position and base transform, deterministic per-plant yaw and uniform size variation; root retained; shared mesh/BVH'

def verify(layer,manifest):
    assert layer['variation']==POLICY
    by_id={i['id']:i for i in manifest['instances'] if i.get('id')}
    keys=[];scales=[];angles=[]
    for row in layer['vegetation']:
        expected=parameters(row);assert row['variation']==expected
        keys.append(expected['key']);scales.append(expected['scale']);angles.append(expected['yawDegrees'])
        for i in row['renderInstances']:
            actual=by_id[i['id']];assert actual==i
            generated,_=transform(i['matrix'],expected,i['variationBaseLinear'])
            assert np.allclose(generated,i['matrix'],rtol=0,atol=1e-12)
            base=np.asarray(i['variationBaseLinear']).reshape(3,3)
            varied=np.asarray(i['matrix']).reshape(3,4)[:,:3]
            # Uniform scale preserves all base angles and aspect ratios.
            assert np.allclose(varied.T@varied,base.T@base*expected['scale']**2,rtol=1e-12,atol=1e-12)
            assert np.linalg.det(varied)>0
    return dict(passed=True,plants=len(keys),uniqueKeys=len(set(keys)),seed=SEED,
        scaleMin=min(scales),scaleMax=max(scales),yawMinDegrees=min(angles),yawMaxDegrees=max(angles))
