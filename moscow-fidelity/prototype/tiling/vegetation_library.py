"""Original faceted vegetation, fitted to measured 2GIS template envelopes.

The supplied Collada trees are visual references only. No reference vertices,
indices or materials enter this generator. Source 2GIS provides dimensions.
"""
import hashlib
from collections import Counter
import numpy as np

def convex_faces(points):
    """Incremental convex hull for the small, non-coplanar crown/branch sets."""
    p=np.asarray(points,float);a=int(np.argmin(p[:,0]));b=int(np.linalg.norm(p-p[a],axis=1).argmax())
    c=int(np.linalg.norm(np.cross(p-p[a],p[b]-p[a]),axis=1).argmax())
    normal=np.cross(p[b]-p[a],p[c]-p[a]);d=int(np.abs((p-p[a])@normal).argmax())
    if abs((p[d]-p[a])@normal)<1e-13:raise ValueError('Degenerate component')
    inside=p[[a,b,c,d]].mean(0)
    def oriented(face):
        x,y,z=face
        return (x,z,y) if np.cross(p[y]-p[x],p[z]-p[x])@(inside-p[x])>0 else (x,y,z)
    faces=[oriented(f) for f in [(a,b,c),(a,b,d),(a,c,d),(b,c,d)]]
    for k in range(len(p)):
        if k in (a,b,c,d):continue
        visible=[f for f in faces if np.cross(p[f[1]]-p[f[0]],p[f[2]]-p[f[0]])@(p[k]-p[f[0]])>1e-12]
        if not visible:continue
        edges=Counter(tuple(sorted(e)) for f in visible for e in [(f[0],f[1]),(f[1],f[2]),(f[2],f[0])])
        faces=[f for f in faces if f not in visible]
        faces.extend(oriented((x,y,k)) for (x,y),count in edges.items() if count==1)
    return np.asarray(faces,dtype=np.int32)

PALETTE=[
    ('Листва · оливковая',[.105,.135,.058]),
    ('Листва · светлая',[.140,.180,.075]),
    ('Листва · тёмная',[.080,.115,.045]),
    ('Хвоя',[.055,.105,.067]),
    ('Кора',[.085,.056,.033]),
    ('Береста',[.420,.410,.370]),
    ('Береста · отметины',[.055,.050,.046]),
]
# Source semantic class, original display template, own silhouettes.
FAMILIES=[
 ('Model_tree_shrubs_point','Template_autumn_bush.001','Куст',[('bush',i) for i in range(4)]),
 ('Model_tree_deciduous_point','Template_autumn_tree.001','Лиственное',[('deciduous',i) for i in range(3)]),
 ('Model_tree_deciduous_growth_point','Template_autumn_porosl.001','Поросль',[('growth',i) for i in range(2)]),
 ('Model_tree_deciduous_low_point','Template_autumn_listvennoe.001','Низкое лиственное',[('low',i) for i in range(2)]),
 ('Model_tree_coniferous_point','Template_summer_pine.001','Ель',[('spruce',i) for i in range(2)]),
 ('Model_tree_deciduous_wide_crown_point','Template_autumn_bigtree.001','Широкая крона',[('wide',i) for i in range(2)]),
 ('Model_tree_narrow_tall_point','Template_autumn_tuya.001','Туя',[('thuja',0)]),
 ('Model_tree_birch_point','Template_autumn_birch.002','Берёза',[('birch',i) for i in range(2)]),
 ('Model_tree_pine_point','Template_summer_sosna.001','Сосна',[('pine',i) for i in range(2)]),
]

def make(kind,variant,bounds):
    """Closed low-poly components, flat normals, local root at zero; Y-up."""
    rng=np.random.default_rng(int.from_bytes(hashlib.sha256(f'nuray-botanical-v1:{kind}:{variant}'.encode()).digest()[:8],'big'))
    tris=[];materials=[];components=[]
    def hull(points,mat):
        p=np.asarray(points,float);faces=convex_faces(p)
        start=len(tris);tris.extend(p[faces]);materials.extend([mat]*len(faces));components.append((start,len(tris)))
    def branch(a,b,r0,r1,mat=4):
        a=np.asarray(a);b=np.asarray(b);d=b-a;d=d/np.linalg.norm(d)
        ref=np.array([0.,0.,1.]) if abs(d[2])<.9 else np.array([0.,1.,0.])
        u=np.cross(d,ref);u/=np.linalg.norm(u);v=np.cross(d,u)
        ring=np.array([np.cos(t)*u+np.sin(t)*v for t in np.arange(5)*2*np.pi/5])
        hull(np.concatenate([a+r0*ring,b+r1*ring]),mat)
    def crown(center,radius,mat=0,segments=8):
        points=[];center=np.asarray(center);radius=np.asarray(radius)
        for j,(z,r) in enumerate([(-1,0),(-.62,.72),(0,1),(.63,.74),(1,0)]):
            for i in range(segments if r else 1):
                a=2*np.pi*(i/segments+j*.045)+variant*.37
                noise=rng.uniform(.88,1.10) if r else 1
                p=np.array([r*np.cos(a)*noise,r*np.sin(a)*noise,z])
                points.append(center+radius*p)
        hull(points,mat)
    # Author in Z-up, then convert to the renderer frame.
    if kind=='bush':
        lobes=1 if variant==0 else 2 if variant==1 else 3
        for j in range(lobes):
            a=2*np.pi*j/lobes+.5;spread=.0 if lobes==1 else .18
            c=[spread*np.cos(a),spread*np.sin(a),.48+rng.uniform(-.05,.05)]
            crown(c,[.35,.32,.46],j%3,segments=7)
            branch([0,0,0],c,.035,.012)
    elif kind in ('spruce','thuja'):
        branch([0,0,0],[.01,0,.88],.033,.008)
        if kind=='thuja':crown([0,0,.53],[.23,.21,.49],3,segments=9)
        else:
            for j in range(3):
                z=.13+j*.22;rad=.42-j*.105
                ring=[[rad*np.cos(a),rad*np.sin(a),z+rng.uniform(-.02,.02)] for a in np.arange(8)*2*np.pi/8+variant*.23+j*.12]
                hull([*ring,[.02*np.sin(j),.01*np.cos(j),min(1.0,z+.45)],[0,0,z-.025]],3)
    elif kind=='pine':
        a=[0,0,0];b=[.045*(1 if variant else -1),.018,.72]
        branch(a,[b[0]*.45,b[1]*.45,.4],.035,.024)
        branch([b[0]*.45,b[1]*.45,.4],b,.024,.012)
        for j in range(3):
            angle=j*2*np.pi/3+variant*.65
            c=[.24*np.cos(angle),.21*np.sin(angle),.80+j*.055]
            branch([b[0],b[1],.56],c,.020,.006)
            crown(c,[.28,.25,.15 if variant else .19],3,segments=7)
    else:
        birch=kind=='birch';wide=kind=='wide';growth=kind=='growth'
        bark=5 if birch else 4
        lean=.025+variant*.014
        for j in range(4):
            z0=j*.15;z1=(j+1)*.15
            start=len(materials)
            branch([lean*z0,0,z0],[lean*z1,.008*np.sin(j),z1],.038*(1-z0),.038*(1-z1),bark)
            if birch:
                for k in range(start,len(materials)):
                    if (k-start+j)%9==0:materials[k]=6
        count=3 if wide else 2 if kind=='deciduous' and variant==2 else 1
        for j in range(count):
            angle=j*2*np.pi/count+variant*.6
            spread=.21 if wide else .12 if count>1 else 0
            center=[spread*np.cos(angle)+lean*.3,spread*np.sin(angle),.69+(j%2)*.05]
            radius=[.30 if wide else .28,.28,.28 if wide else .32]
            if growth:radius=[.22,.20,.35]
            if birch:radius=[.27,.23,.33];center[0]+=.06*(variant*2-1)
            if kind=='low':radius=[.34,.32,.32]
            crown(center,radius,(variant+j)%3,segments=8)
            for k in range(3 if count==1 else 2):
                a=2*np.pi*k/3+variant*.7+j
                endpoint=np.array(center)+[radius[0]*.6*np.cos(a),radius[1]*.6*np.sin(a),-.03]
                branch([lean*.35,0,.34+k*.07],endpoint,.018,.005,bark)
    p=np.asarray(tris)[:,:,[0,2,1]]*[1,1,-1]
    lo=p.min((0,1));hi=p.max((0,1));target_lo=np.array(bounds['min']);target_hi=np.array(bounds['max'])
    # Signed horizontal fitting preserves the root at X=Z=0 even for a leaning
    # source crown with asymmetric min/max. No centroid-based root displacement.
    for axis in (0,2):
        p[:,:,axis]=np.where(p[:,:,axis]<0,p[:,:,axis]*target_lo[axis]/lo[axis],p[:,:,axis]*target_hi[axis]/hi[axis])
    p[:,:,1]=(p[:,:,1]-lo[1])/(hi[1]-lo[1])*(target_hi[1]-target_lo[1])+target_lo[1]
    n=np.cross(p[:,1]-p[:,0],p[:,2]-p[:,0]);n/=np.linalg.norm(n,axis=1,keepdims=True)
    attrs=np.concatenate([p,np.repeat(n[:,None,:],3,axis=1),np.zeros((len(p),3,2))],axis=2)
    return attrs,np.array(materials,dtype=np.uint32),components

def catalog(source_manifest):
    source={c['name']:c for c in source_manifest['chunks']}
    result=[]
    for layer,old,label,variants in FAMILIES:
        for kind,v in variants:
            attrs,mats,components=make(kind,v,source[old]['bounds'])
            result.append(dict(id=f'nuray-{kind}-{v+1:02d}',label=f'{label} {v+1}',layer=layer,
                sourceTemplate=old,sourceChunk=source[old]['id'],sourceBounds=source[old]['bounds'],
                attributes=attrs,materials=mats,components=components))
    return result
