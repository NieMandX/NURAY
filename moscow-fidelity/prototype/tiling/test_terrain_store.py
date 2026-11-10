import tempfile,unittest
from pathlib import Path
import numpy as np
import shapely as sh
from terrain_store import read_terrain,read_terrain_arrays


class TerrainStore(unittest.TestCase):
    def test_exact_geometry_planes_order_and_batch_edges(self):
        polygons=[sh.Polygon([(2125+i*.01,8070),(2125+i*.01,8070.001),(2126+i*.01,8071)]) for i in range(13)]
        planes=np.arange(39,dtype='<f8').reshape(-1,3)*.000013-1.123456789
        with tempfile.TemporaryDirectory() as folder:
            for encoding in ('hex','binary'):
                path=Path(folder)/(encoding+'.npz')
                data=np.array(sh.to_wkb(polygons,hex=encoding=='hex').tolist())
                np.savez_compressed(path,polygons=data,planes=planes)
                for batch in (1,4,32768):
                    rows=read_terrain(path,batch)
                    self.assertEqual([sh.to_wkb(p) for p,c in rows],[sh.to_wkb(p) for p in polygons])
                    self.assertEqual(np.asarray([c for p,c in rows]).tobytes(),planes.tobytes())
                    p,c=read_terrain_arrays(path,batch)
                    self.assertEqual(sh.to_wkb(p).tolist(),sh.to_wkb(polygons).tolist())
                    self.assertEqual(c.tobytes(),planes.tobytes())

    def test_mismatched_planes_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'bad.npz'
            np.savez_compressed(path,polygons=np.array([sh.to_wkb(sh.box(0,0,1,1),hex=True)]),planes=np.zeros((0,3)))
            with self.assertRaisesRegex(ValueError,'count mismatch'):read_terrain(path)


if __name__=='__main__':unittest.main()
