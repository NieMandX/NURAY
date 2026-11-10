import unittest
import shapely as sh
from shapely.affinity import rotate,translate
from tunnel_walls import resolved_border_chains


class BorderPrecisionTest(unittest.TestCase):
    def test_actual_moscow_overlay_loop(self):
        loop=sh.LineString([(3555.03432,4447.21643),(3555.0344,4447.21652),
                            (3555.03443,4447.21657),(3555.03432,4447.21643)])
        for angle in (0,37,90):
            for offset in (0,10000):
                candidate=translate(rotate(loop,angle),offset,-offset)
                resolved,rejected=resolved_border_chains(candidate,1e-5)
                self.assertEqual(resolved,[])
                self.assertEqual(len(rejected),1)

    def test_resolved_boundaries_and_open_ends_remain(self):
        ring=sh.box(0,0,.02,3).exterior
        short_open=sh.LineString([(4,0),(4.0001,0)])
        open_wall=sh.LineString([(5,0),(6,0),(6,10)])
        for angle in (0,37):
            source=rotate(sh.MultiLineString([ring,short_open,open_wall]),angle)
            resolved,rejected=resolved_border_chains(source,1e-5)
            self.assertEqual(rejected,[])
            self.assertEqual(len(resolved),3)
            self.assertTrue(sh.equals(sh.union_all(resolved),source))


if __name__=='__main__':unittest.main()
