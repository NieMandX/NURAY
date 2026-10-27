"""A shared roof/gable vertex must not recolour the gable or alter geometry."""
import numpy as np
from pitched_roofs import slope_mask, select_faces, roof_row
from material_remap import remap

# One sloping roof and a vertical gable share an edge; a horizontal cap stays.
vertices = np.zeros((5, 8), dtype='<u4')
vertices.view('<f4')[:, :3] = [[0, 2, 0], [0, 2, 4], [4, 4, 0], [0, 0, 0], [4, 2, 0]]
vertices[:, 6] = 75 | 0x80000000
ix = np.array([[0, 1, 2], [0, 2, 3], [0, 1, 4]], dtype='<u4')
data = vertices.tobytes() + ix.tobytes()
row = dict(id='roof', category='building', sourceLayer='Dwelling_house_roof_123', sourceBuildingId='123')
chunk = dict(vertexBytes=vertices.nbytes, sourceObjectRanges=[dict(id='roof', first=0, count=3)])
mask, counts = select_faces(data, chunk, {'roof': row})
assert mask.tolist() == [True, False, False] and counts == {'roof': 1}
assert np.array_equal(mask, slope_mask(vertices.view('<f4')[ix[:, ::-1], :3]))
for category, layer in [('building','Dwelling_house_123'),('landmark','Dwelling_house_roof_123'),('building','Canopy_123')]:
    assert not roof_row(dict(row, category=category, sourceLayer=layer))
after, vb, split = remap(data + b'unchanged-bvh-and-lineage', vertices.nbytes, ix.nbytes, mask, 149)
assert split == 3 and after[vb+ix.nbytes:] == b'unchanged-bvh-and-lineage'
v = np.frombuffer(after[:vb], '<u4').reshape(-1,8)
i = np.frombuffer(after[vb:vb+ix.nbytes], '<u4').reshape(-1,3)
expected = vertices[ix].copy(); expected[0,:,6] = 149 | 0x80000000
assert np.array_equal(v[i], expected)
assert not slope_mask(np.zeros((1,3,3))).any()
print('Passed: roof ownership, slope/winding, gables/caps exclusion, shared vertices, all attributes and BVH identity.')
