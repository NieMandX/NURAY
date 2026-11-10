from pathlib import Path
import pickle
import tempfile
import unittest
import shapely as sh
from validation_geometry import footprint_unions, footprint_fingerprint


class FootprintCacheTests(unittest.TestCase):
    def test_cached_overlays_retain_the_fresh_precision_model(self):
        grid=.001
        rows={'land':[sh.set_precision(sh.box(.003,.007,2.001,3.002),grid)]}
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'footprints.pkl'
            fresh=footprint_unions(rows,lambda gs:sh.union_all(gs,grid_size=grid),grid,path)
            def unexpected(_):raise AssertionError('Valid cache was not reused')
            restored=footprint_unions(rows,unexpected,grid,path)
            self.assertEqual(float(sh.get_precision(restored['land'])),grid)
            self.assertEqual(sh.to_wkb(fresh['land']),sh.to_wkb(restored['land']))
            cutter=sh.Polygon([(0,0),(3,1),(0,3)])
            self.assertEqual(sh.to_wkb(fresh['land'].intersection(cutter)),
                             sh.to_wkb(restored['land'].intersection(cutter)))

    def test_legacy_coordinate_only_cache_is_recomputed_without_guessing_a_grid(self):
        grid=.001;rows={'land':[sh.set_precision(sh.box(0,0,2,2),grid)]}
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'footprints.pkl'
            with path.open('wb') as stream:
                pickle.dump(dict(fingerprint=footprint_fingerprint(rows,grid),footprints={'land':rows['land'][0]}),stream)
            calls=[]
            def union(gs):calls.append(len(gs));return sh.union_all(gs,grid_size=grid)
            result=footprint_unions(rows,union,grid,path)
            self.assertEqual(calls,[1]);self.assertEqual(float(sh.get_precision(result['land'])),grid)

    def test_input_precision_change_invalidates_matching_coordinates(self):
        first=sh.set_precision(sh.box(0,0,2,2),.001)
        second=sh.set_precision(first,.0001,mode='pointwise')
        self.assertEqual(sh.to_wkb(first),sh.to_wkb(second))
        self.assertNotEqual(footprint_fingerprint({'land':[first]},.001),
                            footprint_fingerprint({'land':[second]},.001))


if __name__=='__main__':unittest.main()
