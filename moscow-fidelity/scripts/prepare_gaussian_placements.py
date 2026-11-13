"""Use existing approved plant roots/rotations/scales; never invent map positions."""
import argparse
import hashlib
import gzip
import json
from pathlib import Path
import struct
import numpy as np


def transform_key(source_type, matrix):
    """Match the exact Float32 transform serialized by the merged exporter."""
    return source_type, np.asarray(matrix, dtype='<f4').reshape(12).tobytes()


def variant_for(key, names):
    """Stable under draw ordering: source type and original planting transform."""
    digest=hashlib.blake2b(key[0].encode()+key[1],digest_size=8).digest()
    return names[int.from_bytes(digest,'little')%len(names)]


def canopy_limiter(mask_path, origin):
    import shapely as sh
    masks=json.loads(gzip.decompress(mask_path.read_bytes()))
    building_shapes=[sh.from_wkb(bytes.fromhex(g)) for g,h in masks['buildings']]
    heights=np.array([h for g,h in masks['buildings']]);tree=sh.STRtree(building_shapes)
    surfaces=sh.union_all([sh.from_wkb(bytes.fromhex(v)) for k,v in masks['root'].items() if k!='building'])
    sh.prepare(surfaces)
    def factor(source_type, src, requested):
        kind=source_type.removeprefix('nuray-approved-')
        radius,bottom=masks['crowns'][kind]
        radius*=max(np.linalg.norm(src[:,0]),np.linalg.norm(src[:,2]))
        bottom=src[1,3]+origin+bottom*np.linalg.norm(src[:,1])
        p=sh.Point(src[0,3],-src[2,3])
        def fits(value):
            footprint=p.buffer(radius*value,quad_segs=12)
            near=tree.query(footprint,predicate='intersects')
            if len(near) and np.any(heights[near]>bottom):return False
            if bottom-src[1,3]-origin<2.5 and surfaces.intersects(footprint):return False
            return True
        if fits(requested):return requested
        # Preserve approved existing placements; only limit the added width.
        lo,hi=1.,requested
        for _ in range(12):
            mid=(lo+hi)/2
            if fits(mid):lo=mid
            else:hi=mid
        return lo
    return factor


def main():
    p=argparse.ArgumentParser()
    p.add_argument('scene',type=Path)
    p.add_argument('output',type=Path)
    p.add_argument('--model',default='broadleaf')
    p.add_argument('--source-type',default='nuray-approved-open')
    p.add_argument('--map',action='append',default=[],help='Repeat source-type=model-name[,variant-name]')
    p.add_argument('--radius',type=float,default=600)
    p.add_argument('--canopy-width',type=float,default=1.,help='Width factor for mature broadleaf crowns; height and root stay fixed')
    p.add_argument('--placement-masks',type=Path,help='Required to widen canopies without adding building/low-crown collisions')
    p.add_argument('--scene-origin-height',type=float)
    p.add_argument('--full-scene',action='store_true',help='Replace every plant, validating complete source-type coverage')
    p.add_argument('--appearance-overrides',type=Path,help='Accepted infill records; only these exact instances get new appearances')
    args=p.parse_args()
    mapping=dict(item.split('=',1) for item in args.map) if args.map else {args.source_type:args.model}
    if args.canopy_width<1 or args.canopy_width>2:raise ValueError('Canopy width must be between 1 and 2')
    if args.canopy_width>1 and (not args.placement_masks or args.scene_origin_height is None):raise ValueError('Wider canopies require placement masks and origin height')
    limit_width=canopy_limiter(args.placement_masks,args.scene_origin_height) if args.canopy_width>1 else None
    widths=[]
    overrides={}
    if args.appearance_overrides:
        for r in json.loads(args.appearance_overrides.read_text())['records']:
            if r['status']!='accepted':continue
            key=transform_key('nuray-approved-'+r['model'],r['matrix'])
            if key in overrides:raise ValueError('Duplicate appearance override transform')
            overrides[key]=r['appearance']
    variants={kind:value.split(',') for kind,value in mapping.items()}
    names=list(dict.fromkeys([*(name for choices in variants.values() for name in choices),*overrides.values()]))
    models={name:json.loads((args.output/(name+'.json')).read_text()) for name in names}
    with args.scene.open('rb') as f:
        f.seek(12);size,typ=struct.unpack('<II',f.read(8));header=f.read(size);doc=json.loads(header);base=20+size+8
        meta=doc['extras']['nuray']
        def read(view):
            v=doc['bufferViews'][view];f.seek(base+v['byteOffset']);return f.read(v['byteLength'])
        transforms=np.frombuffer(read(meta['transformsView']),'<f4').reshape(-1,12)
        source_types=set(mapping)|{k[0] for k in overrides}
        draws=[d for d in meta['draws'] if d['name'] in source_types and d['instanced']]
        all_plants=[d for d in meta['draws'] if d['name'].startswith('nuray-approved-') and d['instanced']]
        if args.full_scene and {d['id'] for d in draws}!={d['id'] for d in all_plants}:
            raise ValueError('Full-scene mapping must cover every plant type')
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
                name=overrides.get(key)
                if name is None and d['name'] in variants:name=variant_for(key,variants[d['name']])
                if key in overrides:matched.add(key)
                if not name or (not args.full_scene and np.hypot(src[0,3],src[2,3])>args.radius):continue
                model=models[name];model_id=names.index(name)
                splat_span=np.array(model['bounds']['max'])-np.array(model['bounds']['min'])
                fit=span/splat_span
                width=limit_width(d['name'],src,args.canopy_width) if limit_width and d['name'] in ('nuray-approved-open','nuray-approved-compact') else 1.
                fit[[0,2]]*=width
                if d['name'] in ('nuray-approved-open','nuray-approved-compact'):widths.append(width)
                m=src.copy();m[:,:3]*=fit[None,:]
                # Both templates are root-centred; keep the actual source root.
                instances.append({'sourceInstance':i,'sourceDraw':d['id'],'sourceType':d['name'],'model':model_id,'matrix':m.flatten().tolist()})
        if matched!=set(overrides):raise ValueError('Appearance overrides do not match this GLB')
    result={'format':'nuray-vegetation-splats-v1','sourceHeaderSha256':hashlib.sha256(header).hexdigest(),
            'models':[name+'.json' for name in names],'instances':instances,'scope':{'center':[0,0],'radiusM':None if args.full_scene else args.radius,'fullScene':args.full_scene},
            'coverage':{'sourcePlants':sum(d['instanceCount'] for d in all_plants),'replacements':len(instances),'complete':len(instances)==sum(d['instanceCount'] for d in all_plants)},
            'canopyWidth':{'requested':args.canopy_width,'fullWidth':sum(w>=args.canopy_width-1e-6 for w in widths),'limited':sum(w<args.canopy_width-1e-6 for w in widths),'totalMatureBroadleaf':len(widths),'policy':'Limit added width at buildings and low-crown surface conflicts; preserve roots and height'},
            'fit':dimensions,'placement':'existing approved instance XY, root height, yaw and scale; template fitted to source dimensions',
            'variants':variants,'limitations':['generated appearance, not a measured individual tree','baked SH0 colour','mesh proxies retained for solar shadows; legacy non-Gaussian renderers still use meshes']}
    (args.output/'vegetation.json').write_text(json.dumps(result,ensure_ascii=False,separators=(',',':'))+'\n')
    print(json.dumps({'instances':len(instances),'coverage':{'sourcePlants':sum(d['instanceCount'] for d in all_plants),'replacements':len(instances),'complete':len(instances)==sum(d['instanceCount'] for d in all_plants)},
            'fit':dimensions,'header':result['sourceHeaderSha256']}))


if __name__=='__main__':main()
