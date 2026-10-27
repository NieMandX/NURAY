"""Boundary coverage without a monolithic buffer of tiny adjacent segments."""
import shapely as sh
from shapely.geometry import LineString,box

def lines(g):
    if g.is_empty:return []
    if g.geom_type in {'LineString','LinearRing'}:return [g]
    return [p for child in getattr(g,'geoms',[]) for p in lines(child)]

def uncovered_length(boundary,emitted,tolerance):
    """Subtract local capsules with the same tolerance as buffer(emitted).

    Buffering tens of thousands of sub-micron-separated, nearly collinear
    segments together can trigger costly global noding. Independent capsules
    have the same union coverage; sequential subtraction avoids that union.
    This only validates meshes; it never moves or repairs their vertices.
    """
    source=lines(emitted)
    if not source:return boundary.length
    tree=sh.STRtree(source);padded={};missing=0.
    for chain in lines(boundary):
        xy=list(chain.coords)
        for a,b in zip(xy,xy[1:]):
            edge=LineString([a,b])
            if edge.length==0:continue
            x0,y0,x1,y1=edge.bounds
            for i in tree.query(box(x0-tolerance,y0-tolerance,x1+tolerance,y1+tolerance)):
                i=int(i)
                if i not in padded:padded[i]=source[i].buffer(tolerance)
                edge=edge.difference(padded[i])
                if edge.is_empty:break
            # A residual shorter than the two endpoint uncertainty intervals
            # has no resolved length at this positional tolerance.
            missing+=sum(part.length for part in lines(edge) if part.length>2*tolerance)
    return missing

def physical_land_boundary(road,excluded,extent,tolerance):
    """Road interfaces with resolved land, excluding isolated overlay slivers.

    This uses the same local-width precision rule as solid construction;
    it does not derive the expected perimeter from the emitted curb mesh.
    """
    from passage_space import stable_area
    land=stable_area(extent.difference(road.union(excluded)),tolerance/5)
    from spatial_mask import LinearMask
    mask=LinearMask(land.boundary)
    pieces=[]
    for line in lines(road.boundary.difference(excluded.buffer(tolerance*.6)).difference(extent.boundary.buffer(tolerance))):
        # A single connected road ring can span the whole district. Query
        # short original edges, otherwise its AABB retrieves nearly every land
        # edge and reintroduces the pathological global buffer avoided above.
        xy=list(line.coords)
        for a,b in zip(xy,xy[1:]):
            edge=LineString([a,b])
            if edge.length:
                pieces.append(edge.intersection(mask.near(edge.buffer(tolerance)).buffer(tolerance)))
    return sh.union_all(pieces)

def gap_core_area(gaps,tolerance):
    """Area of gaps wider than numerical overlay drift, independent of extent.

    Total area of micron-wide slivers grows with the number of terrain cells.
    An actual areal hole must still be rejected, even in a much larger region.
    """
    if gaps.is_empty:return 0.
    if gaps.geom_type=='Polygon':return sh.set_precision(gaps,0).buffer(-tolerance).area
    return sum(gap_core_area(g,tolerance) for g in getattr(gaps,'geoms',[]))
