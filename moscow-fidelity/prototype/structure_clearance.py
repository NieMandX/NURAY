"""Synthetic deck overhangs yield to nearby, vertically occupied road space.

Source floors are never changed. The one-metre local reservation is a modelling
rule for preventing concrete intrusions, not a certified traffic clearance.
High crossings keep their complete structure; drawing tiers are irrelevant.
"""
import numpy as np
import shapely as sh

RESERVED_HEIGHT = 1.0


def attached_extension(footprint, extension, precision):
    """A clipped concrete remnant needs an areal connection to its source deck."""
    expanded=sh.union_all([footprint,extension],grid_size=precision)
    kept=[];removed=0.
    for p in sh.get_parts(expanded):
        if p.geom_type!='Polygon':continue
        if p.intersection(footprint).area>precision**2:kept.append(p)
        else:removed+=p.area
    retained=sh.union_all(kept,grid_size=precision).difference(footprint)
    return retained,removed


def positive_polygon(points, values):
    out=[]
    for i,a in enumerate(points):
        j=(i+1)%len(points);b=points[j];va=values[i];vb=values[j]
        if va>=0:out.append(a)
        if (va>=0)!=(vb>=0):out.append(a+(b-a)*va/(va-vb))
    return sh.Polygon(out) if len(out)>=3 else sh.Polygon()


def reserved_extension(extension, floors, tree, owners, height, depth, guard,
                       triangulate, z_at, precision):
    cuts=[]
    for i in tree.query(extension,predicate='intersects'):
        row=floors[int(i)]
        if row['kind']=='roadbed_tunnel':continue  # Covered map interiors do not reserve open-air space.
        if row['owner'] in owners:continue
        piece=extension.intersection(row['poly'])
        if piece.area<=precision**2:continue
        for tri in triangulate(piece,np.zeros(3)):
            xy=tri[:,:2];base=np.array([height(p) for p in xy])
            road=z_at(row['plane'],xy)
            # The synthetic solid [base-depth, base+guard] intersects the
            # neighbouring corridor [road, road+reserved height]. Clip the
            # two inequalities continuously, including sloped crossings.
            lower=positive_polygon(xy,road+RESERVED_HEIGHT-(base-depth))
            upper=positive_polygon(xy,(base+guard)-road)
            cut=lower.intersection(upper)
            if cut.area>precision**2:cuts.append(cut)
    return sh.union_all(cuts,grid_size=precision) if cuts else sh.Polygon()
