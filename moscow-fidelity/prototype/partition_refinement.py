"""Apply newly resolved road seams consistently to horizontal and curb solids."""
import numpy as np
import shapely as sh
from road_seams import reconcile
from curbs import band,solid_sides,CURB_MATERIAL
from spatial_mask import SpatialMask

def clip_triangle(triangle,cut,triangulate,plane):
    t=np.asarray(triangle)
    # SpatialMask returns an empty local cut for distant faces. Preserve those
    # exact vertices instead of rebuilding every water triangle in the region.
    if cut.is_empty:return [t]
    xy=t[:,:2];cross=np.cross(t[1]-t[0],t[2]-t[0])
    p=sh.Polygon(xy)
    if p.area>1e-12:
        faces=triangulate(p.difference(cut),plane(t))
        return [face[::-1] for face in faces] if cross[2]<0 else faces
    # Vertical curb faces require clipping in their own (distance,height)
    # plane; their XY projection is a line, not an areal triangle.
    pairs=[(a,b) for a in range(3) for b in range(a+1,3)]
    a,c=max(pairs,key=lambda pair:np.linalg.norm(xy[pair[1]]-xy[pair[0]]))
    length=np.linalg.norm(xy[c]-xy[a])
    if length<1e-10:return [t]
    axis=(xy[c]-xy[a])/length;line=sh.LineString([xy[a],xy[c]])
    allowed=line.difference(cut);pieces=[]
    def collect(g):
        if g.is_empty:return
        if g.geom_type=='LineString':pieces.append(g)
        else:
            for part in getattr(g,'geoms',[]):collect(part)
    collect(allowed);out=[]
    for piece in pieces:
        values=(np.asarray(piece.coords)-xy[a])@axis;lo,hi=values.min(),values.max();ring=list(t)
        for limit,sign in [(lo,1),(hi,-1)]:
            clipped=[]
            for i,u in enumerate(ring):
                v=ring[(i+1)%len(ring)];du=((u[:2]-xy[a])@axis-limit)*sign;dv=((v[:2]-xy[a])@axis-limit)*sign
                if du>=0:clipped.append(u)
                if (du>=0)!=(dv>=0):clipped.append(u+(v-u)*du/(du-dv))
            ring=clipped
            if len(ring)<3:break
        for i in range(1,len(ring)-1):
            face=np.array([ring[0],ring[i],ring[i+1]])
            if np.linalg.norm(np.cross(face[1]-face[0],face[2]-face[0]))>1e-12:out.append(face)
    return out

def refine(b,opening,road,candidates,extra_ground_cut=None):
    all_repairs=[]
    for iteration in range(3):
        updated,repairs,audit=reconcile(road,candidates,b.records,b.EXTENT,b.GRID)
        if not repairs:break
        all_repairs.extend(repairs);road=updated
    else:raise ValueError('Road seam refinement did not converge')
    b.road_seam_report.update(remainingRepairableSeams=len(repairs),remainingRepairableAreaM2=sum(r['areaM2'] for r in repairs))
    cut=b.union([sh.geometry.shape(r['geometry']) for r in all_repairs]+([] if extra_ground_cut is None else [extra_ground_cut]))
    from passage_space import walking_reserve
    new_band=band(road,b.union([opening,b.transition_cut,walking_reserve(b.grade_connections,b.GRID)]),b.EXTENT,b.GRID)
    band_change=new_band.symmetric_difference(b.curb_band)
    if cut.is_empty and band_change.is_empty:return road
    print('PARTITION REFINEMENT',len(all_repairs),'road area',cut.area,'curb area',band_change.area,flush=True)
    land=[s for s in b.surfaces if s['kind'] in ('land','curb_top')]
    tree=sh.STRtree([s['poly'] for s in land])
    changed=cut.union(band_change)
    # Disconnected tiny changes can have a district-wide bounding box. Query
    # each component, not every terrain cell inside that combined envelope.
    affected_ids=set()
    for part in b.parts(changed):affected_ids.update(map(int,tree.query(part,predicate='intersects')))
    affected_rows=[land[i] for i in sorted(affected_ids)]
    print('PARTITION AFFECTED CELLS',len(affected_rows),flush=True)
    # A structural delta can affect water only (handled by its caller), or
    # repeat an already empty ground cut. No land, road or curb solid changed.
    if not affected_rows and not all_repairs and band_change.is_empty:return road
    # Repartition whole intersected height cells. This also creates curb tops
    # along the new outer edge at an open seam's end, rather than merely
    # deleting the old interior curb faces.
    replaced=b.union([s['poly'] for s in affected_rows])
    cut_bounds=np.array([p.bounds for p in b.parts(replaced)])
    for key in list(b.groups):
        kind,material=key
        if kind not in ('land','curb_top','curb_bottom'):continue
        faces=b.groups[key]
        if not faces:continue
        array=np.asarray(faces);minimum=array[:,:,:2].min(1);maximum=array[:,:,:2].max(1);affected=np.zeros(len(array),dtype=bool)
        for x0,y0,x1,y1 in cut_bounds:
            affected|=(minimum[:,0]<=x1)&(maximum[:,0]>=x0)&(minimum[:,1]<=y1)&(maximum[:,1]>=y0)
        flags=b.shading_flags.get(key,[]);out=[];newflags=[]
        for i,t in enumerate(faces):
            pieces=clip_triangle(t,replaced,b.triangulate,b.plane) if affected[i] else [t]
            out.extend(pieces)
            if flags:newflags.extend([flags[i]]*len(pieces))
        b.groups[key]=out
        if flags:b.shading_flags[key]=newflags
    materials={r['id']:r['material'] for r in candidates if r['kind']=='land'}
    removed_ids={s['id'] for s in affected_rows}
    band_mask=SpatialMask(new_band)
    for index,s in enumerate(affected_rows):
        retained=s['poly'].difference(cut)
        nearby_band=band_mask.near(retained)
        material=s['material'] if s['kind']=='land' else materials.get(s['owner'],8 if s['owner'].startswith('inferred:') else 1)
        b.add_surface(retained.difference(nearby_band),s['plane'],s['owner'],material,'land',s['tiers'])
        top=retained.intersection(nearby_band)
        b.add_surface(top,s['plane'],s['owner'],CURB_MATERIAL,'curb_top',s['tiers'])
        b.groups[('curb_bottom',CURB_MATERIAL)].extend(t[::-1] for t in b.triangulate(top,s['plane']-[0,0,.1]))
        s['poly']=sh.Polygon()
        if index and index%500==0:print('PARTITION CELLS',index,'/',len(affected_rows),flush=True)
    b.relationships[:]=[r for r in b.relationships if not any(r.get(key) in removed_ids for key in ('a','b','parent'))]
    for repair in all_repairs:
        owner=f'inferred:road-slit:{len(b.slit_repairs)}';b.slit_repairs.append(repair)
        b.lift(sh.geometry.shape(repair['geometry']),np.zeros(3),owner,0,'roadbed_flat',repair.get('tiers',[0]))
        b.relationships.append(dict(type='inferred-road-contour-repair',owner=owner,parents=repair['sourceParents'],areaM2=repair['areaM2']))
    b.surfaces[:]=[s for s in b.surfaces if not s['poly'].is_empty]
    b.curb_band=new_band
    for name in ('curb_front','curb_back'):b.groups[(name,CURB_MATERIAL)]=[]
    b.curb_front,count=solid_sides(new_band,road,b.dem,b.demtree,b.groups,b.z_at,b.EXTENT)
    b.curb_report.update(topAreaM2=new_band.area,sideSegments=count)
    b.curb_report['precisionProbe']='floating precision local width probe; input boundary retained inside expanded support; numerical tails clipped'
    repair_area=sum(r['areaM2'] for r in all_repairs)
    b.road_seam_report.update(refinementRepairs=len(all_repairs),refinementAreaM2=repair_area,
        repairs=b.road_seam_report['repairs']+len(all_repairs),
        repairedAreaM2=b.road_seam_report['repairedAreaM2']+repair_area)
    return road
