"""Fair a survey surface without moving measured spot heights.

Minimise jumps of the piecewise-linear gradient on a metre-scale mesh.
Survey spots are eliminated as exact Dirichlet constraints, while contours
are soft observations: a simplified contour must not override a nearby
measured spot. The map DEM is fixed in a collar at the replacement boundary.
This is visual interpolation, not an engineering grading design.
"""
import numpy as np
from scipy import sparse
from scipy.sparse.linalg import spsolve
from scipy.spatial import Delaunay


def suspect_spots(marks, radius=30., neighbors=12, excess=5.):
    """Flag, never silently correct, isolated extrema inside neighbour support.

    A point must be surrounded in XY by at least six nearby observations and
    lie >5 m outside their entire elevation range. A monotone slope or a
    surveyed crest with supporting high spots is not an isolated extremum.
    Excluding flagged measurements requires an explicit caller policy.
    """
    from scipy.spatial import cKDTree
    import shapely as sh
    marks=np.asarray(marks,float);result=[]
    if len(marks)<7:return result
    distances,indices=cKDTree(marks[:,:2]).query(marks[:,:2],k=min(neighbors+1,len(marks)))
    for i,p in enumerate(marks):
        keep=(indices[i]!=i)&(distances[i]<=radius)
        near=indices[i,keep]
        if len(near)<6:continue
        a=marks[near];lo,hi=float(a[:,2].min()),float(a[:,2].max())
        outside=max(p[2]-hi,lo-p[2])
        if outside<=excess or not sh.MultiPoint(a[:,:2]).convex_hull.covers(sh.Point(p[:2])):continue
        result.append(dict(index=i,point=p.tolist(),neighborIndices=near.tolist(),neighborHeightRangeM=[lo,hi],
            outsideNeighborRangeM=float(outside),nearestNeighborM=float(distances[i,keep].min()),
            reason='Isolated height outside all nearby elevations, inside their XY convex hull'))
    return result


def fair_heights(nodes, initial, fixed_ids, fixed_heights, observations,
                 fidelity=.002, observation_weight=1.):
    nodes=np.asarray(nodes,float);initial=np.asarray(initial,float)
    dt=Delaunay(nodes);faces=dt.simplices
    xy=nodes[faces];area=abs(np.linalg.det(xy[:,1:]-xy[:,:1]))/2
    basis=np.linalg.inv(np.concatenate([xy,np.ones((*xy.shape[:2],1))],axis=2))[:,:2,:]
    # Each shared edge has one gradient-jump penalty. Weight by the dual
    # distance, so subdividing a triangle does not change smoothing strength.
    left,slot=np.where(dt.neighbors>=0);right=dt.neighbors[left,slot]
    keep=left<right;left,slot,right=left[keep],slot[keep],right[keep]
    edge=np.stack([faces[left,(slot+1)%3],faces[left,(slot+2)%3]],axis=1)
    length=np.linalg.norm(nodes[edge[:,1]]-nodes[edge[:,0]],axis=1)
    dual=2*(area[left]+area[right])/(3*length)
    weight=np.sqrt(length/np.maximum(dual,1e-6))
    coeff=np.concatenate([basis[left],-basis[right]],axis=2)*weight[:,None,None]
    cols=np.concatenate([faces[left],faces[right]],axis=1)
    rows=np.repeat(np.arange(len(left)*2),6)
    bend=sparse.coo_matrix((coeff.ravel(),(rows,np.repeat(cols[:,None,:],2,axis=1).ravel())),shape=(len(left)*2,len(nodes))).tocsr()
    mass=np.zeros(len(nodes));np.add.at(mass,faces.ravel(),np.repeat(area/3,3))
    prior=sparse.diags(np.maximum(mass,1e-6)*fidelity)
    q=bend.T@bend+prior;rhs=prior@initial
    obs=np.asarray(observations,float).reshape(-1,3)
    if len(obs):
        ti=dt.find_simplex(obs[:,:2]);assert (ti>=0).all()
        uv=np.einsum('ijk,ik->ij',dt.transform[ti,:2],obs[:,:2]-dt.transform[ti,2])
        bary=np.column_stack([uv,1-uv.sum(1)])
        a=sparse.coo_matrix((bary.ravel(),(np.repeat(np.arange(len(obs)),3),faces[ti].ravel())),shape=(len(obs),len(nodes))).tocsr()
        q=q+observation_weight*(a.T@a);rhs=rhs+observation_weight*(a.T@obs[:,2])
    fixed_ids=np.asarray(fixed_ids,int);fixed_heights=np.asarray(fixed_heights,float)
    unique,first=np.unique(fixed_ids,return_index=True)
    values=np.full(len(nodes),np.nan);values[unique]=fixed_heights[first]
    assert np.max(abs(values[fixed_ids]-fixed_heights),initial=0)<1e-6,'Contradictory fixed elevations'
    free=np.flatnonzero(np.isnan(values));q=q.tocsr()
    # Solve around the prior, avoiding loss of precision in large absolute
    # elevations on tiny triangles.
    residual=rhs-q@initial
    fixed_delta=values[unique]-initial[unique]
    system=q[free][:,free].tocsc();b=residual[free]-q[free][:,unique]@fixed_delta
    scale=1/np.sqrt(system.diagonal());scaled=sparse.diags(scale)@system@sparse.diags(scale)
    delta=spsolve(scaled.tocsc(),b*scale)*scale
    values[free]=initial[free]+delta
    assert np.isfinite(values).all()
    before=bend@initial;after=bend@values
    stats=dict(vertices=len(nodes),triangles=len(faces),hardConstraints=len(unique),contourObservations=len(obs),
        gradientJumpEnergyBefore=float(before@before),gradientJumpEnergyAfter=float(after@after),
        fixedHeightMaxErrorM=float(abs(values[fixed_ids]-fixed_heights).max(initial=0)),
        maximumInterpolationChangeM=float(abs(values-initial).max()))
    if len(obs):
        error=abs(a@values-obs[:,2])
        stats['contourResidualPercentilesM']=np.quantile(error,[.5,.95,1]).tolist()
    return faces,values,stats


class TerrainNormals:
    """Continuous shading for ground skins, never building/curb side faces."""
    def __init__(self,terrain):
        self.terrain=terrain
        xy=terrain.triangles[:,:,:2]
        vertices,inverse=np.unique(xy.reshape(-1,2),axis=0,return_inverse=True)
        ids=inverse.reshape(-1,3)
        area=abs(np.linalg.det(xy[:,1:]-xy[:,:1]))/2
        normal=np.column_stack([-terrain.planes[:,0],np.ones(len(xy)),terrain.planes[:,1]])
        unit=normal/np.linalg.norm(normal,axis=1,keepdims=True)
        # A real terrace edge must not average opposite-facing slopes. Keep
        # a separate corner normal for each incident face at sharp creases.
        face_ids=np.repeat(np.arange(len(xy)),3);vertex_ids=ids.ravel()
        adjacency=sparse.coo_matrix((np.ones(len(face_ids)),(vertex_ids,face_ids)),shape=(len(vertices),len(xy))).tocsr()
        start=adjacency.indptr[vertex_ids];degree=np.diff(adjacency.indptr)[vertex_ids]
        sums=np.zeros((len(face_ids),3));weighted=normal*area[:,None]
        for offset in range(int(degree.max(initial=0))):
            corners=np.flatnonzero(degree>offset);other=adjacency.indices[start[corners]+offset]
            compatible=(unit[face_ids[corners]]*unit[other]).sum(1)>=np.cos(np.deg2rad(75))
            sums[corners[compatible]]+=weighted[other[compatible]]
        sums/=np.maximum(np.linalg.norm(sums,axis=1,keepdims=True),1e-20)
        design=np.concatenate([xy,np.ones((*xy.shape[:2],1))],axis=2)
        self.coeff=np.linalg.solve(design,sums.reshape(-1,3,3))

    def sample(self,xy):
        import shapely as sh
        xy=np.asarray(xy).reshape(-1,2)
        ids=self.terrain.tree.nearest(sh.points(xy))
        n=np.einsum('ij,ijk->ik',np.column_stack([xy,np.ones(len(xy))]),self.coeff[ids])
        return n/np.maximum(np.linalg.norm(n,axis=1,keepdims=True),1e-20)

    def for_triangles(self,xy):
        import shapely as sh
        xy=np.asarray(xy).reshape(-1,3,2)
        ids=self.terrain.tree.nearest(sh.points(xy.mean(1)))
        n=np.concatenate([xy,np.ones((*xy.shape[:2],1))],axis=2)@self.coeff[ids]
        return n/np.maximum(np.linalg.norm(n,axis=2,keepdims=True),1e-20)


def refresh_ground_normals(root):
    """Refresh survey ground shading after grading, before derived packaging."""
    import json,shapely as sh
    from build_scene import Terrain
    from apply_crossfall import unpack
    from object_geometry import pack
    from survey_terrain import safe_sample
    report=json.loads((root/'survey-terrain.json').read_text())
    if not report.get('fairing'):return
    terrain=Terrain(np.load(root/'canonical/terrain.npz')['triangles']);normals=TerrainNormals(terrain)
    full=root/'canonical/full';scene=json.loads((full/'scene.json').read_text());rect=sh.box(*report['patchBounds'])
    count=0;fallback=0;updated=0
    for c in scene['chunks']:
        if c['name']!='land':continue
        t,m,tint=unpack(full,c);xy=t[:,:,[0,2]]*[1,-1]
        selected=np.flatnonzero((m!=0)&sh.covers(rect,sh.points(xy.mean(1))))
        if not len(selected):continue
        height=safe_sample(terrain,xy[selected].reshape(-1,2)).reshape(-1,3)-scene['origin'][2]
        # Entrance ramps have their own graded normals; retain those.
        selected=selected[np.ptp(t[selected,:,1]-height,axis=1)<.002]
        if not len(selected):continue
        n=normals.for_triangles(xy[selected]);v=t[selected,:,:3]
        face=np.cross(v[:,1]-v[:,0],v[:,2]-v[:,0]);length=np.linalg.norm(face,axis=1)
        face/=np.maximum(length[:,None],1e-20)
        bad=(n*face[:,None]).sum(2)<=.05
        n[bad]=np.broadcast_to(face[:,None],n.shape)[bad];fallback+=int(bad.sum())
        count+=len(selected)
        # Octahedral serialization introduces only ~1e-5 normal error. Avoid
        # recompressing already refreshed blocks during derived packaging.
        if np.max(abs(t[selected,:,3:6]-n),initial=0)<1e-4:continue
        t[selected,:,3:6]=n;updated+=1
        c.update(pack(t,m,full/c['file'],tints=None if not np.any(tint) else tint))
    (full/'scene.json').write_text(json.dumps(scene,ensure_ascii=False,separators=(',',':'))+'\n')
    print('SURVEY NORMALS',dict(triangles=count,updatedChunks=updated,creaseAngleDegrees=75,fallbackCorners=fallback),flush=True)
