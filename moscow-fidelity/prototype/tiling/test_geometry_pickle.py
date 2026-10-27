import io,pickle,unittest
import shapely as sh
from geometry_pickle import dump,restore_source_precision

class CheckpointPrecisionTest(unittest.TestCase):
    def test_geometry_and_index_retain_their_own_precision(self):
        fixed=sh.set_precision(sh.box(0,0,1,1),.001)
        floating=sh.box(1.125,0,2,1)
        # WKB/ordinary pickle keeps every coordinate but loses the GEOS grid.
        old=pickle.loads(pickle.dumps(fixed))
        self.assertEqual(old.wkb,fixed.wkb)
        self.assertNotEqual(old.buffer(.025).wkb,fixed.buffer(.025).wkb)
        stream=io.BytesIO();dump({'rows':[fixed,floating],'tree':sh.STRtree([fixed,floating])},stream)
        stream.seek(0);restored=pickle.load(stream)
        for actual,original in zip(restored['rows'],[fixed,floating]):
            self.assertEqual(actual.wkb,original.wkb)
            self.assertEqual(sh.get_precision(actual),sh.get_precision(original))
            self.assertEqual(actual.buffer(.025).wkb,original.buffer(.025).wkb)
        self.assertEqual(list(sh.get_precision(restored['tree'].geometries)),[.001,0.])

    def test_signed_source_recipe_migration_is_coordinate_preserving(self):
        original=sh.set_precision(sh.box(0,0,1.001,1),.001)
        old=pickle.loads(pickle.dumps(original));state={'dem':[(old,[0,0,0])]}
        rows=[{'poly':old,'patches':[(old,[0,0,0])]}]
        restore_source_precision(state,rows,.001)
        self.assertEqual(rows[0]['poly'].wkb,original.wkb)
        self.assertEqual(rows[0]['poly'].buffer(.025).wkb,original.buffer(.025).wkb)
        self.assertEqual(sh.get_precision(state['demtree'].geometries[0]),.001)
        with self.assertRaises(ValueError):
            restore_source_precision({'dem':[]},[{'poly':sh.box(0,0,1.0015,1),'patches':[]}],.001)

if __name__=='__main__':unittest.main()
