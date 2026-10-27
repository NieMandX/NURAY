"""Distinguish a true cut from a canonical boundary merely touching a tile."""
import numpy as np
import shapely as sh

def one_sided_touches(triangles,axis,edge):
    other=2 if axis==0 else 0
    distance=triangles[:,:,axis]-edge
    rows=triangles[(distance.min(1)<=0)&(distance.max(1)>=0)]
    left=[];right=[];coplanar=[]
    for t in rows:
        d=t[:,axis]-edge;points=[]
        if np.all(d==0):
            coplanar.append(sh.Polygon(t[:,[other,1]]));continue
        for a,b,da,db in zip(t,np.roll(t,-1,axis=0),d,np.roll(d,-1)):
            if da==0:points.append(a)
            if da*db<0:points.append(a+(b-a)*(da/(da-db)))
        if len(points)<2:continue
        p=np.unique(np.asarray(points)[:,[other,1]],axis=0)
        if len(p)<2:continue
        line=sh.LineString([p[0],p[-1]])
        if np.any(d<0):left.append(line)
        if np.any(d>0):right.append(line)
    a,b=sh.union_all(left),sh.union_all(right)
    return a.difference(b.buffer(.000001)),b.difference(a.buffer(.000001)),sh.union_all(coplanar)

def compare(a,b,canonical,axis,edge):
    gap=a.hausdorff_distance(b) if not a.is_empty and not b.is_empty else float('inf')
    missing=a.difference(b.buffer(.0001)).length+b.difference(a.buffer(.0001)).length
    if gap<.0001 and missing<.0001:return gap,missing,0.
    left,right,coplanar=one_sided_touches(canonical,axis,edge)
    # The caller orders the tiles by increasing local axis. A boundary can
    # touch the plane and return to the same side; it owes no duplicate edge
    # to a tile containing no continuation of that physical surface.
    allowed_a=sh.union_all([left,coplanar]);allowed_b=sh.union_all([right,coplanar])
    actual_a=a.difference(b.buffer(.0001));actual_b=b.difference(a.buffer(.0001))
    unexpected=actual_a.difference(allowed_a.buffer(.0001)).length+actual_b.difference(allowed_b.buffer(.0001)).length
    assert unexpected<.0001,('Missing true tile-cut edge',unexpected)
    aa=a.difference(allowed_a.buffer(.0001));bb=b.difference(allowed_b.buffer(.0001))
    gap=0. if aa.is_empty and bb.is_empty else aa.hausdorff_distance(bb)
    missing=aa.difference(bb.buffer(.0001)).length+bb.difference(aa.buffer(.0001)).length
    assert np.isfinite(gap) and gap<.0002 and missing<.0001,(gap,missing)
    return gap,missing,actual_a.length+actual_b.length
