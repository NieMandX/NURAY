import unittest
import numpy as np
import shapely as sh
from spatial_mask import SpatialMask, LinearMask

class Masks(unittest.TestCase):
    def test_exact_difference_near_holes_and_partition_cuts(self):
        g=sh.union_all([sh.box(-40,-30,440,30),sh.box(170,-200,230,250)]).difference(sh.box(190,-10,210,10))
        mask=SpatialMask(g,60)
        probes=[sh.box(190,-20,210,20),sh.box(-40,-40,0,0),sh.box(-500,-500,500,500)]
        for x,y in np.random.default_rng(11).uniform(-220,440,(200,2)):
            probes.append(sh.Point(x,y).buffer(28))
        for p in probes:
            direct=p.difference(g);local=p.difference(mask.near(p))
            self.assertLess(direct.symmetric_difference(local).area,1e-7)

    def test_linear_index_preserves_vertical_horizontal_and_connected_edges(self):
        g=sh.union_all([sh.box(0,0,1000,20).boundary,sh.LineString([(300,-500),(300,500)]),
                        sh.LineString([(-500,10),(1500,10)])])
        mask=LinearMask(g)
        probes=[sh.LineString([(300,-10),(300,600)]),sh.LineString([(100,10),(400,10)]),
                sh.box(-1,-1,1001,21),sh.Point(0,0)]
        for x,y in np.random.default_rng(12).uniform(-500,1500,(100,2)):
            probes.append(sh.Point(x,y).buffer(40))
        for p in probes:
            self.assertTrue(p.intersection(g).equals(p.intersection(mask.near(p))))

    def test_buffered_coverage_across_partition_boundary(self):
        g=sh.box(-300,-50,300,50).difference(sh.box(-10,-10,10,10))
        mask=SpatialMask(g,40);tolerance=.00005
        # A nearby cell may contribute only through its tolerance buffer.
        for x,y in [(0,50),(10,0),(300,0),(-300,-50),(0,0)]:
            for dx in [-tolerance,0,tolerance]:
                gate=sh.Point(x+dx,y).buffer(.001)
                direct=gate.difference(g.buffer(tolerance))
                local=gate.difference(mask.near(gate.buffer(tolerance)).buffer(tolerance))
                self.assertLess(direct.symmetric_difference(local).area,1e-12)

    def test_pedestrian_line_coverage_keeps_crossing_and_boundary_segments(self):
        green=sh.box(0,0,1000,500).difference(sh.box(400,100,600,400))
        paving=sh.union_all([sh.box(0,245,1000,255),sh.box(245,0,255,500)]).buffer(.003)
        green_mask=SpatialMask(green,75);path_mask=SpatialMask(paving,75)
        for line in [sh.LineString([[-20,250],[1020,250]]),sh.LineString([[0,0],[1000,500]]),
                     sh.LineString([[400,50],[400,450]]),sh.LineString([[250,-20],[250,520]])]:
            direct=line.intersection(green).difference(paving)
            local=line.intersection(green_mask.near(line));local=local.difference(path_mask.near(local))
            self.assertLess(direct.symmetric_difference(local).length,1e-8)
if __name__=='__main__':unittest.main()
