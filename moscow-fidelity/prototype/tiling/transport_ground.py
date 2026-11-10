"""Keep ground solids out of newly enlarged, low bridge shoulders.

The full builder partitions land after constructing bridges. This incremental
release applies the same exclusion to the changed footprint and checks that
removing an old shoulder exposes existing ground instead of opening a hole.
"""
from pathlib import Path
import shutil,json,hashlib,gzip
from collections import defaultdict
from itertools import islice
import numpy as np
import shapely as sh
from build import plane,triangulate,parts
from curbs import LAND_RAISE,CURB_WIDTH
from partition_refinement import clip_triangle
from prepare_road_paint import read,world,write,interpolate
from prepare_foundations import digest
from check_structure_ground_delta import audit
from prepare_railway_entries import load_terrain

GROUND={'land','curb_top','curb_bottom','curb_front','curb_back'}

def surface_bounds(geometry):
    """Exact bounds of polygon exteriors, before constructing GEOS objects."""
    kind=geometry['type']
    if kind=='Polygon':rings=geometry['coordinates'][:1]
    elif kind=='MultiPolygon':rings=[p[0] for p in geometry['coordinates'] if p]
    else:return sh.geometry.shape(geometry).bounds
    points=[p for ring in rings for p in ring]
    if not points:return (np.nan,)*4
    return (min(p[0] for p in points),min(p[1] for p in points),
            max(p[0] for p in points),max(p[1] for p in points))

def nearby_surfaces(doc,relevant,cache=None):
    kinds={'land','curb_top','green_curb_top','roadbed_flat','roadbed_tunnel_descent','water'}
    key=dict(version=2,sourceSha256=digest(doc.path),
             regionSha256=hashlib.sha256(sh.to_wkb(relevant)).hexdigest()) if cache else None
    if cache and cache.exists():
        saved=json.loads(cache.read_text())
        if saved.get('key')==key:return saved['rows']
    tree=sh.STRtree(sh.get_parts(relevant));rows=[]
    iterator=(s for s in doc.items('surfaces') if s['kind'] in kinds)
    while batch:=list(islice(iterator,4096)):
        bounds=np.asarray([surface_bounds(s['geometry']) for s in batch])
        candidates=np.unique(tree.query(sh.box(*bounds.T))[0])
        for i in candidates:
            s=batch[int(i)]
            if len(tree.query(sh.geometry.shape(s['geometry']),predicate='intersects')):rows.append(s)
    if cache:cache.write_text(json.dumps(dict(key=key,rows=rows)))
    return rows

def exposed_curb(missing,roads,connections,nearby,precision=1e-5):
    """Use the actual curb rule, including open ground approaches.

    A road buffer alone includes pedestrian mouths where the complete builder
    deliberately leaves a clear passage. Removed deck footprint is outside all
    new decks, so only descent openings and the walking reserve can exclude
    curb here; remaining deck supports have already been excluded by delta.
    """
    from curbs import band
    from passage_space import walking_reserve
    openings=sh.union_all([sh.geometry.shape(s['geometry']) for s in nearby
                           if s['kind']=='roadbed_tunnel_descent']+
                          [walking_reserve(connections,precision)],grid_size=precision)
    return band(roads,openings,missing,precision)

def restore_land(region,features,dem,tree,*,allow_unrefined_green=False,curb=None):
    """Reapply the full builder's source-cover priority on exposed ground."""
    # Repeated initial refinements must not reuse the first repair's row IDs.
    namespace=hashlib.sha256(sh.to_wkb(sh.normalize(region))).hexdigest()[:16]
    candidates=[]
    for f in features:
        sem=f.get('semantics',{})
        if f.get('geometryType')!='polygon' or sem.get('kind')!='land' or sem.get('status')!='built':continue
        xyz=np.asarray(f['coordinates'])
        if len(xyz)<3:continue
        if not sh.box(*xyz[:,:2].min(0),*xyz[:,:2].max(0)).intersects(region):continue
        poly=sh.union_all([sh.Polygon(xyz[i:i+3,:2]) for i in range(len(xyz)-2)
                          if sh.Polygon(xyz[i:i+3,:2]).area>1e-9])
        if poly.intersects(region):candidates.append((f,poly))
    remaining=region;areas=[]
    for f,poly in sorted(candidates,key=lambda fp:(-fp[0]['semantics']['rank'],fp[1].area,fp[0]['id'])):
        area=remaining.intersection(poly)
        if area.area<1e-9:continue
        sem=f['semantics']
        assert allow_unrefined_green or sem['material']!=2,'Exposed greenery requires the full landscape repartition'
        areas.append((area,f['id'],sem['material'],dict(purpose=sem['purpose'],
            construction=sem['construction'],surfaceType=sem['surface'],styleId=sem['styleId'])))
        remaining=remaining.difference(poly)
    if remaining.area>1e-9:areas.append((remaining,'inferred:unclassified-land',8,{}))
    rows=[]
    for region,owner,material,metadata in areas:
        for i in sorted(tree.query(region,predicate='intersects')):
            p,c=dem[int(i)]
            patch=region.intersection(p)
            layers=[('land',material,patch)] if curb is None else [
                ('land',material,patch.difference(curb)),('curb_top',9,patch.intersection(curb))]
            for kind,mid,area in layers:
                for piece in parts(area):
                    if piece.area<1e-9:continue
                    rows.append(dict(id=f'surface:bridge-ground-restored:{namespace}:{len(rows)}',
                        geometry=sh.geometry.mapping(piece),heightPlane=(np.asarray(c)+[0,0,LAND_RAISE]).tolist(),
                        owner=owner,material=mid,kind=kind,tiers=[0],**metadata))
    return rows

def plan(base,profiles,doc,scan_cache=None,*,terrain=None,old_profiles=None,allow_unrefined_green=False,allow_initial_curbs=False):
    delta=audit(base,profiles,old=old_profiles,terrain=terrain)
    cut=sh.geometry.shape(delta['added']['groundContactGeometry'])
    removed=sh.geometry.shape(delta['removed']['groundContactGeometry'])
    relevant=sh.union_all([cut,removed])
    edits={};deleted=set();coverage=[];curb_loss=0.
    nearby=nearby_surfaces(doc,relevant.buffer(1) if allow_initial_curbs else relevant,scan_cache)
    for s in nearby:
        if s['kind']=='roadbed_tunnel_descent':continue
        p=sh.geometry.shape(s['geometry'])
        coverage.append(p)
        if s['kind']=='roadbed_flat':continue
        if s['kind']=='water':continue
        overlap=p.intersection(cut)
        if overlap.area<1e-9:continue
        if s['kind']=='curb_top':curb_loss+=overlap.area
        # A green partition needs its border/planting rebuild too. The normal
        # full construction pipeline already performs that after bridges.
        assert not s.get('landscapeRole') and s['kind']!='green_curb_top', \
            'Changed bridge reaches refined greenery; run landscape repartition before publishing'
        keep=sh.difference(p,cut,grid_size=1e-5)
        if keep.area<1e-9:deleted.add(s['id'])
        else:edits[s['id']]=dict(s,geometry=sh.geometry.mapping(keep))
    existing=sh.union_all(coverage)
    # Canonical grids can leave sub-millimetre edge residue, never an open
    # patch. Check the core as well as its area instead of ignoring a hole.
    holes=removed.difference(existing.buffer(.0001))
    restored=[];needed_curb=sh.Polygon()
    if holes.area>=1e-7:
        # Fill the exact missing patch; the tolerance is used only to identify
        # real holes, never to shrink their replacement geometry.
        missing=sh.union_all([p for p in parts(removed.difference(existing))
                             if p.intersection(holes).area>=1e-7]).difference(cut)
        # New road-side bands need the normal curb/landscape pass. A targeted
        # update must not silently replace one of those with plain paving.
        roads=sh.geometry.shape(doc.read('groundRoadGeometry'))
        needed_curb=exposed_curb(missing,roads,doc.read('gradeConnections'),nearby)
        if scan_cache:
            diagnostic=dict(delta=delta,missingGeometry=sh.geometry.mapping(missing),
                roadBufferOverlapM2=missing.intersection(roads.buffer(CURB_WIDTH)).area,
                neededCurbM2=needed_curb.area,neededCurbGeometry=sh.geometry.mapping(needed_curb),
                roadGeometry=sh.geometry.mapping(roads.intersection(missing.envelope.buffer(2))),
                originalCurbGeometry=sh.geometry.mapping(sh.union_all([sh.geometry.shape(s['geometry'])
                    for s in nearby if s['kind']=='curb_top'])))
            scan_cache.with_suffix('.decision.json').write_text(json.dumps(diagnostic))
        assert allow_initial_curbs or needed_curb.area<1e-8, \
            'Exposed ground reaches a road curb; run full land repartition'
        dem,demtree=terrain if terrain is not None else load_terrain(base)
        restored=restore_land(missing,doc.items('features'),dem,demtree,allow_unrefined_green=allow_unrefined_green,
                              curb=needed_curb if allow_initial_curbs else None)
    restored_domain=sh.union_all([sh.geometry.shape(r['geometry']) for r in restored])
    remaining_holes=holes.difference(restored_domain.buffer(.0001))
    assert remaining_holes.area<1e-7,('Removed concrete would expose a ground hole',remaining_holes.area)
    proof=dict(delta=delta,cutGeometry=sh.geometry.mapping(cut),
        clippedSurfaceIds=sorted(edits),removedSurfaceIds=sorted(deleted),
        removedCurbTopAreaM2=curb_loss,
        exposedGroundHoleBeforeM2=holes.area,exposedGroundHoleM2=remaining_holes.area,
        restoredGroundM2=restored_domain.area,restoredSurfaces=restored,xyToleranceM=.0001,
        policy='Changed low bridge footprints exclude raised ground; exposed land is rebuilt from source-cover priority and the unchanged terrain.')
    if allow_initial_curbs:
        old_curb=sh.union_all([sh.geometry.shape(s['geometry']) for s in nearby if s['kind']=='curb_top'],grid_size=1e-5)
        changed=sh.union_all([needed_curb,old_curb.intersection(cut)],grid_size=1e-5)
        side_region=changed.buffer(.05,join_style='mitre')
        combined=sh.union_all([old_curb.difference(cut),needed_curb],grid_size=1e-5)
        proof['curbRepair']=dict(addedTopM2=needed_curb.area,addedGeometry=sh.geometry.mapping(needed_curb),
            combinedGeometry=sh.geometry.mapping(combined),sideRegionGeometry=sh.geometry.mapping(side_region),
            policy='Restore curb tops/bottoms on the same terrain; replace sides around the joined canonical band, without an internal cap at the old/new seam.')
    return cut,edits,deleted,restored,proof

def initial_curb_faces(ground,restored,roads,dem,tree,extent):
    from curbs import solid_sides
    from build import z_at
    groups=defaultdict(list);repair=ground.get('curbRepair')
    if not repair:return groups,sh.Polygon()
    region=sh.geometry.shape(repair['sideRegionGeometry'])
    if region.is_empty:return groups,region
    band=sh.geometry.shape(repair['combinedGeometry'])
    solid_sides(band,roads,dem,tree,groups,z_at,extent,boundary_region=region)
    for s in restored:
        if s['kind']=='curb_top':
            groups[('curb_bottom',9)].extend(t[::-1] for t in triangulate(sh.geometry.shape(s['geometry']),np.asarray(s['heightPlane'])-[0,0,LAND_RAISE]))
    return groups,region

def triangle_words(faces,origin,material):
    ts=np.asarray(faces).reshape(-1,3,3)
    t=(ts-origin)[:,:,[0,2,1]]*[1,1,-1]
    n=np.cross(t[:,1]-t[:,0],t[:,2]-t[:,0]);n/=np.maximum(abs(n).sum(1,keepdims=True),1e-20)
    xy=n[:,:2].copy();mask=n[:,2]<0
    xy[mask]=(1-abs(xy[mask,::-1]))*np.where(xy[mask]>=0,1,-1)
    out=np.zeros((len(t),3,8),dtype='<u4');v=out.view('<f4')
    v[:,:,:3]=t;v[:,:,4:6]=t[:,:,[0,2]]
    out[:,:,3]=np.round(np.clip(xy,-1,1)*32767).astype('<i2').copy().view('<u4')
    out[:,:,6]=np.uint32(0x80000000|material)
    return out

def ground_words(words,origin,cut,restored):
    clipped=clip_mesh(words,origin,cut)
    if not restored:return clipped
    # Same packed vertex attributes as object_geometry.pack, without changing
    # any of the retained ground vertices.
    extra=[]
    for s in restored:
        ts=np.asarray(triangulate(sh.geometry.shape(s['geometry']),np.asarray(s['heightPlane'])))
        if not len(ts):continue
        extra.append(triangle_words(ts,origin,s['material']))
    return np.concatenate([words if clipped is None else clipped,*extra])

def clip_mesh(words,origin,cut):
    if cut.is_empty:return None
    xyz=world(words,origin);low=xyz[:,:,:2].min(1);high=xyz[:,:,:2].max(1)
    candidates=np.zeros(len(xyz),bool)
    for part in sh.get_parts(cut):
        x0,y0,x1,y1=part.bounds
        candidates|=(low[:,0]<=x1)&(high[:,0]>=x0)&(low[:,1]<=y1)&(high[:,1]>=y0)
    changed=False;kept=[];generated=[]
    for i in np.flatnonzero(candidates):
        t=xyz[i];p=sh.Polygon(t[:,:2])
        if p.area>1e-10:
            if p.intersection(cut).area<1e-10:continue
            faces=clip_triangle(t,cut,triangulate,plane)
            generated.extend(interpolate(words[i],face[:,:2],origin) for face in faces)
        else:
            line=sh.LineString(t[:,:2])
            if line.intersection(cut).length<1e-8:continue
            faces=clip_triangle(t,cut,triangulate,plane)
            # Vertical clipping: barycentrics in the original 3D triangle.
            for face in faces:
                basis=(t[1:]-t[0]).T
                uv=np.linalg.lstsq(basis,(face-t[0]).T,rcond=None)[0].T
                weights=np.column_stack([1-uv.sum(1),uv])
                out=np.repeat(words[i,:1],3,axis=0)
                out.view('<f4')[:,:3]=weights@words[i].view('<f4')[:,:3]
                out.view('<f4')[:,4:6]=weights@words[i].view('<f4')[:,4:6]
                generated.append(out)
        kept.append(i);changed=True
    if not changed:return None
    mask=np.ones(len(words),bool);mask[kept]=False
    return np.concatenate([words[mask],np.asarray(generated,dtype='<u4').reshape(-1,3,8)])

def append_words(source,destination,chunk,extra):
    """Append generated faces while retaining all old packed bytes and indices."""
    data=gzip.decompress(source.read_bytes());size=chunk['vertexBytes'];count=chunk['vertexCount']
    extra=np.asarray(extra,dtype='<u4').reshape(-1,8)
    indices=np.arange(count,count+len(extra),dtype='<u4')
    temporary=destination.with_suffix(destination.suffix+'.tmp')
    with gzip.GzipFile(filename=str(temporary),mode='wb',mtime=0,compresslevel=6) as f:
        f.write(data[:size]);f.write(extra.tobytes());f.write(data[size:]);f.write(indices.tobytes())
    temporary.replace(destination)
    points=extra.view('<f4')[:,:3]
    return dict(vertexBytes=size+extra.nbytes,vertexCount=count+len(extra),
        triangles=chunk['triangles']+len(extra)//3,bounds=dict(
            min=np.minimum(chunk['bounds']['min'],points.min(0)).tolist(),
            max=np.maximum(chunk['bounds']['max'],points.max(0)).tolist()))

def apply(base,out,scene,original_scene,origin,cut,restored,*,curb_faces=None,curb_side_region=None):
    changes=[]
    extras=defaultdict(list)
    for s in restored:
        extras[s['kind']].append(triangle_words(triangulate(sh.geometry.shape(s['geometry']),np.asarray(s['heightPlane'])),origin,s['material']))
    for (kind,material),faces in (curb_faces or {}).items():
        if len(faces):extras[kind].append(triangle_words(faces,origin,material))
    first={name:next(c['id'] for c in scene['chunks'] if c['name']==name) for name in extras}
    for c in scene['chunks']:
        if c['name'] not in GROUND:continue
        original=original_scene['chunks'][c['id']]
        local_cut=cut
        if c['name'] in ('curb_front','curb_back') and curb_side_region is not None:
            local_cut=sh.union_all([cut,curb_side_region])
        added=np.concatenate(extras[c['name']]) if first.get(c['name'])==c['id'] else None
        if local_cut.is_empty and added is None:continue
        path=Path(c['file']).name
        if local_cut.is_empty:
            changes.append(dict(id=c['id'],name=c['name'],reason='bridge-ground-partition',
                beforeSha256=digest(base/'canonical/full'/path)))
            c.update(append_words(base/'canonical/full'/path,out/'canonical/full'/path,original,added))
            print('BRIDGE GROUND APPENDED',c['id'],c['name'],len(added),flush=True)
            continue
        source=read(base,original);words=clip_mesh(source,origin,local_cut)
        if added is not None:words=np.concatenate([source if words is None else words,added])
        if words is None:
            if c!=original:
                shutil.copyfile(base/'canonical/full'/path,out/'canonical/full'/path)
                c.clear();c.update(original)
            continue
        changes.append(dict(id=c['id'],name=c['name'],reason='bridge-ground-partition',
            beforeSha256=digest(base/'canonical/full'/path)))
        c.update(write(out/'canonical/full'/path,words))
        print('BRIDGE GROUND CLIPPED',c['id'],c['name'],flush=True)
    return changes
