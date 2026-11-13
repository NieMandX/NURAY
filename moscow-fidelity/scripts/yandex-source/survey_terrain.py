"""Local survey TIN with a bounded, smooth delta transition to the map DEM.

Requires an explicit horizontal projection and user-selected vertical datum.
No registration fit or arbitrary vertical offset. Contours are sampled rather
than treated as cadastral/engineering constraints. The original map is exact
outside the patch rectangle; metre coordinates are not inferred from INSUNITS.
"""
import gzip,json
from pathlib import Path
import numpy as np
import shapely as sh
from scipy.spatial import Delaunay,cKDTree
from pyproj import Transformer
from build_scene import Terrain,cdt,union,polygons,lines


def safe_sample(terrain,xy):
    xy=np.asarray(xy).reshape(-1,2)
    pi,ti=terrain.tree.query(sh.points(xy),predicate='intersects')
    h=np.full(len(xy),np.nan);h[pi]=(xy[pi]*terrain.planes[ti,:2]).sum(1)+terrain.planes[ti,2]
    missing=np.isnan(h)
    if missing.any():
        q=sh.points(xy[missing]);idx=terrain.tree.nearest(q)
        assert sh.distance(q,terrain.polygons[idx]).max()<.002,'Terrain sampling outside domain'
        h[missing]=(xy[missing]*terrain.planes[idx,:2]).sum(1)+terrain.planes[idx,2]
    return h


def make_field(survey,old,projection,target_crs,folder,blend=120.,spacing=4.,quarantine_outliers=False):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    transform=Transformer.from_crs(projection,target_crs,always_xy=True)
    def project(a):
        a=np.array(a,float);a[:,:2]=np.column_stack(transform.transform(a[:,0],a[:,1]));return a
    raw_marks=project([r['point'] for r in survey['groundMarks']]);samples=[]
    from survey_fairing import suspect_spots
    suspects=suspect_spots(raw_marks)
    for row in suspects:row['sourceHandle']=survey['groundMarks'][row['index']]['handle']
    used=np.ones(len(raw_marks),bool)
    if quarantine_outliers:used[[row['index'] for row in suspects]]=False
    marks=raw_marks[used]
    accepted_contours=0
    for r in survey['contours']:
        a=project(r['points'])
        if np.ptp(a[:,2])>.02 or not marks[:,2].min()-1<=a[0,2]<=marks[:,2].max()+1:continue
        line=sh.LineString(a[:,:2]).simplify(.10);xy=np.asarray(sh.segmentize(line,2).coords)
        samples.append(np.column_stack([xy,np.full(len(xy),a[0,2])]))
        accepted_contours+=1
    contour=np.concatenate(samples)
    # Survey spot marks take precedence over nearly coincident contour labels.
    contour=contour[cKDTree(marks[:,:2]).query(contour[:,:2])[0]>.20]
    points=np.concatenate([marks,contour]);_,idx=np.unique(np.round(points[:,:2],4),axis=0,return_index=True);points=points[np.sort(idx)]
    dt=Delaunay(points[:,:2]);tri=points[dt.simplices]
    edges=np.linalg.norm(tri[:,:2,:2]-tri[:,1:,:2],axis=2)
    longest=np.maximum(edges.max(1),np.linalg.norm(tri[:,0,:2]-tri[:,2,:2],axis=1))
    valid=longest<65
    core=Terrain(tri[valid]);domain=union(list(core.polygons))
    # Any isolated surveyed spot remains represented, without bridging broad gaps.
    bounds=np.array([points[:,:2].min(0)-blend-10,points[:,:2].max(0)+blend+10])
    rect=sh.box(*bounds.reshape(-1));boundary=sh.segmentize(rect.boundary,5)
    old_ids=old.tree.query(rect,predicate='intersects')
    boundary_nodes=[sh.get_coordinates(boundary)]
    for i in old_ids:
        boundary_nodes.append(sh.get_coordinates(old.polygons[i].boundary.intersection(rect.boundary)))
    boundary_nodes=np.concatenate(boundary_nodes)
    terrain_nodes=old.triangles[old_ids,:,:2].reshape(-1,2)
    terrain_nodes=terrain_nodes[sh.covers(rect,sh.points(terrain_nodes))]
    x=np.arange(bounds[0,0],bounds[1,0],spacing);y=np.arange(bounds[0,1],bounds[1,1],spacing)
    grid=np.stack(np.meshgrid(x,y),axis=-1).reshape(-1,2)
    # Sparse survey edges are observations, not the display tessellation.
    # A uniform mesh through the core prevents long, visible triangular fans.
    nodes=np.concatenate([marks[:,:2],terrain_nodes,boundary_nodes,grid])
    # Micrometre welding prevents numerically coincident triangulation nodes.
    _,indices=np.unique(np.round(nodes,6),axis=0,return_index=True);nodes=nodes[np.sort(indices)]
    q=sh.points(nodes);pi,ti=core.tree.query(q,predicate='intersects')
    delta=np.full(len(nodes),np.nan);delta[pi]=(nodes[pi]*core.planes[ti,:2]).sum(1)+core.planes[ti,2]-safe_sample(old,nodes[pi])
    outside=np.isnan(delta)
    ids=core.tree.nearest(q[outside]);near=sh.get_coordinates(sh.get_point(sh.shortest_line(q[outside],core.polygons[ids]),1))
    distance=np.linalg.norm(nodes[outside]-near,axis=1);u=np.clip(distance/blend,0,1);w=1-10*u**3+15*u**4-6*u**5
    delta[outside]=((near*core.planes[ids,:2]).sum(1)+core.planes[ids,2]-safe_sample(old,near))*w
    # Exact spot heights, including isolated marks rejected by alpha-support.
    nearest,ind=cKDTree(nodes).query(marks[:,:2]);assert nearest.max()<2e-6
    delta[ind]=marks[:,2]-safe_sample(old,nodes[ind])
    height=safe_sample(old,nodes)+delta
    # The collar keeps both height and the delta's slope unchanged at the
    # perimeter. Spot measurements are exact; contour polylines guide the
    # fair surface without forcing spurious spikes beside conflicting spots.
    collar=sh.distance(sh.points(nodes),rect.boundary)<spacing*2+.001
    fixed=np.concatenate([ind,np.flatnonzero(collar)])
    fixed_heights=np.concatenate([marks[:,2],safe_sample(old,nodes[collar])])
    from survey_fairing import fair_heights
    print('FAIRING SURVEY',len(nodes),'nodes',len(fixed),'fixed',flush=True)
    faces,height,fairing=fair_heights(nodes,height,fixed,fixed_heights,contour[::2])
    patch_tri=np.column_stack([nodes,height])[faces]
    patch=Terrain(patch_tri);outside_tri=[]
    for i in old_ids:
        xy=cdt(old.polygons[i].difference(rect))
        if len(xy):outside_tri.append(np.concatenate([xy,(xy@old.planes[i,:2]+old.planes[i,2])[:,:,None]],axis=2))
    untouched=np.ones(len(old.triangles),bool);untouched[old_ids]=False
    merged=Terrain(np.concatenate([old.triangles[untouched],*outside_tri,patch.triangles]))
    error=abs(safe_sample(merged,marks[:,:2])-marks[:,2])
    edge_error=abs(safe_sample(patch,boundary_nodes)-safe_sample(old,boundary_nodes))
    assert error.max()<.002,error.max()
    assert edge_error.max()<.002,edge_error.max()
    assert abs(sh.area(patch.polygons).sum()-rect.area)<.005
    report=dict(horizontalCrs='MSK-46 zone 1',verticalDatum='BS-77 assumed by user 2026-11-12',projection=projection,registrationFit=False,verticalShiftM=0,
        groundMarks=len(marks),sourceGroundMarks=len(raw_marks),suspectGroundMarks=suspects,
        quarantinedGroundMarks=len(suspects) if quarantine_outliers else 0,
        contours=accepted_contours,contourSamples=len(contour),supportAreaM2=domain.area,patchBounds=rect.bounds,patchAreaM2=rect.area,
        blendWidthM=blend,gridSpacingM=spacing,fairing=fairing,
        method=f'Minimum gradient-jump surface; exact survey spots, soft contour observations; {blend:g} m transition with fixed outer collar; original DEM outside patch',
        pointErrorMaxM=float(error.max()),seamErrorMaxM=float(edge_error.max()),terrainTriangles=len(merged.triangles),patchTriangles=len(patch.triangles),
        deltaRangeM=[float((height-safe_sample(old,nodes)).min()),float((height-safe_sample(old,nodes)).max())],source=survey['report']['source'])
    np.savez_compressed(folder/'terrain.npz',triangles=merged.triangles)
    np.savez_compressed(folder/'survey-field.npz',triangles=patch.triangles,marks=marks,sourceMarks=raw_marks,sourceMarkUsed=used,bounds=np.array(rect.bounds),domainWkb=np.frombuffer(domain.wkb,dtype=np.uint8))
    (folder/'survey-terrain.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print('SURVEY TERRAIN',json.dumps(report,ensure_ascii=False),flush=True)
    return merged,patch,rect,report

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--base',type=Path,required=True);p.add_argument('--survey',type=Path,required=True);p.add_argument('--projection',required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--quarantine-outliers',action='store_true');a=p.parse_args()
    city=json.loads((a.base/'canonical/urban-model.json').read_text());old=Terrain(np.load(a.base/'canonical/terrain.npz')['triangles'])
    make_field(json.loads(gzip.decompress(a.survey.read_bytes())),old,a.projection,city['crsProj'],a.output,quarantine_outliers=a.quarantine_outliers)
