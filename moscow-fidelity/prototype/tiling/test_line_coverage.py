import unittest
import numpy as np
import shapely as sh
from line_coverage import segments,side_lines,uncovered_linework


class LineCoverage(unittest.TestCase):
    def test_separate_rings_do_not_get_bridged(self):
        rings=sh.MultiLineString([[(0,0),(1,0),(1,1)],[(10,10),(11,10)]])
        self.assertEqual(len(segments(rings)),3)
        self.assertAlmostEqual(sum(sh.length(segments(rings))),3)

    def test_matches_global_buffer_with_gaps_corners_duplicates(self):
        wanted=sh.MultiLineString([[(0,0),(2,0),(2,2)],[(0,0),(2,0)],[(5,5),(7,5)]])
        observed=sh.linestrings([[[0,-.0004],[1,-.0004]],[[1.02,0],[2,0]],[[2,0],[2,1]],[[2,1.01],[2,3]],[[4,5],[8,5]],[[2,0],[2,1]]])
        expected=wanted.difference(sh.union_all(observed).buffer(.001))
        for batch in (1,2,1024):
            got=uncovered_linework(wanted,observed,.001,batch)
            self.assertLess(got.symmetric_difference(expected).length,1e-10)

    def test_preserves_complete_nearby_segments(self):
        wanted=sh.LineString([(0,0),(1,0)])
        observed=sh.linestrings([[[-1,-.0001],[2,-.0001]]])
        self.assertTrue(uncovered_linework(wanted,observed,.001).is_empty)

    def test_no_observed_or_no_expected(self):
        wanted=sh.LineString([(0,0),(1,0)])
        self.assertEqual(len(side_lines([])),0)
        self.assertEqual(uncovered_linework(wanted,[],.001).length,1)
        self.assertEqual(uncovered_linework(sh.MultiLineString([]),[],.001).length,0)

    def test_vertical_double_sided_quad_deduplication(self):
        v=np.array([[1,2,0],[4,6,0],[4,6,1],[1,2,1]])
        triangles=np.array([v[[0,1,2]],v[[0,2,3]],v[[2,1,0]],v[[3,2,0]]])
        lines=side_lines(triangles)
        self.assertEqual(len(lines),1)
        self.assertEqual(lines[0].length,5)


if __name__=='__main__':unittest.main()
