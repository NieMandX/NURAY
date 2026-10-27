"""Native accelerator parity against brute force, without scene assets."""
import math,random,struct,subprocess,tempfile,unittest
from pathlib import Path

def sub(a,b):return tuple(x-y for x,y in zip(a,b))
def dot(a,b):return sum(x*y for x,y in zip(a,b))
def cross(a,b):return (a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0])
def triangle(ro,rd,vertices,tri):
    a,b,c=[vertices[i] for i in tri];e1=sub(b,a);e2=sub(c,a);p=cross(rd,e2);det=dot(e1,p)
    if abs(det)<1e-12:return math.inf
    delta=sub(ro,a);x=dot(delta,p)/det
    if x<0 or x>1:return math.inf
    q=cross(delta,e1);y=dot(rd,q)/det
    if y<0 or x+y>1:return math.inf
    t=dot(e2,q)/det;return t if t>1e-6 else math.inf

class MergedTraceTest(unittest.TestCase):
    def test_complete_and_ray_equivalent(self):
        rng=random.Random(77);vertices=[];triangles=[]
        for i in range(160):
            x,z=rng.uniform(-5000,5000),rng.uniform(-5000,5000);y=rng.uniform(-2,70)
            start=len(vertices);vertices.extend([(x,y,z),(x+45,y+7,z),(x,y,z+42)]);triangles.append((start,start+1,start+2))
        with tempfile.TemporaryDirectory() as folder:
            folder=Path(folder);exe=folder/'bvh';source=folder/'mesh';out=folder/'out'
            subprocess.run(['clang++','-O2','-std=c++17',str(Path(__file__).with_name('merged_bvh.cpp')),'-o',str(exe)],check=True)
            vb=b''.join(struct.pack('<3f5I',*v,0,0,0,0,0) for v in vertices);ib=b''.join(struct.pack('<3I',*t) for t in triangles);source.write_bytes(vb+ib)
            subprocess.run([str(exe),str(source),'0',str(len(vb)),str(len(vb)),str(len(ib)),str(out)],check=True,capture_output=True)
            data=out.read_bytes();ordered=list(struct.iter_unpack('<3I',data[:len(ib)]));nodes=list(struct.iter_unpack('<3fI3fI',data[len(ib):]))
            self.assertEqual(sorted(ordered),triangles)
            # Round source geometry exactly as it is stored in the GLB.
            verts=[struct.unpack('<3f',vb[i:i+12]) for i in range(0,len(vb),32)]
            for v in verts[::3]:
                ro=(v[0]+7,200,v[2]+7);rd=(0,-1,0);expected=min(triangle(ro,rd,verts,t) for t in triangles)
                best=math.inf;n=0
                while n<len(nodes):
                    b=nodes[n];first,length=b[3],b[7];near=-math.inf;far=best
                    for axis in range(3):
                        if rd[axis]==0:
                            if not b[axis]<=ro[axis]<=b[axis+4]:far=-math.inf
                        else:
                            a=(b[axis]-ro[axis])/rd[axis];c=(b[axis+4]-ro[axis])/rd[axis];near=max(near,min(a,c));far=min(far,max(a,c))
                    if max(near,1e-6)>far:n=n+1 if length else first;continue
                    if length:best=min(best,min(triangle(ro,rd,verts,t) for t in ordered[first:first+length]))
                    n+=1
                self.assertEqual(best,expected)

if __name__=='__main__':unittest.main()
