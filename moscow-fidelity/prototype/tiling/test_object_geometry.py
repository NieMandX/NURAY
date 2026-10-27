import numpy as np
from object_geometry import clip_triangles

# Atlas UVs must remain attached while one roof crosses four transport tiles.
t=np.array([[[-2,3,-2,0,1,0,0,0],[4,3,-2,0,1,0,1,0],[-2,3,4,0,1,0,0,1]]],float)
parts=[]
for x in [-2,1]:
    for z in [-2,1]:
        tris,m=clip_triangles(t,np.array([17]),[x,z,x+3,z+3]);assert np.all(m==17)
        if len(tris):
            np.testing.assert_allclose(tris[:,:,6],(tris[:,:,0]+2)/6,atol=1e-12)
            np.testing.assert_allclose(tris[:,:,7],(tris[:,:,2]+2)/6,atol=1e-12)
            parts.extend(tris)
p=np.asarray(parts);area=np.linalg.norm(np.cross(p[:,1,:3]-p[:,0,:3],p[:,2,:3]-p[:,0,:3]),axis=1).sum()/2
assert abs(area-18)<1e-10
print('Passed: clipped facade/roof retains atlas UVs, material identity and total area.')
