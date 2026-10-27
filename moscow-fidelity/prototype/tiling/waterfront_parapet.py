"""Massive stone shore parapet, built on the full bank rings before tile cutting.

The existing source-connected river selection is authoritative. No walls are
introduced on acquisition cuts or across bridges, and ponds remain untouched.
"""
import numpy as np
import shapely as sh
from waterfront_finish import GRID,shoreline_uv,triangles,MATERIAL as GRANITE
HEIGHT=1.0
WIDTH=.4
SLAB=2.0
JOINT_WIDTH=.025
JOINT_DEPTH=.012
POLICY=dict(version=1,heightM=HEIGHT,widthM=WIDTH,slabWidthM=SLAB,jointWidthM=JOINT_WIDTH,jointDepthM=JOINT_DEPTH,
 selection='inherited source-connected river banks only; never acquisition cuts or isolated ponds',
 construction='continuous landward strip with shared capped mitres, metric vertical V-joints and closed ends, before tile clipping',
 finish='same approved granite texture, dry upper course without mooring rings or wet waterline')
MATERIAL={**GRANITE,'name':'Набережная · каменный парапет','family':'waterfront-parapet'}
JOINT_MATERIAL={**MATERIAL,'name':'Набережная · вертикальные швы','family':'waterfront-parapet-joint','color':[c*.55 for c in GRANITE['color']]}


def parapet_geometry(banks,origin,domain,bounds):
    a,b,top,rings=(np.asarray(banks[k]) for k in ('a','b','top','rings'))
    delta=b-a;length=np.linalg.norm(delta,axis=1)
    landward=np.column_stack([delta[:,1],-delta[:,0]])/length[:,None]
    coords=np.concatenate([a,b]);keys=np.column_stack([np.rint(coords/GRID).astype(np.int64),np.r_[rings,rings]])
    _,first,inv=np.unique(keys,axis=0,return_index=True,return_inverse=True)
    points=coords[first];ia,ib=np.split(inv,2);direction=np.zeros_like(points)
    np.add.at(direction,ia,landward);np.add.at(direction,ib,landward)
    direction/=np.maximum(np.linalg.norm(direction,axis=1,keepdims=True),1e-20)
    dot=np.ones(len(points))
    np.minimum.at(dot,ia,np.einsum('ij,ij->i',direction[ia],landward));np.minimum.at(dot,ib,np.einsum('ij,ij->i',direction[ib],landward))
    offset=direction*np.minimum(WIDTH/np.maximum(dot,.01),WIDTH*2)[:,None];offset[dot<.05]=0
    # Constrain the back of the parapet to real land, including concave turns.
    factors=np.ones(len(points));interior=domain.buffer(-GRID*3);sh.prepare(interior)
    for _ in range(12):
        back=np.clip(points+offset*factors[:,None],bounds[:2],bounds[2:])
        pa,pb=back[ia],back[ib]
        probes=np.concatenate([pa,pb,pa*.75+pb*.25,(pa+pb)/2,pa*.25+pb*.75])
        good=(~sh.contains(interior,sh.points(probes))).reshape(5,-1).all(0)
        if good.all():break
        bad=np.unique(np.r_[ia[~good],ib[~good]]);factors[bad]*=.5
    back=np.clip(points+offset*factors[:,None],bounds[:2],bounds[2:])
    heights=np.full(len(points),-np.inf);np.maximum.at(heights,ia,top[:,0]);np.maximum.at(heights,ib,top[:,1])
    # U is continuous and closes on an integer repeat for complete rings.
    along=shoreline_uv(banks)*4
    positions=[];uvs=[];joints=[];ends=[]
    ox,oy,oz=origin
    def cross_section(front,rear,z,recess):
        span=rear-front
        # Small bevel, then a shallow V groove at each vertical stone joint.
        near=front+span*(recess/WIDTH);far=rear-span*(recess/WIDTH)
        xy=np.array([near,near,far,far]);yy=np.array([z-.025,z+HEIGHT-recess,z+HEIGHT-recess,z-.025])
        return np.column_stack([xy[:,0]-ox,yy-oz,oy-xy[:,1]])
    degree=np.bincount(inv,minlength=len(points))
    for i,(u0,u1) in enumerate(along):
        cuts=[u0,u1]
        for k in range(int(np.floor(u0/SLAB))-1,int(np.ceil(u1/SLAB))+1):
            cuts.extend(v for v in [k*SLAB-JOINT_WIDTH/2,k*SLAB,k*SLAB+JOINT_WIDTH/2] if u0+1e-9<v<u1-1e-9)
        cuts=np.unique(cuts);t=(cuts-u0)/(u1-u0)
        front=points[ia[i]]*(1-t[:,None])+points[ib[i]]*t[:,None]
        rear=back[ia[i]]*(1-t[:,None])+back[ib[i]]*t[:,None]
        z=heights[ia[i]]*(1-t)+heights[ib[i]]*t
        dist=abs((cuts+SLAB/2)%SLAB-SLAB/2);recess=JOINT_DEPTH*np.maximum(0,1-dist/(JOINT_WIDTH/2))
        sections=[cross_section(f,r,h,d) for f,r,h,d in zip(front,rear,z,recess)]
        for j in range(len(cuts)-1):
            joint=min(recess[j],recess[j+1])>0 or max(recess[j],recess[j+1])>JOINT_DEPTH*.5
            slab=int(np.floor((cuts[j]+cuts[j+1])/(2*SLAB)))
            phase=(cuts[j:j+2]-slab*SLAB)/SLAB
            if slab%2:phase=1-phase
            # Sample one intact upper stone from the approved granite bitmap.
            # Its small masonry joints must not subdivide our massive slabs.
            stone_u=.775+.22*phase
            for edge in range(4):
                nxt=(edge+1)%4
                q=np.array([sections[j][edge],sections[j+1][edge],sections[j+1][nxt],sections[j][nxt]])
                # Dry stone: map a narrow upper band of the exact approved skin.
                v0,v1=(.035,.17) if edge in (0,2) else (.035,.075)
                uv=np.array([[stone_u[0],v0],[stone_u[1],v0],[stone_u[1],v1],[stone_u[0],v1]])
                positions.append(q[[0,3,2,1]]);uvs.append(uv[[0,3,2,1]]);joints.extend([joint,joint])
        if degree[ia[i]]==1:ends.append(sections[0][::-1])
        if degree[ib[i]]==1:ends.append(sections[-1])
    # Keep flags aligned even when collapsed joins generate degenerate faces.
    quads=np.asarray(positions);uv=np.asarray(uvs)
    xyz=quads[:,[0,1,2,0,2,3]].reshape(-1,3,3)
    keep=np.linalg.norm(np.cross(xyz[:,1]-xyz[:,0],xyz[:,2]-xyz[:,0]),axis=1)>1e-9
    result=triangles(quads,uv);flags=np.asarray(joints,dtype=bool)[keep]
    if ends:
        caps=triangles(np.asarray(ends),np.tile([[0,.04],[.1,.04],[.1,.17],[0,.17]],(len(ends),1,1)))
        result=np.concatenate([result,caps]);flags=np.r_[flags,np.zeros(len(caps),bool)]
    stats=dict(triangles=len(result),shoreLengthM=float(length.sum()),sourceBankSegments=len(a),
               heightM=HEIGHT,widthM=WIDTH,slabWidthM=SLAB,closedEnds=len(ends),
               limitedJoins=int((factors<1).sum()),maxJoinOffsetM=float(np.linalg.norm(back-points,axis=1).max()),
               jointTriangles=int(flags.sum()),highParapet=True)
    return result,flags,stats
