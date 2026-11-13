"""Use existing approved plant roots/rotations/scales; never invent map positions."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import numpy as np


def transform_key(source_type, matrix):
    """Match the exact Float32 transform serialized by the merged exporter."""
    return source_type, np.asarray(matrix, dtype='<f4').reshape(12).tobytes()


def main():
    p=argparse.ArgumentParser()
    p.add_argument('scene',type=Path)
    p.add_argument('output',type=Path)
    p.add_argument('--model',default='broadleaf')
    p.add_argument('--source-type',default='nuray-approved-open')
    p.add_argument('--map',action='append',default=[],help='Repeat source-type=model-name')
    p.add_argument('--radius',type=float,default=600)
    p.add_argument('--appearance-overrides',type=Path,help='Accepted infill records; only these exact instances get new appearances')
    args=p.parse_args()
    mapping=dict(item.split('=',1) for item in args.map) if args.map else {args.source_type:args.model}
    overrides={}
    if args.appearance_overrides:
        for r in json.loads(args.appearance_overrides.read_text())['records']:
            if r['status']!='accepted':continue
            key=transform_key('nuray-approved-'+r['model'],r['matrix'])
            if key in overrides:raise ValueError('Duplicate appearance override transform')
            overrides[key]=r['appearance']
    names=list(dict.fromkeys([*mapping.values(),*overrides.values()]))
    models={name:json.loads((args.output/(name+'.json')).read_text()) for name in names}
    with args.scene.open('rb') as f:
        f.seek(12);size,typ=struct.unpack('<II',f.read(8));header=f.read(size);doc=json.loads(header);base=20+size+8
        meta=doc['extras']['nuray']
        def read(view):
            v=doc['bufferViews'][view];f.seek(base+v['byteOffset']);return f.read(v['byteLength'])
        transforms=np.frombuffer(read(meta['transformsView']),'<f4').reshape(-1,12)
        source_types=set(mapping)|{k[0] for k in overrides}
        draws=[d for d in meta['draws'] if d['name'] in source_types and d['instanced']]
        if {d['name'] for d in draws}!=source_types:raise ValueError('Source plant type not found')
        instances=[];dimensions=[]
        matched=set()
        for d in draws:
            vertices=np.frombuffer(read(d['vertexView']),'<f4').reshape(-1,8)[:,:3]
            lo=vertices.min(0);hi=vertices.max(0);span=hi-lo
            # Approved templates have their planting anchor at local Y=0.
            # Some roots extend below it; this buried portion must not lower
            # the normalized splat's base or increase its above-ground height.
            if hi[1]<=0:raise ValueError('Plant has no height above its root anchor')
            span[1]=hi[1]
            dimensions.append({'source':d['name'],'min':lo.tolist(),'max':hi.tolist()})
            for i in range(d['instanceFirst'],d['instanceFirst']+d['instanceCount']):
                src=transforms[i].reshape(3,4).astype(float)
                key=transform_key(d['name'],src)
                name=overrides.get(key,mapping.get(d['name']))
                if key in overrides:matched.add(key)
                if not name or np.hypot(src[0,3],src[2,3])>args.radius:continue
                model=models[name];model_id=names.index(name)
                splat_span=np.array(model['bounds']['max'])-np.array(model['bounds']['min'])
                fit=span/splat_span
                m=src.copy();m[:,:3]*=fit[None,:]
                # Both templates are root-centred; keep the actual source root.
                instances.append({'sourceInstance':i,'sourceDraw':d['id'],'sourceType':d['name'],'model':model_id,'matrix':m.flatten().tolist()})
        if matched!=set(overrides):raise ValueError('Appearance overrides do not match this GLB')
    result={'format':'nuray-vegetation-splats-v1','sourceHeaderSha256':hashlib.sha256(header).hexdigest(),
            'models':[name+'.json' for name in names],'instances':instances,'scope':{'center':[0,0],'radiusM':args.radius},
            'fit':dimensions,'placement':'existing approved instance XY, root height, yaw and scale; template fitted to source dimensions',
            'limitations':['generated appearance, not a measured individual tree','baked SH0 colour','mesh proxies retained for shadows, reflections and ray tracing']}
    (args.output/'vegetation.json').write_text(json.dumps(result,ensure_ascii=False,separators=(',',':'))+'\n')
    print(json.dumps({'instances':len(instances),'fit':dimensions,'header':result['sourceHeaderSha256']}))


if __name__=='__main__':main()
