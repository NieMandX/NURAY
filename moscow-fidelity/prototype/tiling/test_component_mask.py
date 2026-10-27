import unittest
import numpy as np
import shapely as sh
from spatial_mask import ComponentMask
from landscape import plan, split_cell


class ComponentMaskTests(unittest.TestCase):
    def test_tiny_triangles_cross_hole_edges_without_containing_any_vertex(self):
        holes = [sh.box(x+.2, y+.2, x+.8, y+.8).exterior.coords
                 for x in range(12) for y in range(12)]
        geometry = sh.Polygon(sh.box(-1, -1, 13, 13).exterior.coords, holes)
        mask = ComponentMask(geometry)
        for x in range(12):
            for y in range(12):
                queries = [sh.Polygon([(x+.79, y+.49), (x+.81, y+.49), (x+.8, y+.51)]),
                           sh.box(x+.3, y+.3, x+.4, y+.4),
                           sh.LineString([(x+.8, y+.4), (x+.8, y+.6)])]
                for q in queries:
                    self.assertEqual(mask.intersects(q), geometry.intersects(q))
                    self.assertEqual(mask.covers(q), geometry.covers(q))

    def test_matches_whole_polygon_including_holes_and_multipart_queries(self):
        shell = sh.box(0, 0, 10, 10).difference(sh.box(3, 3, 7, 7))
        geometry = sh.MultiPolygon([shell, sh.box(20, 0, 30, 10), sh.box(40, 0, 41, 1)])
        mask = ComponentMask(geometry)
        queries = [sh.Polygon(), sh.Point(0, 0), sh.Point(5, 5), sh.LineString([(0, 0), (30, 0)]),
                   sh.box(1, 1, 2, 2), sh.box(2, 2, 4, 4), sh.box(9, 1, 21, 2),
                   sh.MultiPolygon([sh.box(1, 1, 2, 2), sh.box(21, 1, 22, 2)])]
        rng = np.random.default_rng(35)
        for x, y, w, h in rng.uniform(-2, 42, (500, 4)):
            queries.append(sh.box(x, y, x+abs(w)/8, y+abs(h)/8))
        for q in queries:
            self.assertEqual(mask.intersects(q), geometry.intersects(q), q.wkt)
            self.assertEqual(mask.covers(q), geometry.covers(q), q.wkt)

    def test_partition_geometry_and_planes_match_original_predicates(self):
        extent = sh.box(-5, -5, 45, 15)
        green = sh.union_all([sh.box(0, 0, 12, 10), sh.box(20, 0, 30, 10), sh.box(35, 0, 40, 10)], grid_size=1e-5)
        features = [dict(id='path', geometryType='polyline', layer='Pedestrian_road',
                         properties={}, coordinates=[[6, -2], [6, 12]])]
        layout, _ = plan(features, green, sh.Polygon(), extent, sh.box(23, 3, 27, 7))
        original = {k: v for k, v in layout.items() if not k.endswith('Predicate')}
        plane = np.array([.02, -.03, 2.])
        queries = [sh.box(x, y, x+1.3, y+1.1) for x in np.arange(-1, 42, 1.7) for y in np.arange(-1, 12, 1.3)]
        queries += [sh.box(0, 0, .00001, 10), sh.box(11.99999, 1, 12.00001, 2)]
        for q in queries:
            actual = list(split_cell(q, plane, layout))
            expected = list(split_cell(q, plane, original))
            self.assertEqual(len(actual), len(expected))
            for (a, p, c), (b, r, d) in zip(actual, expected):
                self.assertEqual(a, b)
                self.assertEqual(p.wkb, r.wkb)
                np.testing.assert_array_equal(c, d)


if __name__ == '__main__':
    unittest.main()
