"""Exact local overlays on a large connected polygon, without changing topology."""
import shapely as sh
from collections import OrderedDict

class SpatialMask:
    def __init__(self,geometry,cell_size=250.):
        self.geometry=geometry;self.cells=[];self.cache=OrderedDict()
        def split(g):
            if g.is_empty:return
            x0,y0,x1,y1=g.bounds
            if max(x1-x0,y1-y0)<=cell_size:
                self.cells.append(g);return
            if x1-x0>=y1-y0:
                m=(x0+x1)/2;boxes=[sh.box(x0,y0,m,y1),sh.box(m,y0,x1,y1)]
            else:
                m=(y0+y1)/2;boxes=[sh.box(x0,y0,x1,m),sh.box(x0,m,x1,y1)]
            for box in boxes:split(g.intersection(box))
        split(geometry);self.tree=sh.STRtree(self.cells)

    def near(self,geometry):
        ids=self.tree.query(geometry)
        if len(ids)==len(self.cells):return self.geometry
        if len(ids)==1:return self.cells[int(ids[0])]
        if not len(ids):return sh.GeometryCollection()
        # Adjacent terrain triangles repeatedly request the same immutable
        # cell combination. Bound the cache rather than re-unioning it for
        # every triangle or retaining every region combination indefinitely.
        key=tuple(sorted(map(int,ids)))
        if key in self.cache:
            self.cache.move_to_end(key);return self.cache[key]
        result=sh.union_all([self.cells[i] for i in ids]);self.cache[key]=result
        if len(self.cache)>64:self.cache.popitem(last=False)
        return result


class LinearMask:
    """Exact nearby line segments, including straight zero-width bounds.

    Long connected road networks must not intersect their entire perimeter for
    every short side-wall edge. Index edges without altering their coordinates.
    """
    def __init__(self, geometry):
        self.geometry = geometry
        self.segments = []
        def collect(g):
            if g.is_empty:
                return
            if g.geom_type in ('LineString', 'LinearRing'):
                xy = list(g.coords)
                self.segments.extend(sh.LineString([a, b]) for a, b in zip(xy, xy[1:]) if a != b)
            else:
                for part in getattr(g, 'geoms', []):
                    collect(part)
        collect(geometry)
        self.tree = sh.STRtree(self.segments)

    def near(self, geometry):
        ids = self.tree.query(geometry)
        return sh.union_all([self.segments[i] for i in ids])


class ComponentMask:
    """Exact predicates on original area components near a query geometry.

    Unlike overlay cells, these components are never clipped or rounded.
    An inclusive bounding-box query only excludes components that cannot meet
    the query. Several candidates stay a collection for the covers predicate,
    so a multipart query can be covered by several separate polygons.
    """
    def __init__(self, geometry):
        self.geometry = geometry
        self.parts = []
        def collect(g):
            if g.is_empty:
                return
            if g.geom_type == 'Polygon':
                self.parts.append(g)
            elif g.geom_type in ('MultiPolygon', 'GeometryCollection'):
                for part in g.geoms:
                    collect(part)
            else:
                raise ValueError('ComponentMask requires areal geometry')
        collect(geometry)
        self.tree = sh.STRtree(self.parts)
        self.cache = OrderedDict()

    def intersects(self, geometry):
        # STRtree's predicate prepares the query, not its indexed candidates.
        # With tiny terrain cells and a large polygon containing many holes,
        # that rebuilds the candidate's segment chains for every cell. Keep
        # the exact symmetric predicate, preparing the persistent component.
        for index in self.tree.query(geometry):
            part = self.parts[int(index)]
            sh.prepare(part)
            if part.intersects(geometry):
                return True
        return False

    def covers(self, geometry):
        if geometry.is_empty:
            return self.geometry.covers(geometry)
        ids = self.tree.query(geometry)
        if not len(ids):
            return False
        if len(ids) == len(self.parts):
            return self.geometry.covers(geometry)
        if len(ids) == 1:
            part = self.parts[int(ids[0])]
            sh.prepare(part)
            return part.covers(geometry)
        key = tuple(sorted(map(int, ids)))
        if key not in self.cache:
            local = sh.MultiPolygon([self.parts[i] for i in key])
            sh.prepare(local)
            self.cache[key] = local
            if len(self.cache) > 64:
                self.cache.popitem(last=False)
        self.cache.move_to_end(key)
        return self.cache[key].covers(geometry)
