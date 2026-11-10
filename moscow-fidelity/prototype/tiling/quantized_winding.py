"""Keep generated faces in their normal's hemisphere after Float32 packing."""
import numpy as np


def reversed_faces(words, indices, *, batch_size=250_000):
    from object_geometry import decode_normals
    for start in range(0,len(indices),batch_size):
        ix=indices[start:start+batch_size]
        p=words.view('<f4')[ix,:3].astype(float)
        n=np.cross(p[:,1]-p[:,0],p[:,2]-p[:,0])
        normal=decode_normals(words[ix[:,0],3])
        ids=np.flatnonzero((np.linalg.norm(n,axis=1)>1e-9)&(np.sum(n*normal,axis=1)<0))
        if len(ids):yield start+ids


def repair_faces(words, indices, rows, original_triangles):
    """Only a proven conversion reversal is repaired; bad source data fails.

    The original corners must round exactly to the stored positions in their
    original order, with a positive original normal/winding dot product. The
    repair changes only the order of corners two and three, retaining every
    position, normal, UV, material, triangle and source face identity.
    """
    rows=np.asarray(rows,dtype=np.intp)
    original=np.asarray(original_triangles)
    assert original.shape==(len(rows),3,8)
    p=original[:,:,:3].astype(float)
    n=np.cross(p[:,1]-p[:,0],p[:,2]-p[:,0])
    dot=np.sum(n*original[:,0,3:6],axis=1)
    assert np.isfinite(dot).all() and np.all(dot>0),'Source face winding is invalid before quantization'
    stored=words.view('<f4')[indices[rows],:3]
    assert np.array_equal(p.astype('<f4'),stored),'Packed face is not the rounded source face'
    from object_geometry import decode_normals
    q=stored.astype(float);current=np.cross(q[:,1]-q[:,0],q[:,2]-q[:,0])
    normals=decode_normals(words[indices[rows,0],3])
    assert np.all(np.sum(current*normals,axis=1)<0),'Packed face is not reversed'
    indices[rows,1],indices[rows,2]=indices[rows,2].copy(),indices[rows,1].copy()
    return len(rows)


def repair_packed(words, indices, originals, *, batch_size=250_000):
    count=0
    for rows in reversed_faces(words,indices,batch_size=batch_size):
        source=originals[rows]
        p=source[:,:,:3].astype(float)
        dot=np.sum(np.cross(p[:,1]-p[:,0],p[:,2]-p[:,0])*source[:,0,3:6],axis=1)
        valid=np.isfinite(dot)&(dot>0)
        # pack also transports imported/smooth attributes. Leave inconsistent
        # input untouched so its normal audit can reject it; do not pretend it
        # was a rounding reversal or change the packer's existing input API.
        if valid.any():count+=repair_faces(words,indices,rows[valid],source[valid])
    return count
