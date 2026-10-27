"""Repartition planting when source-confirmed transport reservations expand.

Use the same raised-green/inset-curb rules as the full builder. Unaffected
source cells and packed vertices retain their original representation.
"""
import copy
import json
from pathlib import Path
import numpy as np
import shapely as sh
from landscape import physical_green,area_only,GREEN_CURB_WIDTH,GREEN_RAISE,split_cell,sides
from railway_landscape import railway_reserve
from spatial_mask import SpatialMask
from build import triangulate,z_at
from transport_ground import clip_mesh
from prepare_road_paint import read,write
from prepare_foundations import digest

POLICY='Recompute raised planting, inset curbs and ground-height rail aprons whenever confirmed railway reservations expand.'

def layout(before,reserve,extent,precision=1e-5):
    old_reserve=sh.geometry.shape(before['railApronGeometry'])
    old_raised=sh.geometry.shape(before['raisedGeometry'])
    old_band=sh.geometry.shape(before['curbGeometry'])
    extra=area_only(reserve.difference(old_reserve),precision)
    components=[p for p in sh.get_parts(old_raised) if p.intersection(extra).area>1e-9]
    affected=sh.union_all(components)
    cut=area_only(affected.intersection(reserve),precision)
    # The margin contains both the old and new inset band, not an arbitrary
    # road-width guess. It never creates a border at the patch perimeter.
    patch=area_only(extra.intersection(affected.buffer(GREEN_CURB_WIDTH*2+.01))
                    .buffer(GREEN_CURB_WIDTH*2+.01,join_style='mitre'),precision)
    replacement=physical_green(area_only(affected.difference(reserve),precision),precision)
    band=area_only(replacement.difference(replacement.buffer(-GREEN_CURB_WIDTH,join_style='mitre',mitre_limit=2)),precision)
    band=physical_green(band.difference(extent.boundary.buffer(GREEN_CURB_WIDTH+precision*5)),precision)
    # Rebuffering a kilometre-scale component can re-node an existing grid
    # edge by one grid step. Retain the original geometry outside this patch,
    # and reject any resolved change there rather than accumulating its area.
    remote=old_band.intersection(affected).symmetric_difference(band).difference(patch.buffer(.00005))
    assert remote.buffer(-precision).is_empty
    raised=area_only(sh.union_all([old_raised.difference(patch),replacement.intersection(patch)]),precision)
    band=area_only(sh.union_all([old_band.difference(patch),band.intersection(patch)]),precision)
    result=dict(raised=raised,band=band,cut=reserve,precision=precision,
                railApron=reserve,railApronMask=SpatialMask(reserve),
                cutMask=SpatialMask(reserve),raisedMask=SpatialMask(raised),bandMask=SpatialMask(band))
    return result,patch,cut

def row_bounds(s):
    g=s['geometry'];rings=[g['coordinates'][0]] if g['type']=='Polygon' else [p[0] for p in g['coordinates']]
    xs=[p[0] for ring in rings for p in ring];ys=[p[1] for ring in rings for p in ring]
    return min(xs),min(ys),max(xs),max(ys)

def partition(rows,plan,patch,material_map,owners):
    removed=set();result=[];mask=[];bounds=patch.bounds
    if patch.is_empty:return removed,result,sh.Polygon()
    for s in rows:
        if s.get('landscapeRole') not in ('green','curb'):continue
        x0,y0,x1,y1=row_bounds(s)
        if x1<bounds[0] or x0>bounds[2] or y1<bounds[1] or y0>bounds[3]:continue
        p=sh.geometry.shape(s['geometry'])
        if p.intersection(patch).area<1e-10:continue
        removed.add(s['id']);mask.append(p)
        base=np.asarray(s['heightPlane'])-[0,0,GREEN_RAISE]
        for role,g,c in split_cell(p,base,plan):
            for piece in sh.get_parts(g):
                if piece.area<1e-9:continue
                material=material_map[owners[s['owner']]['layer']] if role=='green' else 9 if role=='curb' else plan['railMaterial']
                row=dict(s,id=f"{s['id']}:transport-reserve:{role}:{len(result)}",
                         geometry=sh.geometry.mapping(piece),heightPlane=c.tolist(),
                         material=material,kind='green_curb_top' if role=='curb' else 'land',
                         landscapeRole=role,
                         purpose='vegetation-cover' if role=='green' else 'green-border' if role=='curb' else 'railway',
                         surfaceType='vegetation' if role=='green' else 'concrete' if role=='curb' else 'dark-concrete')
                assert role in ('green','curb','railway_apron')
                result.append(row)
    return removed,result,area_only(sh.union_all(mask),1e-5)

def plan(doc,interfaces,dem,tree):
    before=doc.read('landscape');features=doc.read('features');bounds=doc.read('boundsMSK');extent=sh.box(*bounds)
    reserve=railway_reserve(dict(features=features,roadInterfaces=interfaces,boundsMSK=bounds))
    current,patch,lowered=layout(before,reserve,extent)
    current['railMaterial']=before['railApronMaterial']
    removed,rows,mask=partition(doc.items('surfaces'),current,patch,before['materials'],{f['id']:f for f in features})
    # A source plant on newly lowered ground requires a placement rebuild.
    for obj in doc.read('objectLayer').get('vegetation',[]):
        assert not lowered.covers(sh.Point(obj['position'][:2])),('Plant occupies a new rail approach',obj['id'])
    after=copy.deepcopy(before)
    after.update(raisedGeometry=sh.geometry.mapping(current['raised']),
                 curbGeometry=sh.geometry.mapping(current['band']),
                 railApronGeometry=sh.geometry.mapping(reserve),
                 raisedAreaM2=current['raised'].area,curbTopAreaM2=current['band'].area,
                 reservedAreaM2=before['reservedAreaM2']+lowered.area,
                 convertedGeometry=sh.geometry.mapping(sh.union_all([sh.geometry.shape(before['convertedGeometry']),lowered])),
                 transportReservePolicy=POLICY)
    side_faces=sides(current,dem,tree,extent,triangulate,z_at,region=patch)
    proof=dict(policy=POLICY,removedSurfaceIds=sorted(removed),surfaceMask=sh.geometry.mapping(mask),
               sideMask=sh.geometry.mapping(patch),loweredAreaM2=lowered.area,newSurfaces=rows)
    return after,proof,side_faces

def face_words(ts,material,origin):
    if not len(ts):return np.empty((0,3,8),dtype='<u4')
    xyz=(np.asarray(ts)-origin)[:,:,[0,2,1]]*[1,1,-1]
    n=np.cross(xyz[:,1]-xyz[:,0],xyz[:,2]-xyz[:,0]);size=np.linalg.norm(n,axis=1)
    keep=size>1e-9;xyz=xyz[keep];n=n[keep]
    n/=np.maximum(abs(n).sum(1,keepdims=True),1e-20)
    xy=n[:,:2].copy();negative=n[:,2]<0
    xy[negative]=(1-abs(xy[negative,::-1]))*np.where(xy[negative]>=0,1,-1)
    out=np.zeros((len(xyz),3,8),dtype='<u4');v=out.view('<f4')
    v[:,:,:3]=xyz;v[:,:,4:6]=xyz[:,:,[0,2]]
    out[:,:,3]=np.round(np.clip(xy,-1,1)*32767).astype('<i2').copy().view('<u4')
    out[:,:,6]=np.uint32(0x80000000|material)
    return out

def generated(proof,side_faces,origin):
    groups={}
    for row in proof['newSurfaces']:
        name={'green':'land','curb':'green_curb_top','railway_apron':'railway_apron'}[row['landscapeRole']]
        faces=triangulate(sh.geometry.shape(row['geometry']),np.asarray(row['heightPlane']))
        groups.setdefault(name,[]).append(face_words(faces,row['material'],origin))
    groups['green_curb_side']=[face_words(side_faces,9,origin)]
    return {k:np.concatenate(v) for k,v in groups.items()}

def rebuilt_words(words,name,proof,green_materials,extra,origin):
    selection=np.isin(words[:,0,6]&0x7fffffff,list(green_materials)) if name=='land' else np.ones(len(words),bool)
    if name=='railway_apron':selection[:]=False
    cut=sh.geometry.shape(proof['sideMask' if name=='green_curb_side' else 'surfaceMask'])
    clipped=clip_mesh(words[selection],origin,cut) if selection.any() else None
    if clipped is None and not len(extra):return None
    kept=words if clipped is None else np.concatenate([words[~selection],clipped])
    return np.concatenate([kept,extra])

def apply(base,out,scene,before_scene,proof,side_faces,landscape,origin):
    extra=generated(proof,side_faces,origin);changes=[]
    green=set(landscape['materials'].values())
    # Use an existing vegetation-only land chunk for regenerated foliage cover.
    targets={}
    for c in before_scene['chunks']:
        if c['name'] not in extra:continue
        if c['name']=='land':
            words=read(base,c)
            if not np.isin(words[:,0,6]&0x7fffffff,list(green)).all():continue
        targets.setdefault(c['name'],c['id'])
    assert set(targets)==set(extra)
    for c in scene['chunks']:
        if c['name'] not in extra:continue
        old=before_scene['chunks'][c['id']]
        additions=extra[c['name']] if targets[c['name']]==c['id'] else np.empty((0,3,8),dtype='<u4')
        words=rebuilt_words(read(base,old),c['name'],proof,green,additions,origin)
        if words is None:continue
        if c!=old:
            assert np.array_equal(read(out,c),words),'Planting repartition overlaps another mesh refinement'
        path=Path(c['file']).name
        changes.append(dict(id=c['id'],name=c['name'],reason='railway-planting-reservation',
                            beforeSha256=digest(base/'canonical/full'/path)))
        c.update(write(out/'canonical/full'/path,words))
        print('RAIL PLANTING REPARTITION',c['id'],c['name'],flush=True)
    proof['targetChunks']=targets
    return changes
