"""Smooth longitudinal road grades on their own network, not across ravines.

The source terrain is evidence, not a finished pavement. A 1D bending energy
removes short waves while retaining long climbs. Crossfall and mesh continuity
are subsequently enforced by the existing constrained road solve.
"""
import argparse,json
from pathlib import Path
import numpy as np
import shapely as sh
from scipy import sparse
from scipy.sparse.linalg import spsolve
from scipy.spatial import cKDTree
from build_scene import lines
from apply_crossfall import RoadField
from road_crossfall import solve


def fade(distance,inner,outer):
    t=np.clip((np.asarray(distance)-inner)/(outer-inner),0,1)
    return 1-t*t*(3-2*t)


def smooth_network(segments,heights,length=12.):
    """Segments already share endpoint coordinates; preserve linear grades."""
    nodes,ids=np.unique(np.round(segments.reshape(-1,2),5),axis=0,return_inverse=True)
    ids=ids.reshape(-1,2);keep=ids[:,0]!=ids[:,1];ids=np.unique(np.sort(ids[keep],axis=1),axis=0)
    z=np.asarray(heights(nodes));d=nodes[ids[:,1]]-nodes[ids[:,0]];dist=np.linalg.norm(d,axis=1)
    mass=np.bincount(ids.ravel(),weights=np.repeat(dist/2,2),minlength=len(nodes))
    adjacent=[[]for _ in nodes]
    for a,b in ids:adjacent[a].append(b);adjacent[b].append(a)
    cols=[];values=[]
    for i,near in enumerate(adjacent):
        for k,a in enumerate(near):
            for b in near[k+1:]:
                da=nodes[a]-nodes[i];db=nodes[b]-nodes[i];la=np.linalg.norm(da);lb=np.linalg.norm(db)
                # Continue through junctions only along a compatible road.
                # Perpendicular branches share a height, not a forced tangent.
                if da@db/(la*lb)>-.7:continue
                cols.append([a,i,b]);values.append(np.array([1/la,-1/la-1/lb,1/lb])/np.sqrt((la+lb)/2))
    bend=sparse.coo_matrix((np.asarray(values).ravel(),(np.repeat(np.arange(len(cols)),3),np.asarray(cols).ravel())),shape=(len(cols),len(nodes))).tocsr()
    prior=sparse.diags(np.maximum(mass,.01));p=prior+length**4*(bend.T@bend)
    fitted=z+spsolve(p.tocsc(),-length**4*(bend.T@(bend@z)))
    stats=dict(vertices=len(nodes),edges=len(ids),smoothingLengthM=length,
       bendingEnergyBefore=float(np.sum((bend@z)**2)),bendingEnergyAfter=float(np.sum((bend@fitted)**2)),
       maxChangeM=float(abs(fitted-z).max()),rmsChangeM=float(np.sqrt(np.mean((fitted-z)**2))))
    return nodes,ids,z,fitted,stats


class NetworkGrade:
    def __init__(self,nodes,ids,z):
        self.segments=nodes[ids];self.heights=z[ids]
        self.mid=self.segments.mean(1);self.tree=cKDTree(self.mid)
        self.d=self.segments[:,1]-self.segments[:,0];self.l2=np.sum(self.d**2,axis=1)
    def sample(self,xy):
        xy=np.asarray(xy).reshape(-1,2);out=[]
        for first in range(0,len(xy),20000):
            q=xy[first:first+20000];_,ix=self.tree.query(q,k=min(24,len(self.mid)))
            v=q[:,None]-self.segments[ix,0];u=np.clip(np.sum(v*self.d[ix],axis=2)/self.l2[ix],0,1)
            closest=self.segments[ix,0]+u[:,:,None]*self.d[ix]
            dist2=np.sum((closest-q[:,None])**2,axis=2)
            # Smooth weighting avoids discrete nearest-segment switches.
            w=1/(.5+dist2)**3;h=self.heights[ix,0]*(1-u)+self.heights[ix,1]*u
            out.append(np.sum(w*h,axis=1)/np.sum(w,axis=1))
        return np.concatenate(out) if out else np.empty(0)


def build(base,out,center=(150.,180.),inner=800.,outer=1000.,length=12.):
    out.mkdir(parents=True,exist_ok=True);old=RoadField(base/'canonical/road-height-field.npz')
    center=np.asarray(center);roi=sh.Point(center).buffer(outer+100)
    source=sh.intersection(sh.linestrings(np.load(base/'canonical/road-height-field.npz')['segments']),roi)
    chains=list(lines(sh.line_merge(sh.union_all(source))))
    segments=[]
    for line in chains:
        p=np.asarray(sh.segmentize(line,2.).coords);segments.extend(np.stack([p[:-1],p[1:]],axis=1))
    nodes,ids,z,fitted,stats=smooth_network(np.asarray(segments),lambda q:sum(old.sample(q)[:2]),length)
    network=NetworkGrade(nodes,ids,fitted)
    vertices,inv=np.unique(old.xy.reshape(-1,2),axis=0,return_inverse=True)
    weight=fade(np.linalg.norm(vertices-center,axis=1),inner,outer);target=old.z.copy().ravel()
    original=sum(old.sample(vertices)[:2]);new=original.copy();selected=weight>0
    new[selected]+=(network.sample(vertices[selected])-original[selected])*weight[selected]
    target=new[inv].reshape(old.z.shape)
    np.savez_compressed(out/'network-grade.npz',nodes=nodes,ids=ids,original=z,height=fitted,center=center,inner=inner,outer=outer)
    print('NETWORK GRADE',stats,flush=True)
    report=solve(old.xy,old.z,np.load(base/'canonical/road-height-field.npz')['segments'],out,target=target)
    report.update(network=stats,center=center.tolist(),innerRadiusM=inner,outerRadiusM=outer,
                  surveyPolicy='Original terrain and survey retained; separately reconstructed finished pavement')
    (out/'road-crossfall.json').write_text(json.dumps(report,indent=2)+'\n')
    return report

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--base',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--length',type=float,default=12.);a=p.parse_args();build(a.base,a.output,length=a.length)
