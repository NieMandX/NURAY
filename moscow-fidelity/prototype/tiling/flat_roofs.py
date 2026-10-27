"""Inset/extrude only inferred flat caps, before spatial tile cutting.

Source roof geometry and detailed models are authoritative. Every replacement
is computed from a complete source object, including courtyards and steps.
"""
import gzip,json
from pathlib import Path
from collections import defaultdict,Counter
import numpy as np
import shapely as sh
from shapely.geometry.polygon import orient

INSET=.4
DEPTH=.4
PARAPET_HEIGHT=1.0
RAISE=PARAPET_HEIGHT-DEPTH
# Source cap triangles can each have a slightly different constant height
# after coordinate conversion. Millimetre bins split one roof along its
# triangulation edges. Treat up to 1 cm as source precision, not a storey.
LEVEL_TOLERANCE=.01
POLICY=dict(version=3,insetM=INSET,depthM=DEPTH,parapetHeightM=PARAPET_HEIGHT,raiseM=RAISE,sourceLevelToleranceM=LEVEL_TOLERANCE,
 selection='ordinary house body without a source roof part or detailed model; horizontal generated caps only',
 shape='inset the full coplanar cap, preserving concavity and courtyard holes; rim and inner walls retain the original material',
 center='only the recessed horizontal face receives grey matte metal',
 fallback='retain caps too narrow for the inset, non-horizontal caps, and buildings cut by the acquisition boundary')
# Linear RGB: the approved soft matte-metal base darkened by 1.5, then 1.2.
# Keep the same metallic response and broad highlight shape.
MATERIAL=dict(name='Крыша · углублённая плоскость',family='recessed-flat-roof',color=[c/1.5/1.2 for c in (.224,.256,.280)],roughness=.68,metallic=.4,ior=1.5,kind=1,alphaCutoff=0,texture=None)
HOUSE_TYPES={'Administrative_house','Dwelling_house','Technical_house','School_house','Preschool_house','Private_house','New_house','Floor_plan_house','Momrah_building'}

def eligible_rows(rows,bounds):
    authoritative={r.get('sourceBuildingId') for r in rows if r['category']=='landmark' or '_roof_' in r.get('sourceLayer','')}
    result={};skips=Counter()
    for r in rows:
        layer=r.get('sourceLayer','');kind=layer.rsplit('_',1)[0]
        reason=None
        if r['category']!='building' or kind not in HOUSE_TYPES:reason='not-inferred-house-body'
        elif r.get('sourceBuildingId') in authoritative:reason='source-roof-or-detailed-model'
        elif r.get('flatRoof'):reason='already-inset'
        elif any(r['bounds']['min'][i]<bounds[i]+.001 or r['bounds']['max'][i]>bounds[i+2]-.001 for i in (0,1)):reason='acquisition-boundary'
        if reason:skips[reason]+=1
        else:result[r['id']]=r
    return result,skips

def parts(g):
    if g.geom_type=='Polygon':return [g]
    return [p for p in getattr(g,'geoms',[]) if p.geom_type=='Polygon']

def encode_faces(xyz,material):
    """New faces only; existing source normal/UV/tint words are never re-encoded."""
    xyz=np.asarray(xyz,dtype='<f4');n=np.cross(xyz[:,1]-xyz[:,0],xyz[:,2]-xyz[:,0])
    n=n/np.maximum(abs(n).sum(1,keepdims=True),1e-20);xy=n[:,:2].copy();neg=n[:,2]<0
    xy[neg]=(1-abs(xy[neg,::-1]))*np.where(xy[neg]>=0,1,-1)
    octn=np.round(np.clip(xy,-1,1)*32767).astype('<i2').copy().view('<u4').ravel()
    words=np.zeros((len(xyz),3,8),dtype='<u4');f=words.view('<f4');f[:,:,:3]=xyz
    f[:,:,4]=xyz[:,:,0];f[:,:,5]=xyz[:,:,2];words[:,:,3]=octn[:,None];words[:,:,6]=int(material)|0x80000000
    return words

def recessed_cap(words,center_material):
    xyz=words.view('<f4')[:,:,:3].astype(float)
    n=np.cross(xyz[:,1]-xyz[:,0],xyz[:,2]-xyz[:,0]);norm=np.linalg.norm(n,axis=1)
    flat=(abs(n[:,1])>norm*(1-1e-8))&(norm>1e-8)&(xyz[:,:,1].min(1)>xyz[:,:,1].min()+.8)
    # Each source triangle must still be horizontal; the tolerance between
    # triangles must never turn an actual sloping roof into a flat cap.
    flat &= np.ptp(xyz[:,:,1],axis=1)<.0005
    removed=np.zeros(len(words),bool);added=[];records=[]
    candidates=np.flatnonzero(flat)
    heights=xyz[candidates,:,1].mean(1)
    order=np.argsort(heights,kind='stable');candidates=candidates[order];heights=heights[order]
    # Gap-based grouping is independent of arbitrary rounding boundaries.
    # Reject an excessive chained drift as a whole, rather than processing
    # one fragment and introducing a parapet across the remaining roof.
    groups=np.split(candidates,np.flatnonzero(np.diff(heights)>LEVEL_TOLERANCE)+1)
    for indices in groups:
        if not len(indices) or np.ptp(xyz[indices,:,1])>LEVEL_TOLERANCE:continue
        mids=np.unique(words[indices,0,6]&0x7fffffff)
        if len(mids)!=1:continue
        mid=int(mids[0]);polygons=sh.polygons(xyz[indices][:,:,[0,2]])
        domain=sh.union_all(polygons)
        if not domain.is_valid:continue
        for polygon in parts(domain):
            inside=polygon.buffer(-INSET,join_style='mitre')
            if inside.is_empty or not inside.is_valid or inside.area<.1:continue
            indices_part=indices[sh.covered_by(sh.centroid(polygons),polygon)]
            if not len(indices_part):continue
            source=xyz[indices_part];h=float(source[:,:,1].mean())
            source_span=float(np.ptp(source[:,:,1]))
            if source_span>LEVEL_TOLERANCE:continue
            rim=polygon.difference(inside);top=[];center=[];walls=[]
            def horizontal(g,y,dest):
                for p in parts(g):
                    for tri in sh.constrained_delaunay_triangles(p).geoms:
                        a=np.array(tri.exterior.coords)[:3];t=np.column_stack((a[:,0],np.full(3,y),a[:,1]))
                        if np.cross(t[1]-t[0],t[2]-t[0])[1]<0:t=t[::-1]
                        dest.append(t)
            horizontal(rim,h+RAISE,top);horizontal(inside,h-DEPTH,center)
            for p in parts(inside):
                p=orient(p,sign=1)
                for ring in [p.exterior,*p.interiors]:
                    coords=list(ring.coords)
                    for a,b in zip(coords,coords[1:]):
                        ta=[a[0],h+RAISE,a[1]];tb=[b[0],h+RAISE,b[1]];ba=[a[0],h-DEPTH,a[1]];bb=[b[0],h-DEPTH,b[1]]
                        walls.extend([[ta,ba,bb],[ta,bb,tb]])
            outer=outer_extension(polygon,h,h+RAISE)
            assert abs(rim.area+inside.area-polygon.area)<max(1e-6,polygon.area*1e-9)
            added.extend([encode_faces(top,mid),encode_faces(center,center_material),encode_faces(walls,mid),encode_faces(outer,mid)])
            removed[indices_part]=True
            records.append(dict(heightM=h,sourceHeightSpanM=source_span,areaM2=polygon.area,centerAreaM2=inside.area,innerPerimeterM=inside.length,
                                wallAreaM2=inside.length*PARAPET_HEIGHT,outerWallAreaM2=polygon.length*RAISE,parapetHeightM=PARAPET_HEIGHT,raiseM=RAISE,centerTriangles=len(center),rimTriangles=len(top),wallTriangles=len(walls)+len(outer),
                                bounds=list(polygon.bounds)))
    return removed,np.concatenate(added) if added else np.empty((0,3,8),dtype='<u4'),records

def outer_extension(polygon,bottom,top):
    faces=[]
    for p in parts(polygon):
        p=orient(p,sign=1)
        for ring in [p.exterior,*p.interiors]:
            coords=list(ring.coords)
            for a,b in zip(coords,coords[1:]):
                ta=[a[0],top,a[1]];tb=[b[0],top,b[1]];ba=[a[0],bottom,a[1]];bb=[b[0],bottom,b[1]]
                faces.extend([[ta,bb,ba],[ta,tb,bb]])
    return faces

def raise_existing(words,patches,center_material,old_raise=0):
    """Upgrade already inset caps by provenance; retain the roof floor bit for bit.

    Boundaries come from the complete cap before tile cutting. Existing facade
    vertices never move: an outer extension closes the new 60 cm strip.
    """
    out=words.copy();xyz=out.view('<f4')[:,:,:3];mids=words[:,0,6]&0x7fffffff;extra=[]
    for patch in patches:
        h=patch['heightM'];old_top=h+old_raise;new_top=h+RAISE
        if abs(new_top-old_top)<1e-6:continue
        b=patch['bounds'];in_box=(xyz[:,:,0].min(1)>=b[0]-.001)&(xyz[:,:,0].max(1)<=b[2]+.001)&(xyz[:,:,2].min(1)>=b[1]-.001)&(xyz[:,:,2].max(1)<=b[3]+.001)
        floor=in_box&(mids==center_material)&(xyz[:,:,1]==np.float32(h-DEPTH)).all(1)
        rim=in_box&(mids!=center_material)&(xyz[:,:,1]==np.float32(old_top)).all(1)
        assert floor.any() and rim.any(),('missing complete cap',patch)
        inside=sh.union_all(sh.polygons(xyz[floor][:,:,[0,2]].astype(float)))
        domain=sh.union_all(sh.polygons(xyz[floor|rim][:,:,[0,2]].astype(float)))
        assert abs(domain.area-patch['areaM2'])<max(.02,domain.length*.001),(domain.area,patch,inside.area,int(rim.sum()))
        # Only the generated inner wall lies entirely on the inner boundary
        # and has both its bottom and top at these two known levels.
        wall=in_box&(mids!=center_material)&(xyz[:,:,1].min(1)==np.float32(h-DEPTH))&(xyz[:,:,1].max(1)==np.float32(old_top))
        ids=np.flatnonzero(wall)
        if len(ids):
            boundary=sh.distance(sh.points(xyz[ids][:,:,[0,2]].reshape(-1,2)),inside.boundary).reshape(-1,3)
            wall[ids]=boundary.max(1)<.001
        assert wall.any()
        move=(rim|wall)[:,None]&(xyz[:,:,1]==np.float32(old_top));xyz[:,:,1][move]=new_top
        mid=int(np.bincount(mids[rim].astype(int)).argmax())
        extra.append(encode_faces(outer_extension(domain,old_top,new_top),mid))
        assert np.array_equal(out[floor],words[floor])
    return np.concatenate([out,*extra]) if extra else out

def read_faces(folder,c):
    data=gzip.decompress((folder/Path(c['file']).name).read_bytes());u=np.frombuffer(data[:c['vertexBytes']],'<u4').reshape(-1,8)
    ix=np.frombuffer(data[c['vertexBytes']:],'<u4').reshape(-1,3)
    return u[ix]

def store_faces(folder,c,faces,owners):
    vertices,ix=np.unique(faces.reshape(-1,8),axis=0,return_inverse=True);ix=ix.astype('<u4')
    raw=vertices.tobytes()+ix.tobytes();(folder/Path(c['file']).name).write_bytes(gzip.compress(raw,compresslevel=6,mtime=0))
    p=faces.view('<f4')[:,:,:3];ranges=[];first=0
    for owner,count in owners:
        if not count:continue
        if ranges and ranges[-1]['id']==owner:ranges[-1]['count']+=count
        else:ranges.append(dict(id=owner,first=first,count=count))
        first+=count
    assert first==len(faces)
    c.update(vertexCount=len(vertices),vertexBytes=vertices.nbytes,triangles=len(faces),
             bounds=dict(min=p.min((0,1)).tolist(),max=p.max((0,1)).tolist()),sourceObjectRanges=ranges,
             sourceObjectIds=sorted({r['id'] for r in ranges}))

def install(rows,scene,folder,bounds):
    eligible,skips=eligible_rows(rows,bounds);chunks=[c for c in scene['chunks'] if c.get('category')=='building']
    faces={c['id']:read_faces(folder,c) for c in chunks};by_object=defaultdict(list)
    for c in chunks:
        for r in c.get('sourceObjectRanges',[]):
            if r['id'] in eligible:by_object[r['id']].append((c['id'],r['first'],r['count']))
    material=len(scene['materials']);changes={};updates=[];records=[]
    for owner,ranges in by_object.items():
        words=np.concatenate([faces[c][i:i+n] for c,i,n in ranges]);remove,add,patches=recessed_cap(words,material)
        if not len(add):skips['no-safe-flat-inset']+=1;continue
        offset=0
        for j,(c,i,n) in enumerate(ranges):
            changes[(c,i)]=(remove[offset:offset+n],add if j==0 else add[:0]);offset+=n
        row=dict(id=owner,retainedTriangles=int(len(words)-remove.sum()+len(add)),flatRoof=dict(**POLICY,patches=patches))
        updates.append(row);records.append(dict(id=owner,removedTriangles=int(remove.sum()),addedTriangles=len(add),patches=patches))
    changed=[]
    for c in chunks:
        if not any((c['id'],r['first']) in changes for r in c['sourceObjectRanges']):continue
        output=[];owners=[]
        for r in c['sourceObjectRanges']:
            data=faces[c['id']][r['first']:r['first']+r['count']];change=changes.get((c['id'],r['first']))
            if change is not None:
                remove,add=change;data=np.concatenate([data[~remove],add])
            output.append(data);owners.append((r['id'],len(data)))
        store_faces(folder,c,np.concatenate(output),owners);changed.append(c['id'])
    if records:scene['materials'].append(dict(MATERIAL))
    by_id={u['id']:u for u in updates}
    for r in rows:
        update=by_id.get(r['id'])
        if update:r.update(update)
    return dict(policy=POLICY,changedChunks=changed,buildings=updates,records=records,
                stats=dict(buildings=len(updates),caps=sum(len(r['patches']) for r in records),
                           removedTriangles=sum(r['removedTriangles'] for r in records),addedTriangles=sum(r['addedTriangles'] for r in records),skipped=dict(skips)))
