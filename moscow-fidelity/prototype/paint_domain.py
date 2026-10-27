"""Road paint belongs to an asphalt floor, never an adjacent map surface."""
import numpy as np
import shapely as sh
from collections import OrderedDict

GAP = .003
HEIGHT_TOLERANCE = .002
POLICY = ('Clip all marking triangles to motor-traffic asphalt before transport tiling; '
          'exclude sidewalks, curbs, traffic separators, vegetation, pedestrian and railway slabs; '
          'match the physical height of each floor, retain holes and disconnected footprints; '
          'record unsupported paint but do not render it.')

def paint_projection_mask(local_xyz):
    """Reject paint that collapses in XZ after renderer Float32 packing.

    A tiny vertical residual can have nonzero 3D area while no longer covering
    any road. Assess the actual stored coordinates, not the pre-pack doubles.
    """
    xy=np.asarray(local_xyz,dtype=np.float32)[:,:,[0,2]].astype(float)
    d=xy[:,1:]-xy[:,:1]
    return (d[:,0,0]*d[:,1,1]-d[:,0,1]*d[:,1,0])!=0


def accepts(surface):
    # Contour repairs inherit the canonical road material, but have no source
    # purpose. Unknown source purposes must not become roads by name alone.
    return (surface['kind'].startswith('roadbed') and surface['material'] == 0
            and surface.get('purpose') in (None, 'motor-traffic')
            and surface.get('transport') != 'pedestrian')


def polygons(g):
    if g.is_empty:return []
    if g.geom_type == 'Polygon':return [g]
    return [p for x in getattr(g, 'geoms', []) for p in polygons(x)]


def height_band(triangle, delta, tolerance):
    """Clip a convex XY triangle where |linear height difference| <= tolerance.

    Checking only a centroid can attach a sloping stripe to the wrong deck.
    """
    ring=list(np.asarray(triangle, dtype=float))
    for sign in (1, -1):
        result=[]
        for i,a in enumerate(ring):
            b=ring[(i+1)%len(ring)]
            da=tolerance-sign*(a@delta[:2]+delta[2]);db=tolerance-sign*(b@delta[:2]+delta[2])
            if da>=0:result.append(a)
            if (da>=0)!=(db>=0):result.append(a+(b-a)*da/(da-db))
        ring=result
        if len(ring)<3:return sh.Polygon()
    return sh.Polygon(ring)


class Domain:
    def __init__(self, cells):
        self.cells=cells
        self.geometries=[c['poly'] for c in cells]
        self.tree=sh.STRtree(self.geometries)
        self._unions=OrderedDict()

    def fully_supported(self, triangles, tolerance=HEIGHT_TOLERANCE):
        """Conservative batch shortcut for the existing single-cell return.

        Query `covered_by` (the inverse of cell.covers(p)) in bounded batches.
        Height arithmetic is deliberately identical to supported(), including
        its local 2x2 solve; no rounded plane buckets or relaxed tolerances.
        A False result still needs the ordinary multi-cell clipping path.
        """
        result=np.zeros(len(triangles),dtype=bool)
        for start in range(0,len(triangles),4096):
            batch=triangles[start:start+4096]
            geometries=sh.polygons(batch[:,:,:2])
            valid=sh.area(geometries)>=1e-12
            pairs=self.tree.query(geometries,predicate='covered_by')
            planes={}
            for row,index in pairs.T:
                row=int(row)
                if result[start+row] or not valid[row]:continue
                xyz=batch[row];xy=xyz[:,:2]
                if row not in planes:
                    slope=np.linalg.solve(xy[1:]-xy[0],xyz[1:,2]-xyz[0,2])
                    plane=np.r_[slope,xyz[0,2]-slope@xy[0]]
                    plane[2]-=GAP;planes[row]=plane
                delta=planes[row]-self.cells[int(index)]['plane']
                differences=xy@delta[:2]+delta[2]
                if abs(differences).max()<=tolerance:result[start+row]=True
        return result

    def supported(self, xyz, tolerance=HEIGHT_TOLERANCE):
        xy=xyz[:,:2];p=sh.Polygon(xy)
        if p.area<1e-12:return sh.Polygon()
        slope=np.linalg.solve(xy[1:]-xy[0],xyz[1:,2]-xyz[0,2])
        plane=np.r_[slope,xyz[0,2]-slope@xy[0]]
        plane[2]-=GAP
        pieces=[];indices=[];partial=False
        for i in self.tree.query(p, predicate='intersects'):
            c=self.cells[int(i)];delta=plane-c['plane']
            differences=xy@delta[:2]+delta[2]
            if differences.min()>tolerance or differences.max()<-tolerance:continue
            if abs(differences).max()<=tolerance and c['poly'].covers(p):return p
            # Union floor cells before intersecting the narrow stripe. Doing
            # the reverse creates nearly coincident slivers and spurious holes.
            piece=c['poly']
            clipped=abs(differences).max()>tolerance
            if clipped:piece=piece.intersection(height_band(xy,delta,tolerance))
            if piece.area>1e-12:
                pieces.append(piece);indices.append(int(i));partial=partial or clipped
        if not pieces:return sh.Polygon()
        # Adjacent stripes repeatedly intersect the same immutable floor
        # cells. Only reuse a union of whole cells in the exact same order;
        # height-clipped cells depend on this triangle and are never cached.
        key=tuple(indices)
        if not partial and key in self._unions:
            merged=self._unions[key];self._unions.move_to_end(key)
        else:
            merged=sh.union_all(pieces)
            if not partial:
                self._unions[key]=merged
                if len(self._unions)>256:self._unions.popitem(last=False)
        return p.intersection(merged)
