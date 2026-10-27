"""Exact line coverage with local buffers, bounded by relevant geometry."""
import numpy as np
import shapely as sh


def segments(geometry):
    coords,owners=sh.get_coordinates(sh.get_parts(geometry),return_index=True)
    if len(coords)<2:return np.empty(0,dtype=object)
    endpoints=np.stack((coords[:-1],coords[1:]),axis=1)[owners[:-1]==owners[1:]]
    return sh.linestrings(endpoints)


def side_lines(triangles):
    """Project vertical triangle edges without four copies per two-sided quad."""
    if not len(triangles):return np.empty(0,dtype=object)
    xy=np.asarray(triangles)[:,:,:2]
    pairs=np.array([[0,1],[1,2],[2,0]])
    distance=np.linalg.norm(xy[:,pairs[:,1]]-xy[:,pairs[:,0]],axis=2)
    chosen=pairs[distance.argmax(axis=1)]
    endpoints=xy[np.arange(len(xy))[:,None],chosen][distance.max(axis=1)>1e-6]
    flip=(endpoints[:,0,0]>endpoints[:,1,0])|((endpoints[:,0,0]==endpoints[:,1,0])&(endpoints[:,0,1]>endpoints[:,1,1]))
    endpoints[flip]=endpoints[flip,::-1]
    return sh.linestrings(np.unique(endpoints.reshape(-1,4),axis=0).reshape(-1,2,2))


def uncovered_linework(expected,observed,tolerance,batch_size=1024):
    """Same result as expected minus buffer(union(observed), tolerance).

    Only segments within that exact distance can cover a queried boundary.
    Keep complete nearby segments until after buffering: clipping them first
    invents endpoint gaps. Union the remainders to avoid duplicate accounting.
    """
    expected=segments(expected);observed=np.asarray(observed,dtype=object)
    tree=sh.STRtree(observed);missing=[]
    for offset in range(0,len(expected),batch_size):
        group=expected[offset:offset+batch_size]
        hits=tree.query(group,predicate='dwithin',distance=tolerance)[1]
        coverage=sh.union_all(observed[np.unique(hits)]).buffer(tolerance)
        missing.append(sh.union_all(group).difference(coverage))
    return sh.union_all(missing)
