"""Change selected triangle materials without changing any geometric corner."""
import numpy as np


def remap_many(raw, vertex_bytes, index_bytes, targets):
    """Per-face material IDs; -1 leaves a face completely unchanged."""
    count=0
    for material in np.unique(targets[targets>=0]):
        raw,vertex_bytes,added=remap(raw,vertex_bytes,index_bytes,targets==material,int(material))
        count+=added
    return raw,vertex_bytes,count


def remap(raw, vertex_bytes, index_bytes, selected, material):
    old=np.frombuffer(raw[:vertex_bytes],'<u4').reshape(-1,8)
    indices=np.frombuffer(raw[vertex_bytes:vertex_bytes+index_bytes],'<u4').reshape(-1,3)
    assert len(indices)==len(selected)
    if not np.any(selected):return raw,vertex_bytes,0
    vertices=old.copy();ix=indices.copy()
    changed=np.unique(ix[selected]);shared=np.intersect1d(changed,np.unique(ix[~selected]))
    # Split only shared material-boundary vertices; positions, normals and UVs
    # are copied exactly. Triangle order and existing BVH remain valid.
    if len(shared):
        lookup=np.arange(len(old),dtype='<u4');lookup[shared]=np.arange(len(old),len(old)+len(shared))
        vertices=np.concatenate([vertices,vertices[shared]])
        ix[selected]=lookup[ix[selected]]
    changed=np.unique(ix[selected])
    vertices[changed,6]=(vertices[changed,6]&np.uint32(0x80000000))|np.uint32(material)
    # Verify the entire expanded stream, including every unselected face.
    for start in range(0,len(ix),32768):
        expected=old[indices[start:start+32768]].copy()
        mask=selected[start:start+32768]
        expected[mask,:,6]=(expected[mask,:,6]&np.uint32(0x80000000))|np.uint32(material)
        assert np.array_equal(expected,vertices[ix[start:start+32768]])
    tail=raw[vertex_bytes+index_bytes:]
    return vertices.tobytes()+ix.tobytes()+tail,vertices.nbytes,len(shared)
