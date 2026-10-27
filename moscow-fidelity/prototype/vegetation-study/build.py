"""Isolated shape studies: branch-led, non-convex crowns; no city integration."""
from pathlib import Path
import sys,json,hashlib
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tiling'))
from object_geometry import pack,export_glb

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'web-preview/vegetation-study/assets'
SOURCE=ROOT/'web-preview/prototype/tiles/assets-km1-vegetation/canonical/full/scene.json'
FOLIAGE_SCALE=1.20
FOLIAGE_SCALES={'birch':FOLIAGE_SCALE*1.30,'spruce':FOLIAGE_SCALE*1.35*1.20}
CROWN_RADIAL_FACTORS={'pine':.70}  # Keep the first 30% inward move; the second was rejected.
SPRUCE_HELIX=dict(boughs=40,stepDegrees=65,heightExponent=1.35,baseHeight=.18,
    azimuthJitterDegrees=22,heightStepJitter=.30)
PALETTE=[('Листва · олива',[.16,.19,.075]),('Листва · свет',[.20,.235,.105]),
 ('Листва · глубина',[.105,.135,.047]),('Хвоя',[.078,.125,.063]),
 ('Кора',[.105,.072,.044]),('Береста',[.50,.48,.40]),('Береста · отметины',[.055,.047,.030])]
MODELS=[
 ('open','Лиственное · сквозистое','Неровный ярусный силуэт, открытые развилки и просветы между ветвями.','Template_autumn_bigtree.001','nuray-wide-01'),
 ('compact','Лиственное · широкое','Крупная смещённая масса с выемками по нижнему краю.','Template_autumn_bigtree.001','nuray-wide-01'),
 ('birch','Берёза','Тонкий светлый ствол, неравные ветви, опущенные концы кроны.','Template_autumn_birch.002','nuray-birch-01'),
 ('pine','Сосна','Изломанный ствол и разновысокие плоские группы хвои.','Template_summer_sosna.001','nuray-pine-01'),
 ('spruce','Ель','Вытянутые хвойные лапы идут по спирали: широкие внизу, короткие у вершины.','Template_summer_pine.001','nuray-spruce-01'),
 ('bush','Кустарник','Несколько стволиков, низкая несимметричная крона и неровный край.','Template_autumn_bush.001','nuray-bush-03'),
 ('thuja','Туя','Узкая вертикальная крона: крупные вытянутые группы хвои, неровные плечи и смещённая вершина.','Template_autumn_tuya.001','nuray-thuja-01'),
 ('growth','Лиственная поросль','Три тонких стволика разной высоты, крупные молодые кроны и просветы между ветвями.','Template_autumn_porosl.001','nuray-growth-01'),
 ('low','Низкое лиственное','Короткий ствол, открытые развилки и широкая неровная крона из крупных лиственных масс.','Template_autumn_listvennoe.001','nuray-low-01'),
]
NEW_STUDIES={
 'thuja':dict(studyLabel='Туя · вертикальные группы хвои',smoothingAngle=58,foliageColor='#527253'),
 'growth':dict(studyLabel='Поросль · три молодых стволика',smoothingAngle=68,foliageColor='#7d925c'),
 'low':dict(studyLabel='Низкое лиственное · крупная крона',smoothingAngle=70,foliageColor='#687d4b'),
}

class Mesh:
    def __init__(self,kind):
        self.rng=np.random.default_rng(int.from_bytes(hashlib.sha256(('nuray-study-01:'+kind).encode()).digest()[:8],'big'))
        self.tris=[];self.mats=[];self.components=[];self.branch_tips=[]
    def component(self,p,faces,mat,tag):
        p=np.asarray(p,float);f=np.asarray(faces);t=p[f]
        if np.sum(t[:,0]*np.cross(t[:,1],t[:,2]))<0:f=f[:,[0,2,1]];t=p[f]
        start=len(self.tris);self.tris.extend(t)
        self.mats.extend([mat]*len(t));self.components.append(dict(start=start,end=len(self.tris),kind=tag))
        return f
    def branch(self,path,radius,mat=4,sides=5,role='branch'):
        p=np.asarray(path,float);r=np.linspace(radius,radius*.17,len(p));v=[];faces=[]
        for i,c in enumerate(p):
            tangent=p[min(i+1,len(p)-1)]-p[max(i-1,0)];tangent/=np.linalg.norm(tangent)
            axis=np.array([0.,1.,0.]);u=np.cross(tangent,axis);u/=np.linalg.norm(u);w=np.cross(tangent,u)
            for k in range(sides):
                a=k*2*np.pi/sides;v.append(c+r[i]*(np.cos(a)*u+np.sin(a)*w))
        for j in range(len(p)-1):
            for k in range(sides):
                a=j*sides+k;b=j*sides+(k+1)%sides;c=b+sides;d=a+sides
                faces.extend([(a,b,c),(a,c,d)])
        for k in range(1,sides-1):
            faces.extend([(0,k+1,k),((len(p)-1)*sides,(len(p)-1)*sides+k,(len(p)-1)*sides+k+1)])
        start=len(self.mats);faces=self.component(v,faces,mat,'wood')
        if role=='trunk':
            self.components[-1].update(role=role,centerline=p.tolist(),sides=sides,
                rings=np.asarray(v).reshape(len(p),sides,3).tolist(),faces=faces.tolist())
        if mat==5:
            for k in range(start,len(self.mats)):
                if (k-start)%17 in (2,3):self.mats[k]=6
        self.branch_tips.append(p[-1])
    def foliage(self,center,size,mat=0,phase=0,notch=.57):
        # Non-convex closed rings: independent radial notches, unequal heights,
        # off-axis cap vertices. No convex hull can erase the indentations.
        c=np.array(center,float);size=np.array(size);r=self.rng;N=7
        pts=[c+size*np.array([r.uniform(-.2,.2),r.uniform(-.2,.2),-.66])]
        radial=r.uniform(.70,1.24,N);radial[int(r.integers(N))]*=notch
        for j,(z,span) in enumerate([(-.48,.66),(.02,1.0),(.47,.69)]):
            shift=r.uniform(-.15,.15,2)
            for k in range(N):
                a=k*2*np.pi/N+phase+j*.21+r.uniform(-.09,.09)
                rr=span*radial[k]*r.uniform(.9,1.10)
                v=[np.cos(a)*rr+shift[0],np.sin(a)*rr+shift[1],z+r.uniform(-.20,.17)]
                pts.append(c+size*np.array(v))
        pts.append(c+size*np.array([r.uniform(-.3,.3),r.uniform(-.3,.3),.72]))
        faces=[]
        for k in range(N):
            a=1+k;b=1+(k+1)%N
            faces.extend([(0,b,a),(len(pts)-1,a+2*N,b+2*N)])
            for j in range(2):
                x=a+j*N;y=b+j*N
                faces.extend([(x,y,y+N),(x,y+N,x+N)])
        self.component(pts,faces,mat,'foliage')
        self.components[-1]['center']=c.tolist()
    def cluster(self,c,size,mat=0,count=3,phase=0):
        c=np.array(c,float);size=np.array(size)
        self.foliage(c,size,mat,phase)
        for j in range(count-1):
            a=phase+j*2.7+self.rng.uniform(-.4,.4)
            offset=np.array([np.cos(a)*size[0]*.70,np.sin(a)*size[1]*.70,size[2]*self.rng.uniform(-.3,.25)])
            self.foliage(c+offset,size*self.rng.uniform(.50,.72),mat if mat==3 else (mat+j+1)%3,a)

    def spruce_bough(self,anchor,length,width,thickness,angle,droop,pitch=0.,roll=0.):
        """Closed, flattened radial pad with shallow, irregular edge lobes.

        The long axis points away from the trunk. Two offset ridge vertices
        give the pad volume without turning it into the deciduous clump.
        All edge points remain visible from the ridge in plan, so the fans
        triangulate the mildly concave outline without crossing its boundary.
        """
        anchor=np.asarray(anchor,float);r=self.rng
        outline=np.array([[0,-.13],[.20,-.72],[.42,-.75],[.59,-1],
            [.81,-.66],[1,-.025],[.89,.43],[.70,.85],[.48,.79],
            [.31,.95],[.10,.50],[0,.12]],float)
        # Vary radii around an interior point: this changes lobes without
        # swapping perimeter rays or making the fan self-intersect.
        mid=.49
        outline[1:-1]=[mid,0]+(outline[1:-1]-[mid,0])*r.uniform(.78,1.22,(len(outline)-2,1))
        x=outline[:,0]*length;y=outline[:,1]*width*.5
        z=-droop*np.maximum(0,outline[:,0])**1.3+r.uniform(-.09,.09,len(outline))*thickness
        local=np.column_stack([x,y,z]).tolist()
        ridge_y=0.
        local.extend([[mid*length,ridge_y,-droop*mid**1.3+thickness*.55],
                      [mid*length,ridge_y,-droop*mid**1.3-thickness*.45]])
        yaw=np.array([[np.cos(angle),-np.sin(angle),0],
                      [np.sin(angle), np.cos(angle),0],[0,0,1]])
        tilt=np.array([[np.cos(pitch),0,np.sin(pitch)],[0,1,0],[-np.sin(pitch),0,np.cos(pitch)]])
        bank=np.array([[1,0,0],[0,np.cos(roll),-np.sin(roll)],[0,np.sin(roll),np.cos(roll)]])
        rotation=yaw@tilt@bank
        points=np.asarray(local)@rotation.T+anchor
        count=len(outline);faces=[]
        for k in range(count):
            nxt=(k+1)%count
            faces.extend([(count,k,nxt),(count+1,nxt,k)])
        self.component(points,faces,3,'foliage')
        self.components[-1].update(center=(np.array([mid*length,ridge_y,-droop*mid**1.3])@rotation.T+anchor).tolist(),
            shape='radial-pad',anchor=anchor.tolist(),azimuth=float(angle),
            length=float(length),width=float(width),thickness=float(thickness),
            pitch=float(pitch),roll=float(roll),frame=rotation.tolist())
        return np.array([length*.87,0,-droop*.87])@rotation.T+anchor

def round_trunk_sections(rings,centers):
    """Replace each fitted ellipse by its inscribed circle, keeping its plane.

    SVD finds the stretched section axis, not the tree's bounding-box axis.
    Only its larger singular value is reduced. The five-sided low-poly section,
    centerline, section orientation and taper remain (the root keeps its ground
    contact). Envelope fitting can be
    piecewise around the origin; use a conservative radius in that case too.
    """
    sides=rings.shape[1];angles=np.arange(sides)*2*np.pi/sides
    circle=np.stack([np.cos(angles),np.sin(angles)],axis=1)
    result=[];report=[];previous=np.inf
    for ring,center in zip(rings,centers):
        offsets=ring-center
        ellipse=np.linalg.lstsq(circle,offsets,rcond=None)[0]
        u,s,v=np.linalg.svd(ellipse,full_matrices=False)
        radius=min(s[-1],np.linalg.norm(offsets,axis=1).min(),previous)
        corrected=center+circle@((u*radius)@v)
        # Keep the root in contact with the same ground plane after narrowing.
        anchor_shift=float(ring[:,1].min()-corrected[:,1].min()) if not result else 0.0
        corrected[:,1]+=anchor_shift
        center=center.copy();center[1]+=anchor_shift
        result.append(corrected);previous=radius
        report.append(dict(center=center.tolist(),beforeRadii=s.tolist(),radius=float(radius),
            rootAnchorShiftY=anchor_shift,maxFitResidual=float(np.linalg.norm(circle@ellipse-offsets,axis=1).max())))
    return np.asarray(result),report

def make(kind,bounds,round_trunk=True,crown_factor=None):
    m=Mesh(kind);r=m.rng
    if kind in ('open','compact','birch'):
        birch=kind=='birch';bark=5 if birch else 4
        path=[[0,0,0],[-.025,.012,.19],[.015,-.007,.38],[-.022,.018,.57],[.035,.01,.78],[.01,-.025,.98]]
        if birch:path=[[0,0,0],[.015,.01,.25],[-.009,0,.48],[.04,.01,.70],[.03,.04,.94]]
        m.branch(path,.020 if birch else .028,bark,role='trunk')
        if kind=='bush':
            row.update(studyLabel='Кустарник · низкая неровная крона',defaultSmoothingAngle=65,
                defaultFoliageColor='#62794b',defaultCurvatureStrength=100,
                scaleDescription='Несколько тонких стволиков и 28 неравных лиственных фрагментов. Доступны размер по осям, повороты, Boolean и упрощение оболочки.')
        if kind=='open':
            ends=[[-.29,-.025,.66],[.25,.05,.72],[-.12,.13,.87],[.17,-.09,.97],[-.20,-.15,.48],[.30,-.10,.49],[-.035,-.025,1.07],[-.29,.13,.80]]
            sizes=[[.145,.13,.12],[.14,.13,.14],[.12,.105,.13],[.11,.10,.11],[.09,.085,.07],[.12,.11,.09],[.10,.09,.10],[.10,.085,.09]]
        elif kind=='compact':
            ends=[[-.28,.01,.67],[.18,.02,.87],[-.07,.03,.94],[.31,-.07,.64],[-.18,-.15,.85],[.02,.22,.75],[.24,.16,.56],[-.26,.14,.48]]
            sizes=[[.19,.18,.19],[.21,.15,.15],[.19,.16,.16],[.15,.14,.12],[.17,.16,.17],[.17,.16,.16],[.12,.13,.10],[.10,.12,.11]]
        else:
            ends=[[-.25,.00,.62],[.19,.10,.75],[-.14,-.07,.86],[.15,-.12,.54],[-.12,.16,.48],[.04,.04,1.02],[.23,.0,.91]]
            sizes=[[.115,.12,.15],[.10,.13,.16],[.13,.12,.16],[.12,.10,.13],[.085,.09,.14],[.13,.13,.15],[.10,.10,.11]]
        for i,(end,size) in enumerate(zip(ends,sizes)):
            end=np.array(end);base=np.array(max((p for p in path if p[2]<=end[2]-.19),key=lambda p:p[2]))
            elbow=base+(end-base)*[.56,.6,.45];elbow[2]-=.035
            m.branch([base,elbow,end],.010 if birch else .014,bark)
            size=np.array(size)*[1.07,1.07,1.30]
            m.cluster(end,size,i%3,3 if kind!='birch' else 2,phase=i*.78)
            middle=elbow+(end-elbow)*.40
            m.foliage(middle,size*.78,(i+1)%3,i*.31)
            if i%2==0:
                tip=end+np.array([size[0]*.72,-size[1]*.6,-size[2]*.75 if birch else size[2]*.35])
                m.branch([elbow,tip],.006,bark,sides=4)
                m.foliage(tip,np.array(size)*.53,1,i*.47)
    elif kind=='pine':
        path=[[0,0,0],[-.025,.01,.25],[.035,-.01,.49],[.01,.035,.70],[-.055,.01,.89]]
        m.branch(path,.028)
        ends=[[-.30,-.02,.72],[.22,-.03,.94],[-.06,.10,1.01],[.33,.15,.76],[-.24,-.16,.94],[.13,-.14,.64]]
        for i,end in enumerate(ends):
            end=np.array(end);base=np.array(path[2 if i%2==0 else 3]);elbow=base+(end-base)*.54;elbow[2]-=.08
            m.branch([base,elbow,end],.014)
            m.cluster(end,[.19,.17,.10+(i%3)*.012],3,3,i*1.2)
            m.foliage(elbow+(end-elbow)*.5,[.14,.13,.095],3,i*.7)
    elif kind=='spruce':
        m.branch([[0,0,0],[.003,-.002,.35],[-.004,.003,.70],[0,0,1.010]],.018,role='trunk')
        # One ascending helix, not a stack of horizontal whorls. A bounded
        # perturbation keeps neighbouring steps ordered and the cone legible.
        count=SPRUCE_HELIX['boughs']
        for i in range(count):
            jitter=r.uniform(-1,1)*SPRUCE_HELIX['heightStepJitter'] if 0<i<count-1 else 0.
            step=(i+jitter)/(count-1);u=1-(1-step)**SPRUCE_HELIX['heightExponent']
            z=SPRUCE_HELIX['baseHeight']+(1.01-SPRUCE_HELIX['baseHeight'])*u
            a=.34+np.deg2rad(i*SPRUCE_HELIX['stepDegrees']+r.uniform(-1,1)*SPRUCE_HELIX['azimuthJitterDegrees'])
            reach=(.34*(1-u)**.80+.014)*r.uniform(.80,1.24)
            width=reach*r.uniform(.66,.98)
            thickness=reach*r.uniform(.40,.56)
            droop=reach*r.uniform(.025,.13)
            anchor=np.r_[r.uniform(-.009,.009,2)*(1-u),z]
            pitch=r.uniform(-.10,.18);roll=r.uniform(-.24,.24)
            end=m.spruce_bough(anchor,reach,width,thickness,a,droop,pitch,roll)
            m.components[-1]['spiralIndex']=i
            m.branch([anchor,end],.0035*(1-u)+.0006,sides=4)
    elif kind=='thuja':
        path=[[0,0,0],[.005,-.008,.26],[-.015,.01,.53],[.012,0,.79],[-.008,.009,1.04]]
        m.branch(path,.025,role='trunk')
        # Upright overlapping sprays, neither horizontal spruce tiers nor a
        # single rotational cone. Large lobes are staggered around the stem.
        sprays=[(.30,.16,.115,.29),(.38,.18,.125,.31),(.45,.15,.125,.33),
            (.54,.16,.12,.32),(.64,.135,.11,.30),(.72,.12,.11,.30),
            (.80,.10,.10,.27),(.87,.085,.088,.24),(.95,.060,.075,.21)]
        for i,(z,reach,width,height) in enumerate(sprays):
            angle=i*2.38+r.uniform(-.25,.25)
            center=np.array([np.cos(angle)*reach,np.sin(angle)*reach,z])
            base=np.array([0.,0.,max(.14,z-.24)])
            elbow=base+(center-base)*[.65,.65,.35]
            m.branch([base,elbow,center+[0,0,.06]],.008*(1-z*.6),sides=4)
            m.foliage(center,[width,width*r.uniform(.78,.95),height],3,angle,notch=.80)
        # Fill the central axis with three unequal volumes, leaving shallow
        # clefts between the outer sprays instead of holes through the column.
        for i,(z,width,height) in enumerate([(.33,.14,.31),(.62,.13,.34),(.97,.07,.24)]):
            m.foliage([.012*(-1)**i,-.012,z],[width,width*.9,height],3,i*.9,notch=.82)
    elif kind=='growth':
        stems=[([-.038,.012,0],[-.105,.018,.88],.014),
               ([.032,.024,0],[.125,.075,.72],.012),
               ([.010,-.035,0],[.008,-.105,1.01],.013)]
        for i,(root,tip,radius) in enumerate(stems):
            root=np.array(root);tip=np.array(tip)
            elbow=root+(tip-root)*[.40,.40,.48]
            m.branch([root,elbow,tip],radius,role='trunk')
            m.foliage(tip,[.145,.125,.20],i%3,i*1.27)
            for j,zfactor in enumerate([.64,.78]):
                angle=i*2.05+j*2.55+.4
                base=root+(tip-root)*(zfactor-.19)
                end=root+(tip-root)*zfactor+np.array([np.cos(angle)*.14,np.sin(angle)*.14,-.02])
                bend=base+(end-base)*[.52,.52,.40]
                m.branch([base,bend,end],radius*.50,sides=4)
                m.foliage(end,[.13,.115,.155 if j==0 else .18],(i+j+1)%3,angle)
    elif kind=='low':
        path=[[0,0,0],[.018,-.005,.16],[-.025,.015,.33],[.035,.018,.58],[.010,.005,.80]]
        m.branch(path,.034,role='trunk')
        ends=[[-.28,-.015,.63],[.26,.10,.73],[-.10,.025,.96],[.07,-.18,.84],
              [-.18,.17,.79],[.29,-.14,.53],[-.25,-.13,.48],[.16,.20,.58]]
        for i,end in enumerate(ends):
            end=np.array(end);base=np.array(path[2 if i%3 else 1])
            elbow=base+(end-base)*[.54,.54,.43]
            m.branch([base,elbow,end],.012 if i<5 else .009,sides=5)
            size=np.array([.185,.16,.19])*r.uniform(.91,1.12,3)
            m.foliage(end,size,i%3,i*.83)
            if i in (0,2,5):
                shoulder=end+np.array([-.06 if i%2 else .08,.05,-.065])
                m.foliage(shoulder,size*[.80,.85,.78],(i+1)%3,i*1.13)
    elif kind=='bush':
        ends=[[-.31,0,.30],[.22,-.03,.39],[-.1,.1,.49],[.04,-.18,.36],[.31,.14,.23],[-.26,-.15,.18],[.02,.20,.27]]
        for i,end in enumerate(ends):
            m.branch([[r.uniform(-.045,.045),r.uniform(-.03,.03),0],[end[0]*.40,end[1]*.50,end[2]*.38],end],.017)
            m.cluster(end,[.20,.18,.20],i%3,3,i*.8)
            mid=np.array(end)*.7;mid[2]=max(.10,end[2]-.12)
            m.foliage(mid,[.15,.13,.16],(i+1)%3,i*.5)
    else:
        raise ValueError('Unknown study model: '+kind)
    p=np.asarray(m.tris)[:,:,[0,2,1]]*[1,1,-1]
    # Keep the measured source envelope, with roots at the original origin.
    lo=p.min((0,1));hi=p.max((0,1));target_lo=np.array(bounds['min']);target_hi=np.array(bounds['max'])
    for axis in (0,2):p[:,:,axis]=np.where(p[:,:,axis]<0,p[:,:,axis]*target_lo[axis]/lo[axis],p[:,:,axis]*target_hi[axis]/hi[axis])
    height_factor=.56 if kind=='bush' else 1.0
    p[:,:,1]=(p[:,:,1]-lo[1])/(hi[1]-lo[1])*(target_hi[1]-target_lo[1])*height_factor+target_lo[1]
    if kind in ('open','thuja','growth','low') and round_trunk:
        def fit(points):
            q=np.asarray(points)[...,[0,2,1]]*[1,1,-1]
            for axis in (0,2):q[...,axis]*=np.where(q[...,axis]<0,target_lo[axis]/lo[axis],target_hi[axis]/hi[axis])
            q[...,1]=(q[...,1]-lo[1])/(hi[1]-lo[1])*(target_hi[1]-target_lo[1])*height_factor+target_lo[1]
            return q
        for part in m.components:
            if part.get('role')!='trunk':continue
            rings,sections=round_trunk_sections(fit(part['rings']),fit(part['centerline']))
            p[part['start']:part['end']]=rings.reshape(-1,3)[np.asarray(part['faces'])]
            part['roundSections']=sections
    # Enlarge each leaf/needle fragment only AFTER fitting the original tree.
    # Refitting the full envelope after this step would shrink wood and undo
    # the requested growth. Preserve each fragment's attachment centre.
    for part in m.components:
        if part['kind']!='foliage':continue
        center=np.array(part['center'])[[0,2,1]]*[1,1,-1]
        for axis in (0,2):
            center[axis]*=target_lo[axis]/lo[axis] if center[axis]<0 else target_hi[axis]/hi[axis]
        center[1]=(center[1]-lo[1])/(hi[1]-lo[1])*(target_hi[1]-target_lo[1])*height_factor+target_lo[1]
        part['pivot']=center.tolist()
        fragment=p[part['start']:part['end']]
        fragment[:]=center+(fragment-center)*FOLIAGE_SCALES.get(kind,FOLIAGE_SCALE)
    n=np.cross(p[:,1]-p[:,0],p[:,2]-p[:,0]);n/=np.linalg.norm(n,axis=1,keepdims=True)
    # Translate whole foliage fragments towards the vertical root axis.
    # Do this after envelope fitting: no resizing, vertical motion or refit.
    # A translation preserves the already calculated normals exactly.
    radial=CROWN_RADIAL_FACTORS.get(kind,1.) if crown_factor is None else float(crown_factor)
    if radial!=1.:
        for part in m.components:
            if part['kind']!='foliage':continue
            pivot=np.asarray(part['pivot']);delta=np.array([pivot[0]*(radial-1),0.,pivot[2]*(radial-1)])
            p[part['start']:part['end']]+=delta
            part['pivotBeforeInward']=pivot.tolist();part['pivot']=(pivot+delta).tolist()
    return np.concatenate([p,np.repeat(n[:,None,:],3,axis=1),np.zeros((len(p),3,2))],2),np.array(m.mats,dtype=np.uint32),m.components

def validate(a,parts):
    from collections import Counter
    assert np.isfinite(a).all()
    for part in parts:
        t=a[part['start']:part['end'],:,:3];edges=Counter()
        assert np.sum(t[:,0]*np.cross(t[:,1],t[:,2]))>1e-9
        assert np.all(np.linalg.norm(np.cross(t[:,1]-t[:,0],t[:,2]-t[:,0]),axis=1)>1e-9)
        for tri in np.round(t,8):
            v=list(map(tuple,tri))
            for x,y in ((v[0],v[1]),(v[1],v[2]),(v[2],v[0])):edges[x,y]+=1
        assert all(n==1 and edges[y,x]==1 for (x,y),n in edges.items())

def export(folder,attrs,mats,materials):
    folder.mkdir(parents=True,exist_ok=True)
    meta=pack(attrs,mats,folder/'mesh-000.bin.gz')
    manifest=dict(origin=[0,0,0],materials=materials,textures={},chunks=[dict(id=0,name=folder.name,file='mesh-000.bin.gz',**meta)],instances=[dict(mesh=0,matrix=[1,0,0,0,0,1,0,0,0,0,1,0])])
    (folder/'scene.json').write_text(json.dumps(manifest,ensure_ascii=False))
    np.savez(folder/'geometry.npz',attributes=attrs,materials=mats)
    export_glb(manifest,folder)
    return meta

def main(only=None):
    source=json.loads(SOURCE.read_text());source={c['name']:c for c in source['chunks']}
    materials=[dict(name=n,family='vegetation',color=c,roughness=.94,metallic=0,ior=1.5,kind=1,texture=None,alphaCutoff=0) for n,c in PALETTE]
    existing=json.loads((OUT/'catalog.json').read_text()) if only else {}
    rows=[]
    for kind,label,description,template,old in MODELS:
        if only and kind!=only:
            prior=next((r for r in existing['models'] if r['id']==kind),None)
            if prior is not None:rows.append(prior)
            continue
        a,m,parts=make(kind,source[template]['bounds']);validate(a,parts)
        assert np.array_equal(a,make(kind,source[template]['bounds'])[0]),'Generator must be deterministic'
        meta=export(OUT/kind,a,m,materials)
        old_data=np.load(ROOT/f'web-preview/prototype/tiles/assets-km1-botanical/library/{old}/geometry.npz')
        old_meta=export(OUT/(kind+'-previous'),old_data['attributes'],old_data['materials'],materials)
        row=dict(id=kind,label=label,description=description,sourceTemplate=template,sourceBounds=source[template]['bounds'],triangles=meta['triangles'],bounds=meta['bounds'],previousBounds=old_meta['bounds'],previousTriangles=old_meta['triangles'],components=len(parts),foliageGroups=sum(p['kind']=='foliage' for p in parts),foliageScale=FOLIAGE_SCALES.get(kind,FOLIAGE_SCALE))
        if kind in NEW_STUDIES:
            study=NEW_STUDIES[kind]
            row.update(studyLabel=study['studyLabel'],defaultSmoothingAngle=study['smoothingAngle'],
                defaultFoliageColor=study['foliageColor'],defaultCurvatureStrength=100,
                scaleDescription='Крупные фрагменты увеличены на 20% после подгонки базового габарита к шаблону 2ГИС. Стволы имеют круглые сужающиеся сечения. Доступны размер, повороты, Boolean и упрощение.')
        if kind=='open':
            prior_path=OUT/'open-selected-before-trunk/scene.json'
            if prior_path.exists():
                prior=json.loads(prior_path.read_text())['chunks'][0]
                row['comparisons']=[dict(value='open-selected-before-trunk',folder='open-selected-before-trunk',label='Выбранная крона · прежний ствол',description='Точная выбранная в мастерской форма до исправления овальных сечений ствола.',triangles=prior['triangles'],bounds=prior['bounds'])]
        if kind=='birch':
            row.update(studyLabel='Листва берёзы +30%',scaleDescription='Каждый фрагмент листвы увеличен ещё на 30% относительно предыдущей пробы. Ствол и ветви прежние.')
            prior_path=OUT/'birch-before-growth/scene.json'
            if prior_path.exists():
                prior=json.loads(prior_path.read_text())['chunks'][0]
                row['comparisons']=[dict(value='birch-before-growth',folder='birch-before-growth',label='Берёза до увеличения',description='Предыдущая проба берёзы до дополнительного увеличения листвы на 30%.',triangles=prior['triangles'],bounds=prior['bounds'])]
        if kind=='pine':
            reduction=round((1-CROWN_RADIAL_FACTORS['pine'])*100)
            row.update(studyLabel=f'Крона компактнее · центры −{reduction}%',crownRadialFactor=CROWN_RADIAL_FACTORS['pine'],
                scaleDescription=f'Центры всех объёмов хвои сдвинуты на {reduction}% ближе к вертикальной оси ствола относительно исходной сосны. Высоты, размеры и формы объёмов, ствол и ветви сохранены.')
            prior_path=OUT/'pine-before-inward/scene.json'
            if prior_path.exists():
                prior=json.loads(prior_path.read_text())['chunks'][0]
                row['comparisons']=[dict(value='pine-before-inward',folder='pine-before-inward',label='Сосна · до сближения хвои',description='Предыдущая сосна до сдвига центров хвои к оси ствола; размеры объёмов те же.',triangles=prior['triangles'],bounds=prior['bounds'])]
            step_path=OUT/'pine-inward-step-1/scene.json'
            if step_path.exists() and CROWN_RADIAL_FACTORS['pine']!=.70:
                prior=json.loads(step_path.read_text())['chunks'][0]
                row.setdefault('comparisons',[]).append(dict(value='pine-inward-step-1',folder='pine-inward-step-1',label='Сосна · первый сдвиг на 30%',description='Первый шаг: расстояния центров хвои до оси составляют 70% от исходных.',triangles=prior['triangles'],bounds=prior['bounds']))
        if kind=='spruce':
            row.update(studyLabel='Ель · крупные объёмные лапы',crownLayout='ascending-helix',
                spiral=SPRUCE_HELIX,scaleDescription='Лапы увеличены ещё на 20% и утолщены по высоте. Редкая спираль, разные наклоны и неровные края.')
            prior_path=OUT/'spruce-before-spiral/scene.json'
            if prior_path.exists():
                prior=json.loads(prior_path.read_text())['chunks'][0]
                row['comparisons']=[dict(value='spruce-before-spiral',folder='spruce-before-spiral',label='Ель · прежние объёмные фрагменты',
                    description='Предыдущая проба ели с раздельными объёмными группами хвои, до спирального расположения плоских лап.',triangles=prior['triangles'],bounds=prior['bounds'])]
            fine_path=OUT/'spruce-spiral-fine/scene.json'
            if fine_path.exists():
                fine=json.loads(fine_path.read_text())['chunks'][0]
                row.setdefault('comparisons',[]).insert(0,dict(value='spruce-spiral-fine',folder='spruce-spiral-fine',label='Ель · мелкая регулярная спираль',
                    description='Первая спиральная проба: 72 небольшие лапы и около 14 витков.',triangles=fine['triangles'],bounds=fine['bounds']))
            flat_path=OUT/'spruce-large-flat/scene.json'
            if flat_path.exists():
                flat=json.loads(flat_path.read_text())['chunks'][0]
                row.setdefault('comparisons',[]).insert(0,dict(value='spruce-large-flat',folder='spruce-large-flat',label='Ель · крупные плоские лапы',
                    description='Предыдущая укрупнённая нерегулярная спираль до дополнительного увеличения и утолщения лап.',triangles=flat['triangles'],bounds=flat['bounds']))
        rows.append(row)
    result=dict(version='shape-study-03',foliageScale=FOLIAGE_SCALE,foliageScales=FOLIAGE_SCALES,status='review-only',integrated=False,models=rows,materials=materials,
        policy='Branch-led asymmetry, non-convex closed foliage groups, deliberate gaps and uneven lower edge. Baseline tree envelopes and shrub footprint match source templates; baseline shrub height is 56% of source. Leaf/needle fragments scale about their own centres after fitting, without changing wood. Default scale 120%; birch 156%; spruce 194.4% after its procedural shape fitting. No production generator/config is modified.',validation=dict(passed=True,closedComponents=True,positiveVolume=True,finiteVertices=True,repeatable=True))
    (OUT/'catalog.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
    print(json.dumps(rows,ensure_ascii=False,indent=2))

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument('--model',choices=[m[0] for m in MODELS])
    main(parser.parse_args().model)
