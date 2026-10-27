"""Small replaceable NURAY street-object library, metres, renderer Y-up.

These are our display models, not surveyed reconstructions. Shape and material
defaults live here; source identity/placement never depends on triangle order.
"""
import math
import numpy as np

# Align the replacement template's front with the provider's local +Z.
# This is a library convention, never a correction to a source map angle.
TEMPLATE_YAW = dict.fromkeys(['bench1','bench2','swing','swing2','swing3'],180)

MATERIALS = [
    dict(name='Город · окрашенный металл',color=[.075,.095,.11],roughness=.48,metallic=.65),
    dict(name='Город · дерево',color=[.27,.14,.057],roughness=.76,metallic=0),
    dict(name='Город · бетон',color=[.36,.38,.37],roughness=.88,metallic=0),
    dict(name='Город · стекло',color=[.12,.21,.24],roughness=.15,metallic=.35),
    dict(name='Город · светлый металл',color=[.54,.56,.55],roughness=.38,metallic=.7),
    dict(name='Город · охра',color=[.49,.23,.035],roughness=.65,metallic=.05),
    dict(name='Город · зелёная краска',color=[.055,.20,.14],roughness=.65,metallic=.1),
    dict(name='Город · синяя краска',color=[.045,.16,.28],roughness=.65,metallic=.1),
    dict(name='Город · вода фонтана',color=[.05,.16,.20],roughness=.12,metallic=0),
]
for m in MATERIALS:m.update(family='street',ior=1.5,kind=1,alphaCutoff=0)

class Mesh:
    def __init__(self):self.faces=[];self.materials=[]
    def face(self,p,mat):
        p=np.asarray(p,float);normal=np.cross(p[1]-p[0],p[2]-p[0]);length=np.linalg.norm(normal)
        if length<1e-10:return
        normal/=length
        tangent=(p[1]-p[0])/np.linalg.norm(p[1]-p[0]);bitangent=np.cross(normal,tangent)
        uv=np.array([[0,0],[np.linalg.norm(p[1]-p[0]),0],[(p[2]-p[0])@tangent,(p[2]-p[0])@bitangent]])
        self.faces.append(np.column_stack((p,np.tile(normal,(3,1)),uv)));self.materials.append(mat)
    def quad(self,p,mat):self.face([p[0],p[1],p[2]],mat);self.face([p[0],p[2],p[3]],mat)
    def face_batch(self,triangles,mat):
        """Same per-face metric UVs and winding, with one NumPy dispatch per batch.

        A fence has hundreds of thousands of identical prism operations. Keep
        its topology intact while avoiding twelve Python/NumPy calls per post.
        """
        p=np.asarray(triangles,float).reshape(-1,3,3)
        d=p[:,1]-p[:,0];e=p[:,2]-p[:,0]
        normal=np.cross(d,e);length=np.linalg.norm(normal,axis=1)
        keep=length>=1e-10
        p,d,e,normal,length=p[keep],d[keep],e[keep],normal[keep],length[keep]
        if not len(p):return
        normal/=length[:,None]
        edge=np.linalg.norm(d,axis=1);tangent=d/edge[:,None]
        bitangent=np.cross(normal,tangent)
        uv=np.zeros((len(p),3,2));uv[:,1,0]=edge
        uv[:,2,0]=np.sum(e*tangent,axis=1);uv[:,2,1]=np.sum(e*bitangent,axis=1)
        faces=np.concatenate((p,np.broadcast_to(normal[:,None,:],p.shape),uv),axis=2)
        self.faces.extend(faces);self.materials.extend([mat]*len(faces))
    def box(self,center,size,mat=0):
        c=np.asarray(center);h=np.asarray(size)/2
        v=np.array([c+h*[1 if b&(1<<k) else -1 for k in range(3)] for b in range(8)])
        for ids in [(0,4,6,2),(1,3,7,5),(0,1,5,4),(2,6,7,3),(0,2,3,1),(4,5,7,6)]:self.quad(v[list(ids)],mat)
    def beam(self,a,b,r,mat=0,sides=8,r2=None):
        a=np.asarray(a,float);b=np.asarray(b,float);d=b-a;length=np.linalg.norm(d)
        if length<1e-8:return
        d/=length;u=np.cross(d,[0,1,0] if abs(d[1])<.9 else [1,0,0]);u/=np.linalg.norm(u);v=np.cross(d,u)
        rr=r if r2 is None else r2
        one=[a+r*(math.cos(t)*u+math.sin(t)*v) for t in np.arange(sides)*2*math.pi/sides]
        two=[b+rr*(math.cos(t)*u+math.sin(t)*v) for t in np.arange(sides)*2*math.pi/sides]
        for i in range(sides):
            j=(i+1)%sides;self.quad([one[i],one[j],two[j],two[i]],mat)
            self.face([a,one[j],one[i]],mat);self.face([b,two[i],two[j]],mat)
    def ring(self,r,inner,y,h,mat=2,n=24):
        for i in range(n):
            a=i*2*math.pi/n;b=(i+1)*2*math.pi/n
            pts=[[q*math.cos(t),yy,q*math.sin(t)] for yy in [y,y+h] for q in [r,inner] for t in [a,b]]
            for ids in [(4,5,1,0),(3,7,6,2),(6,7,5,4),(1,3,2,0)]:self.quad(np.asarray(pts)[list(ids)],mat)
    def arrays(self):return np.asarray(self.faces,float),np.asarray(self.materials,np.uint32)

def bench(m,back=True):
    for x in [-.7,.7]:
        for z in [-.19,.19]:m.beam([x,0,z],[x,.46,z],.045)
        m.box([x,.42,0],[.09,.09,.6])
    for z in np.linspace(-.24,.24,5):m.box([0,.5,z],[1.9,.07,.085],1)
    if back:
        for x in [-.7,.7]:m.beam([x,.42,.25],[x,1.05,.35],.035)
        for y in [.7,.86,1.02]:m.box([0,y,.32],[1.9,.11,.065],1)

def model(name):
    m=Mesh()
    if name.startswith('lamppost'):
        high=name in ['lamppost1','lamppost2'];double=name in ['lamppost2','lamppost4'];h=6.09 if high else 3.97
        m.beam([0,0,0],[0,h-.2,0],.095,r2=.055);m.beam([0,0,0],[0,.28,0],.18,2)
        if high or double:
            for side in ([1,-1] if double else [1]):
                m.beam([0,h-.65,0],[0,h,side*1.2],.045)
                m.box([0,h-.03,side*1.35],[.38,.14,.65],4)
                m.box([0,h-.11,side*1.35],[.30,.025,.50],3)
        else:
            m.box([0,h-.18,0],[.52,.40,.52],3);m.box([0,h+.045,0],[.65,.075,.65])
    elif name in ['bench1','bench2']:bench(m,name=='bench1')
    elif name=='busstation':
        for x in [-2.65,2.65]:
            for z in [-.7,.7]:m.beam([x,0,z],[x,2.35,z],.045)
        # Provider angles expect the shelter entrance toward local +Z.
        # Keep this in the shared template, not as per-stop rotation overrides.
        m.box([0,2.39,0],[5.7,.13,1.8]);m.box([0,1.3,-.72],[5.2,1.8,.035],3)
        for x in [-2.67,2.67]:m.box([x,1.25,0],[.035,1.8,1.4],3)
        m.box([0,.50,-.38],[3.2,.09,.4],1)
        for x in [-1.15,1.15]:m.box([x,.24,-.38],[.12,.48,.3])
    elif name=='porch':
        m.box([0,1.35,.045],[1.15,2.6,.09],3)
        for x in [-.63,.63]:m.box([x,1.4,0],[.1,2.8,.18],2)
        m.box([0,2.74,0],[1.36,.12,.18],2);m.box([0,.06,-.22],[1.6,.12,.60],2)
        m.box([0,1.36,-.02],[.045,2.45,.1]);m.beam([.35,1.1,-.08],[.35,1.38,-.08],.02,4)
    elif name in ['swing2','swing3']:
        for x in [-1.6,1.6]:
            for z in [-.95,.95]:m.beam([x,0,z],[x,2.6,0],.07)
        m.beam([-1.75,2.6,0],[1.75,2.6,0],.08,5)
        for x in ([-.85,.85] if name=='swing2' else [0]):
            w=.48 if name=='swing2' else 1.6
            for xx in [x-w/2,x+w/2]:m.beam([xx,.55,0],[xx,2.53,0],.017,4)
            m.box([x,.52,0],[w+.1,.09,.42],1)
            if name=='swing3':m.box([x,.8,.22],[w+.1,.55,.07],1)
    elif name=='slide2':
        for x in [-.7,.7]:
            for z in [-.7,.7]:m.beam([x,0,z],[x,2.15,z],.065,1)
        m.box([0,1.4,0],[1.55,.12,1.55],5)
        for x in [-.7,.7]:m.beam([x,2.1,-.7],[x,2.1,.7],.04,6)
        for z in [-.7,.7]:m.beam([-.7,2.1,z],[.7,2.1,z],.04,6)
        m.quad([[-.5,1.45,-.7],[.5,1.45,-.7],[.5,.08,-3],[-.5,.08,-3]],7)
        for x in [-.52,.52]:m.beam([x,1.55,-.7],[x,.18,-3],.06,5)
        for y in np.linspace(.18,1.4,6):m.box([0,y,.7+(1.4-y)*.65],[1,.08,.22],1)
    elif name=='tabletennis':
        m.box([0,.76,0],[2.74,.08,1.525],7)
        for x in [-.9,.9]:
            for z in [-.5,.5]:m.box([x,.36,z],[.06,.72,.06])
        m.box([0,.88,0],[.025,.16,1.65],4)
    elif name in ['workout','gyms']:
        for x,h in [(-1.4,2.1),(0,2.6),(1.4,2.1)]:m.beam([x,0,0],[x,h,0],.065,6)
        m.beam([-1.4,2.1,0],[0,2.1,0],.035,5);m.beam([0,2.5,0],[1.4,2.5,0],.035,5)
        if name=='gyms':
            for x in [-1.4,1.4]:
                m.box([x,.6,-.6],[.6,.09,.5],5);m.beam([x,0,0],[x,.6,-.6],.05)
        else:
            for y in np.arange(.35,2.1,.3):m.beam([-.65,y,0],[0,y,0],.025,4)
    elif name.startswith('fountain') or name=='fontain1_3_a':
        r=3.6 if name=='fountain2_a' else 1.8
        m.ring(r,r-.25,0,.42);m.beam([0,.30,0],[0,.315,0],r-.26,8,sides=32)
        m.beam([0,.1,0],[0,1.05,0],.18,2);m.ring(.65,.5,.95,.16)
    elif name=='pavilion1':
        for t in np.arange(6)*math.pi/3:m.beam([2*math.cos(t),0,2*math.sin(t)],[2*math.cos(t),2.7,2*math.sin(t)],.08,1)
        for t in np.arange(6)*math.pi/3:
            q=t+math.pi/3;m.face([[0,3.6,0],[2.3*math.cos(t),2.7,2.3*math.sin(t)],[2.3*math.cos(q),2.7,2.3*math.sin(q)]],6)
    elif name=='footballgate1':
        for x in [-1.5,1.5]:
            m.beam([x,0,0],[x,2,0],.05,4);m.beam([x,0,1],[x,2,0],.04,4)
        m.beam([-1.5,2,0],[1.5,2,0],.05,4);m.beam([-1.5,0,1],[1.5,0,1],.04,4)
    elif name=='barrier':
        for z in [-1.25,1.25]:m.beam([0,0,z],[0,1.35,z],.06,6)
        for y in [.35,.65,.95]:m.box([0,y,0],[.1,.22,2.6],5)
    elif name in ['boom','swing','trampoline']:
        if name=='boom':
            for z in [-1.6,1.6]:m.box([0,.5,z],[.25,1,.25],6)
            m.box([0,1,0],[.35,.10,3.2],5)
            for sign in [-1,1]:m.quad([[-.18,1,sign*1.6],[.18,1,sign*1.6],[.18,.03,sign*3.2],[-.18,.03,sign*3.2]],5)
        elif name=='swing':m.box([0,.5,0],[.4,.95,.5],6);m.box([0,.98,0],[.45,.10,3],5)
        else:
            m.quad([[-.7,.02,-1],[.7,.02,-1],[.7,1,0],[-.7,1,0]],5)
            m.quad([[-.7,1,0],[.7,1,0],[.7,.02,1],[-.7,.02,1]],5)
    else:raise ValueError(('Unknown street model',name))
    if name in TEMPLATE_YAW:
        for face in m.faces:
            face[:,[0,2,3,5]] *= -1  # Position and normal; pivot, Y and UV stay fixed.
    return m
