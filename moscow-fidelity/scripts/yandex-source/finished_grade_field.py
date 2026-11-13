"""Continuous civil surface between streets and the untouched natural terrain.

Nearest-road heights are discontinuous on Voronoi boundaries. Solve the
off-road collar as a harmonic surface instead: road interiors and the outer
natural terrain are fixed, and intermediate heights have no local extrema.
This is visual grading, not a replacement for the survey measurements.
"""
import hashlib,json
import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.linalg import cg
from scipy.interpolate import RegularGridInterpolator


def harmonic_fill(height, unknown):
    height=np.asarray(height,dtype=float);unknown=np.asarray(unknown,dtype=bool)
    assert not (unknown[0].any() or unknown[-1].any() or unknown[:,0].any() or unknown[:,-1].any())
    ids=np.full(height.shape,-1,dtype=np.int32);ids[unknown]=np.arange(unknown.sum())
    y,x=np.nonzero(unknown);n=len(y)
    if not n:return height.copy(),dict(unknownVertices=0,solverInfo=0,residualMaxM=0.)
    row=[np.arange(n)];col=[np.arange(n)];data=[np.full(n,4.)];rhs=np.zeros(n)
    for dy,dx in ((-1,0),(1,0),(0,-1),(0,1)):
        j=ids[y+dy,x+dx];free=j>=0
        row.append(np.flatnonzero(free));col.append(j[free]);data.append(np.full(free.sum(),-1.))
        rhs[~free]+=height[y[~free]+dy,x[~free]+dx]
    matrix=coo_matrix((np.concatenate(data),(np.concatenate(row),np.concatenate(col))),shape=(n,n)).tocsr()
    result,info=cg(matrix,rhs,x0=height[unknown],rtol=1e-10,atol=1e-9,maxiter=3000)
    error=float(np.max(abs(matrix@result-rhs)));assert info==0 and error<1e-5,(info,error)
    out=height.copy();out[unknown]=result
    return out,dict(unknownVertices=n,solverInfo=int(info),residualMaxM=error)


def input_signature(road,terrain,alt,center,outer):
    digest=hashlib.sha256(b'finished-harmonic-2m-30m-v1')
    for value in (road.xy,road.z,terrain.triangles,[alt,*center,outer]):
        digest.update(np.ascontiguousarray(value,dtype='<f8').tobytes())
    return digest.hexdigest()


def load_or_build(path, road, terrain, alt, center, outer):
    from survey_terrain import safe_sample
    signature=input_signature(road,terrain,alt,center,outer)
    receipt=path.with_suffix('.json')
    valid=path.exists() and receipt.exists() and json.loads(receipt.read_text()).get('inputSignature')==signature
    if not valid:
        step=2.;extent=np.ceil((outer+40)/step)*step
        x=np.arange(center[0]-extent,center[0]+extent+step,step)
        y=np.arange(center[1]-extent,center[1]+extent+step,step)
        xx,yy=np.meshgrid(x,y);xy=np.column_stack([xx.ravel(),yy.ravel()])
        natural=safe_sample(terrain,xy)-alt;z=natural.copy();distance=np.full(len(xy),100.)
        domain=np.linalg.norm(xy-center,axis=1)<outer+32
        selected=np.flatnonzero(domain)
        for start in range(0,len(selected),20000):
            i=selected[start:start+20000];d,h,off=road.sample(xy[i]);distance[i]=off
            fixed=off<1e-5;z[i[fixed]]=h[fixed]+d[fixed]-.035
        unknown=(distance>1e-5)&(distance<30)&domain
        z,report=harmonic_fill(z.reshape(xx.shape),unknown.reshape(xx.shape))
        np.savez_compressed(path,x=x,y=y,height=z)
        receipt.write_text(json.dumps(dict(method='harmonic off-road collar',inputSignature=signature,gridStepM=step,collarM=30,**report),indent=2)+'\n')
        print('CONTINUOUS FINISHED GRADE',report,flush=True)
    data=np.load(path)
    field=RegularGridInterpolator((data['y'],data['x']),data['height'],bounds_error=False,fill_value=np.nan)
    return lambda xy:field(np.asarray(xy)[:,::-1])
