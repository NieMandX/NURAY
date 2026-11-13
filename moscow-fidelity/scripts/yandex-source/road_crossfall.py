"""Limit crossfall relative to source traffic axes, retaining longitudinal grade.

This is a visual road reconstruction, not a surveyed engineering profile.
The shared-vertex constrained solve prevents seams at road intersections.
"""
import json,math
from pathlib import Path
import numpy as np
import shapely as sh
from build_scene import lines

LIMIT_DEGREES=5.
DESIGN_DEGREES=4.9  # small allowance for serialized float32 geometry

def road_topology(xy,z):
    """Weld numerical duplicate XYs and constrain vertices on unsplit edges.

    A local survey introduces T-junctions where fine triangles meet an old,
    longer edge. Merely sharing exact endpoint IDs does not keep that edge
    continuous after changing heights.
    """
    vertices,first,index=np.unique(xy.reshape(-1,2),axis=0,return_index=True,return_inverse=True)
    heights=z.ravel()[first]
    assert np.max(np.abs(heights[index]-z.ravel()))<.001
    from scipy.spatial import cKDTree
    parents=np.arange(len(vertices))
    def find(i):
        while parents[i]!=i:
            parents[i]=parents[parents[i]];i=parents[i]
        return i
    for a,b in cKDTree(vertices).query_pairs(.0001,output_type='ndarray'):
        a,b=find(a),find(b)
        assert abs(heights[a]-heights[b])<.001
        parents[max(a,b)]=min(a,b)
    roots=np.array([find(i) for i in range(len(vertices))]);chosen,inverse=np.unique(roots,return_inverse=True)
    vertices=vertices[chosen];heights=heights[chosen];ids=inverse[index].reshape(-1,3).astype('<u4')
    edges=np.unique(np.sort(ids[:,[[0,1],[1,2],[2,0]]].reshape(-1,2),axis=1),axis=0)
    edges=edges[edges[:,0]!=edges[:,1]];segments=vertices[edges]
    tree=sh.STRtree(sh.linestrings(segments));point,edge=tree.query(sh.points(vertices),predicate='dwithin',distance=.0001)
    keep=(point!=edges[edge,0])&(point!=edges[edge,1]);point,edge=point[keep],edge[keep]
    direction=segments[edge,1]-segments[edge,0];u=((vertices[point]-segments[edge,0])*direction).sum(1)/(direction**2).sum(1)
    keep=(u>1e-8)&(u<1-1e-8);point,edge,u=point[keep],edge[keep],u[keep]
    seam_ids=np.column_stack([point,edges[edge]])
    seam_coeff=np.column_stack([np.ones(len(u)),u-1,-u])
    assert np.max(abs((heights[seam_ids]*seam_coeff).sum(1)),initial=0)<.005
    return vertices,heights,ids,seam_ids,seam_coeff

def source_segments(rows):
    segments=[]
    for f,g,l in rows:
        a=f['attributes']
        if f['layer']!='road' or int(a.get('z_level',0)) or a.get('struct','none') not in ('none','') or a.get('class','').startswith('10') or a.get('class') in ('stairs','crosswalk'):continue
        for line in lines(l):
            p=np.asarray(line.coords);segments.extend(np.stack([p[:-1],p[1:]],axis=1))
    s=np.asarray(segments);return s[np.linalg.norm(s[:,1]-s[:,0],axis=1)>.01]

def solve(xy,z,segments,folder,*,target=None):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    vertices,heights,ids,seam_ids,seam_coeff=road_topology(xy,z)
    tree=sh.STRtree(sh.linestrings(segments));nearest=tree.nearest(sh.points(xy.mean(1)));d=segments[nearest,1]-segments[nearest,0];d/=np.linalg.norm(d,axis=1)[:,None];normal=np.column_stack([-d[:,1],d[:,0]])
    inverse=np.linalg.inv(xy[:,1:]-xy[:,:1]);q=np.einsum('ij,ijk->ik',normal,inverse);coeff=np.column_stack([-q.sum(1),q])
    # Adjacent packed chunks can differ by a few height ULPs. The solve uses
    # ONE source height per shared vertex too, otherwise sliver constraints
    # can become mutually inconsistent after dividing by their tiny width.
    z=heights[ids]
    constant=(coeff*z).sum(1)
    nearest_v=tree.nearest(sh.points(vertices));distance=sh.distance(sh.points(vertices),sh.linestrings(segments[nearest_v]))
    invsqrt=1/np.sqrt(1+100*np.exp(-distance**2/4))
    # Optional civil-grade target is independent of the measured terrain.
    # The same crossfall/seam constraints still govern the serialized result.
    objective=np.zeros(len(vertices))
    if target is not None:
        target=np.asarray(target)
        sums=np.bincount(ids.ravel(),weights=target.ravel(),minlength=len(vertices))
        count=np.bincount(ids.ravel(),minlength=len(vertices))
        objective=-(sums/np.maximum(count,1)-heights)/invsqrt
    weighted=coeff*invsqrt[ids]
    import osqp
    from scipy import sparse
    a=sparse.coo_matrix((weighted.ravel(),(np.repeat(np.arange(len(ids)),3),ids.ravel())),shape=(len(ids),len(vertices))).tocsr()
    # Welding a very short edge combines two coefficients in one column.
    # Normalize AFTER that cancellation, otherwise these rows are ill-scaled.
    norm=np.sqrt(np.asarray(a.power(2).sum(axis=1)).ravel());norm=np.maximum(norm,1e-12)
    a=(sparse.diags(1/norm)@a).tocsc()
    limit=math.tan(math.radians(DESIGN_DEGREES))
    lower=(-limit-constant)/norm;upper=(limit-constant)/norm
    if len(seam_ids):
        weights=seam_coeff*invsqrt[seam_ids];seam_norm=np.linalg.norm(weights,axis=1)
        seams=sparse.coo_matrix(((weights/seam_norm[:,None]).ravel(),(np.repeat(np.arange(len(seam_ids)),3),seam_ids.ravel())),shape=(len(seam_ids),len(vertices))).tocsc()
        seam_target=-(seam_coeff*heights[seam_ids]).sum(1)/seam_norm
        a=sparse.vstack([a,seams],format='csc');lower=np.concatenate([lower,seam_target]);upper=np.concatenate([upper,seam_target])
    print('ROAD TOPOLOGY',len(vertices),'vertices;',len(seam_ids),'edge continuity constraints',flush=True)
    problem=osqp.OSQP();problem.setup(P=sparse.eye(len(vertices),format='csc'),q=objective,A=a,l=lower,u=upper,
        eps_abs=1e-6,eps_rel=1e-6,max_iter=2000,polishing=True,polish_refine_iter=20,delta=1e-9,verbose=False,check_termination=100)
    # Continue the same warm-started QP until the actual geometric contract
    # passes. Requiring a near-exact objective minimum on microscopic slivers
    # is unnecessary once both saved crossfall and edge continuity pass.
    iterations=0
    feasibility_phase=False
    for _ in range(50):
        result=problem.solve();iterations+=result.info.iter
        assert result.info.status in ('solved','solved inaccurate','maximum iterations reached'),result.info.status
        solution=result.x
        delta=solution*invsqrt;after=(coeff*(heights+delta)[ids]).sum(1)
        seam_error=np.max(abs((seam_coeff*(heights+delta)[seam_ids]).sum(1)),initial=0)
        saved_angle=np.degrees(np.arctan(abs((coeff*((heights+delta)[ids].astype('<f4').astype(float))).sum(1))))
        angle=float(np.degrees(np.arctan(abs(after))).max())
        print('ROAD FEASIBILITY',iterations,'iterations;',angle,'degrees;',float(saved_angle.max()),'saved;',seam_error,'seam metres',flush=True)
        if angle<=4.95 and saved_angle.max()<=LIMIT_DEGREES and seam_error<1e-5:break
        if not feasibility_phase and iterations>=4000:
            # On finely clipped survey meshes the default QP balances its
            # objective while tiny geometric violations converge too slowly.
            # Reinitialize penalty adaptation with the SAME problem and warm
            # primal/dual state. Updating adaptive_rho in place does not reset
            # its internal schedule reliably in the installed OSQP version.
            problem=osqp.OSQP();problem.setup(P=sparse.eye(len(vertices),format='csc'),q=objective,A=a,l=lower,u=upper,
                eps_abs=1e-9,eps_rel=1e-9,max_iter=500,rho=1000.,adaptive_rho=False,polishing=False,verbose=False,check_termination=100)
            problem.warm_start(x=result.x,y=result.y)
            feasibility_phase=True
    else:raise AssertionError(('Road constraints did not converge',angle,float(saved_angle.max()),seam_error))
    assert np.abs(after).max()<=math.tan(math.radians(LIMIT_DEGREES)),np.abs(after).max()
    seam_error=np.max(abs((seam_coeff*(heights+delta)[seam_ids]).sum(1)),initial=0)
    assert seam_error<1e-5,seam_error
    saved_angle=np.degrees(np.arctan(abs((coeff*((heights+delta)[ids].astype('<f4').astype(float))).sum(1))))
    assert saved_angle.max()<=LIMIT_DEGREES,float(saved_angle.max())
    area=np.abs(np.linalg.det(xy[:,1:]-xy[:,:1]))/2
    before_angle=np.degrees(np.arctan(np.abs(constant)));after_angle=np.degrees(np.arctan(np.abs(after)))
    report=dict(limitDegrees=LIMIT_DEGREES,designLimitDegrees=DESIGN_DEGREES,triangles=len(ids),sharedVertices=len(vertices),beforeMaxDegrees=float(before_angle.max()),afterMaxDegrees=float(after_angle.max()),
                beforeAreaOverLimitM2=float(area[before_angle>LIMIT_DEGREES].sum()),afterAreaOverLimitM2=float(area[after_angle>LIMIT_DEGREES].sum()),maxHeightAdjustmentM=float(abs(delta).max()),rmsHeightAdjustmentM=float(np.sqrt(np.mean(delta**2))),
                edgeContinuityConstraints=len(seam_ids),edgeContinuityMaxErrorM=float(seam_error),float32MaxDegrees=float(saved_angle.max()),optimizerStatus=result.info.status,optimizerIterations=iterations,
                highPenaltyFeasibilityPhase=feasibility_phase,
                method='Weighted height-change QP with a high-penalty feasibility phase; shared crossfall and T-junction constraints; centerline heights weighted 101x; longitudinal slope not capped')
    if target is not None:
        report['method']='Fit a separately smoothed road-network grade with shared crossfall and T-junction constraints; survey terrain is not modified'
        report['targetFitRmsM']=float(np.sqrt(np.mean(((heights+delta)[ids]-target)**2)))
    np.savez_compressed(folder/'road-height-field.npz',xy=xy,z0=z,z=(heights+delta)[ids],delta=delta[ids],normal=normal,segments=segments)
    (folder/'road-crossfall.json').write_text(json.dumps(report,indent=2)+'\n');print('CROSSFALL SOLVED',report,flush=True)
    return report

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('audit',type=Path);p.add_argument('output',type=Path);a=p.parse_args();d=np.load(a.audit)
    solve(d['xy'],d['z'],d['segments'],a.output)
