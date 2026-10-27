"""Protect roof materials, authored models and stripe continuity across tiles."""
import tempfile
from pathlib import Path
import numpy as np
from PIL import Image
from flat_roofs import encode_faces
from facade_bands import building_bases, select_faces, apply_faces, make_material, make_texture


rows = [dict(id='body',category='building',sourceLayer='Dwelling_house_1',sourceBuildingId='1',placement=dict(targetBaseM=12.)),
        dict(id='roof',category='building',sourceLayer='Dwelling_house_roof_1',sourceBuildingId='1',placement=dict(targetBaseM=12.)),
        dict(id='authored-body',category='building',sourceLayer='Dwelling_house_2',sourceBuildingId='2',placement=dict(targetBaseM=12.)),
        dict(id='model',category='landmark',sourceBuildingId='2'),
        dict(id='canopy',category='building',sourceLayer='Canopy_3',sourceBuildingId='3',placement=dict(targetBaseM=12.))]
bases = building_bases(rows,[0,0,2.])
assert bases == {'body':10.,'roof':10.}
xyz = np.array([[[0,10,0],[3,10,0],[3,16,0]],
                [[0,16,0],[3,16,0],[0,16,3]],  # flat cap
                [[0,16,0],[3,18,0],[0,16,3]],  # sloping roof
                [[0,10,0],[3,10,0],[3,16,0]]],dtype='<f4')
corners = encode_faces(xyz,75)
unique,inverse = np.unique(corners.reshape(-1,8).view('V32').ravel(),return_inverse=True)
v = unique.view('<u4').reshape(-1,8); ix = inverse.astype('<u4').reshape(-1,3)
data = v.tobytes()+ix.tobytes()
chunk = dict(vertexBytes=v.nbytes,triangles=4,sourceObjectRanges=[dict(id='body',first=0,count=2),dict(id='roof',first=2,count=1),dict(id='authored-body',first=3,count=1)])
phase = select_faces(data,chunk,bases,[75])
assert np.array_equal(np.isfinite(phase),[True,False,False,False])
tail = b'unchanged BVH and lineage'
updated,vb = apply_faces(data+tail,v.nbytes,ix.nbytes,phase,151)
assert updated[-len(tail):] == tail
nv = np.frombuffer(updated[:vb],'<u4').reshape(-1,8); ni = np.frombuffer(updated[vb:vb+ix.nbytes],'<u4').reshape(-1,3)
after = nv[ni]; before = v[ix]
assert np.array_equal(after[1:],before[1:])
assert np.array_equal(after[:,:,[0,1,2,3,7]],before[:,:,[0,1,2,3,7]])
assert np.allclose(after.view('<f4')[0,:,5],[0,0,2])
# A split tile face starts at y=13, not at the building base. UV must continue.
tile_xyz = xyz[:1].copy();tile_xyz[:,:,1] += 3
t = encode_faces(tile_xyz,75).reshape(-1,8); ti = np.array([[0,1,2]],'<u4')
out,tvb = apply_faces(t.tobytes()+ti.tobytes(),t.nbytes,ti.nbytes,np.array([10.]),151)
tv = np.frombuffer(out[:tvb],'<f4').reshape(-1,8);tx = np.frombuffer(out[tvb:],'<u4').reshape(-1,3)
assert np.allclose(tv[tx,5],[[1,1,3]])
m = make_material(dict(color=[.2,.3,.4],roughness=.8))
assert np.allclose(m['color'],[.27,.405,.54]) and m['roughness']==.8
with tempfile.TemporaryDirectory() as folder:
    path = Path(folder)/'bands.png';make_texture(path);pixels=np.asarray(Image.open(path))
    assert np.array_equal(pixels[0],pixels[-1]) and pixels.min()<pixels.max()==255
print('PASS: house selection, unchanged flat/sloping roofs and landmarks, identical geometry, ground-relative UV across tiles, seamless bands.')
