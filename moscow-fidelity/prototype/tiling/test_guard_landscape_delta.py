import unittest
import shapely as sh
from guard_landscape_delta import change_envelope


class GuardLandscapeDeltaTests(unittest.TestCase):
    def test_removed_apron_inside_shared_header_does_not_change_reserved_ground(self):
        apron=sh.box(0,0,2,1);header=sh.box(-1,-1,3,2)
        changed,proof=change_envelope([(apron,sh.Polygon()),(header,header)])
        self.assertTrue(changed.is_empty)
        self.assertEqual(proof['rawAreaM2'],2)

    def test_exposed_removed_apron_remains_in_envelope(self):
        apron=sh.box(0,0,2,1);header=sh.box(-1,-1,1,2)
        changed,_=change_envelope([(apron,sh.Polygon()),(header,header)])
        self.assertTrue(changed.equals(sh.box(1,0,2,1)))

    def test_equal_boundaries_with_different_ring_starts_are_not_changed(self):
        a=sh.box(0,0,2,1);xy=list(a.exterior.coords)[:-1]
        b=sh.Polygon(xy[2:]+xy[:2])
        changed,proof=change_envelope([(a,b)])
        self.assertTrue(changed.is_empty)
        self.assertEqual(proof['changedOperands'],0)

    def test_envelope_contains_every_change_for_overlapping_operands(self):
        pairs=[(sh.box(0,0,3,2),sh.box(1,0,4,2)),
               (sh.box(2,-1,5,3),sh.box(2,-1,5,3)),
               (sh.box(-2,0,1,1),sh.box(-2,0,1,2))]
        changed,_=change_envelope(pairs)
        actual=sh.union_all([a for a,b in pairs]).symmetric_difference(sh.union_all([b for a,b in pairs]))
        self.assertEqual(actual.difference(changed).area,0)
        self.assertTrue(changed.intersects(sh.box(0,1,1,2)))


if __name__=='__main__':unittest.main()
