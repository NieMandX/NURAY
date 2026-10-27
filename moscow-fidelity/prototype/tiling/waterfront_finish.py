"""Approved ashlar skin and continuous low cornice on the canonical shore.

Only the existing selected bank rings are used. No additional water selection,
excavation, bridge closure, acquisition-edge wall, or high parapet is introduced.
"""
from pathlib import Path
import hashlib,shutil
import numpy as np
import shapely as sh
GRID=1e-5

TEXTURE='granite-mooring-v2.png'
ASSET=Path(__file__).parent/'assets'/TEXTURE
PROJECTION=.12
HEIGHT=.16
POLICY=dict(version=2,textureRepeatM=[4,2],mooringRingSpacingM=4,mooringRings='baked into the approved diffuse texture',corniceProjectionM=PROJECTION,corniceHeightM=HEIGHT,highParapet=False,uv='continuous shoreline chainage; closed rings fit the nearest whole repeat count to avoid a closure seam; horizontal repeat only, full height once',joins='shared ring vertices, capped mitres; water-domain constrained projection, before tile clipping')
MATERIAL=dict(name='Набережная · массивный серый гранит и кольца',family='waterfront-granite',color=[.70,.82,.98],roughness=.86,metallic=0,ior=1.5,kind=1,alphaCutoff=0,texture='textures/'+TEXTURE)

def install_texture(folder):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True);target=folder/TEXTURE
    shutil.copyfile(ASSET,target);raw=target.read_bytes()
    return {TEXTURE:dict(sha256=hashlib.sha256(raw).hexdigest(),bytes=len(raw),repeatM=[4,2],horizontalOnly=True,mooringRingSpacingM=4,provenance='ImageGen, user-approved Saint Petersburg granite reference; original image preserved')}

def triangles(quads,uv):
    xyz=quads[:,[0,1,2,0,2,3]].reshape(-1,3,3);tex=uv[:,[0,1,2,0,2,3]].reshape(-1,3,2)
    n=np.cross(xyz[:,1]-xyz[:,0],xyz[:,2]-xyz[:,0]);length=np.linalg.norm(n,axis=1);keep=length>1e-9
    return np.concatenate([xyz[keep],np.repeat((n[keep]/length[keep,None])[:,None,:],3,axis=1),tex[keep]],axis=2)

def shoreline_uv(banks):
    along=np.asarray(banks['chainage']);uv=along/4
    for ring in np.unique(banks['rings']):
        ids=np.flatnonzero(banks['rings']==ring);a=np.rint(banks['a'][ids]/GRID).astype(np.int64);b=np.rint(banks['b'][ids]/GRID).astype(np.int64)
        # Open stretches ending at an acquisition cut keep exact 4 m scale.
        # Only a genuinely closed ring needs its final texel to meet the first.
        if not np.array_equal(a[np.lexsort((a[:,1],a[:,0]))],b[np.lexsort((b[:,1],b[:,0]))]):continue
        total=float(along[ids].max());repeats=max(1,round(total/4))
        if total>1e-8:uv[ids]=along[ids]*repeats/total
    return uv

def finished_bank(banks,origin):
    from waterfront import bank_triangles
    tri=bank_triangles(banks,origin)
    # The generated skin has a damp bottom and an attachment ring: it must never
    # wrap in V over a paving lip. Keep U and all original positions/normals.
    tri[:,:,7]=np.tile([0,0,1,0,1,1],len(banks['a'])).reshape(-1,3)
    u=shoreline_uv(banks);tri[:,:,6]=u[:,[0,1,1,0,1,0]].reshape(-1,3)
    return tri

def cornice_geometry(banks,origin,domain):
    a,b,top,along,rings=(np.asarray(banks[k]) for k in ('a','b','top','chainage','rings'))
    delta=b-a;length=np.linalg.norm(delta,axis=1);waterward=np.column_stack([-delta[:,1],delta[:,0]])/length[:,None]
    coords=np.concatenate([a,b]);keys=np.column_stack([np.rint(coords/GRID).astype(np.int64),np.r_[rings,rings]])
    _,first,inv=np.unique(keys,axis=0,return_index=True,return_inverse=True);points=coords[first];ia,ib=np.split(inv,2)
    summed=np.zeros_like(points);np.add.at(summed,ia,waterward);np.add.at(summed,ib,waterward)
    norm=np.linalg.norm(summed,axis=1);direction=summed/np.maximum(norm[:,None],1e-20)
    dot=np.ones(len(points));np.minimum.at(dot,ia,np.einsum('ij,ij->i',direction[ia],waterward));np.minimum.at(dot,ib,np.einsum('ij,ij->i',direction[ib],waterward))
    offset=direction*np.minimum(PROJECTION/np.maximum(dot,.01),PROJECTION*2)[:,None]
    offset[dot<.05]=0 # no spike at an almost reversing coastline
    allowed=domain.buffer(GRID*3);sh.prepare(allowed)
    # Keep the narrow band on the water side even at concave corners and very
    # narrow channels. One factor per shared vertex preserves connected joins.
    factors=np.ones(len(points))
    for _ in range(10):
        pa=points[ia]+offset[ia]*factors[ia,None];pb=points[ib]+offset[ib]*factors[ib,None]
        probes=np.concatenate([pa,pb,pa*.75+pb*.25,(pa+pb)/2,pa*.25+pb*.75])
        good=sh.covers(allowed,sh.points(probes)).reshape(5,-1).all(0)
        if good.all():break
        bad=np.unique(np.r_[ia[~good],ib[~good]]);factors[bad]*=.5
    factors[factors<.002]=0
    displacements=offset*factors[:,None]
    h=np.full(len(points),-np.inf);np.maximum.at(h,ia,top[:,0]);np.maximum.at(h,ib,top[:,1])
    # A modest bevel at the top, flush with paving; no raised parapet.
    profile=[(0,-HEIGHT),(1,-HEIGHT),(1,-.045),(.75,0),(0,0)]
    ox,oy,oz=origin;sections=[]
    for width,z in profile:
        xy=points+displacements*width;sections.append(np.column_stack([xy[:,0]-ox,h+z-oz,oy-xy[:,1]]))
    out=[];us=shoreline_uv(banks)
    for j in range(len(profile)-1):
        q=np.stack([sections[j][ia],sections[j][ib],sections[j+1][ib],sections[j+1][ia]],axis=1)
        # Only dry stone from the top course; no ring or damp band on the trim.
        va=.045+j*.015;vb=va+.015
        uv=np.stack([np.column_stack([us[:,0],np.full(len(a),va)]),np.column_stack([us[:,1],np.full(len(a),va)]),np.column_stack([us[:,1],np.full(len(a),vb)]),np.column_stack([us[:,0],np.full(len(a),vb)])],axis=1)
        out.append(triangles(q[:,[0,3,2,1]],uv[:,[0,3,2,1]]))
    # Cap only genuine ends of the inherited shore strip, never tile cuts.
    degree=np.bincount(inv,minlength=len(points));caps=[]
    for node in np.flatnonzero(degree==1):
        p=np.array([s[node] for s in sections])
        for k in range(1,len(p)-1):caps.append([p[0],p[k],p[k+1]])
    if caps:
        xyz=np.asarray(caps);n=np.cross(xyz[:,1]-xyz[:,0],xyz[:,2]-xyz[:,0]);ln=np.linalg.norm(n,axis=1);keep=ln>1e-9
        out.append(np.concatenate([xyz[keep],np.repeat((n[keep]/ln[keep,None])[:,None,:],3,axis=1),np.full((keep.sum(),3,2),.07)],axis=2))
    result=np.concatenate(out)
    return result,dict(corniceTriangles=len(result),corniceSegments=len(a),sharedJoinVertices=len(points),projectionLimitedVertices=int((factors<1).sum()),maxProjectionM=float(np.linalg.norm(displacements,axis=1).max()),highParapet=False)
