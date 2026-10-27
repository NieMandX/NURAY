"""Bind source paint by its declared road tier, before physical-mesh clipping."""
import numpy as np
import shapely as sh
from paint_domain import accepts, HEIGHT_TOLERANCE

SOURCE_FLOOR = 'source-tier-floor'

def floor_overlaps(geometry, polygons):
    """Yield possible floor pairs in the original order, with exact overlays.

    A long marking can cross thousands of disjoint terrain cells. Index their
    bounds instead of performing a quadratic number of polygon intersections.
    The expanded query only selects candidates; it never changes the overlay
    geometry or the ambiguity tolerance.
    """
    tree=sh.STRtree(polygons) if len(polygons)>16 else None
    padding=max(1e-8,2*max([sh.get_precision(geometry),*sh.get_precision(polygons)])) if tree is not None else 0
    for k,polygon in enumerate(polygons):
        clipped=geometry.intersection(polygon)
        if clipped.is_empty:continue
        if tree is None:near=range(k+1,len(polygons))
        else:
            x0,y0,x1,y1=clipped.bounds
            near=sorted(int(j) for j in tree.query(sh.box(x0-padding,y0-padding,x1+padding,y1+padding)) if j>k)
        for j in near:yield k,j,clipped.intersection(polygons[j])

def bind(geometry, source_plane, tiers, surfaces, tree, *, source_floor=False):
    """Zero map marking Z is a drawing offset, even on bridges.

    A declared tier selects the floor. Physically different floors at the same
    tier/XY are ambiguous and remain unbound. Legacy absolute-height paint keeps
    its height compatibility check.
    """
    ids=[int(i) for i in tree.query(geometry,predicate='intersects')
         if set(tiers)&set(surfaces[int(i)]['tiers']) and accepts(surfaces[int(i)])]
    blocked=[]
    if source_floor:
        for k,j,overlap in floor_overlaps(geometry,[surfaces[i]['poly'] for i in ids]):
            if overlap.area<1e-10:continue
            a,b=surfaces[ids[k]],surfaces[ids[j]]
            xy=sh.get_coordinates(overlap);delta=np.asarray(a['plane'])-b['plane']
            if np.max(abs(xy@delta[:2]+delta[2]))>HEIGHT_TOLERANCE:blocked.append(overlap)
    remaining=geometry.difference(sh.union_all(blocked)) if blocked else geometry
    bound=[]
    for i in sorted(ids,key=lambda j:surfaces[j].get('id',str(j))):
        s=surfaces[i];piece=remaining.intersection(s['poly'])
        if piece.area<1e-9:continue
        if not source_floor:
            xy=sh.get_coordinates(piece);delta=np.asarray(s['plane'])-source_plane
            if np.max(abs(xy@delta[:2]+delta[2]))>2:continue
        bound.append((i,piece));remaining=remaining.difference(piece)
        if remaining.is_empty:break
    return bound,sh.union_all([remaining,*blocked]) if blocked else remaining
