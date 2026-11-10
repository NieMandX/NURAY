import json,tempfile,unittest
from unittest.mock import patch
from pathlib import Path
import numpy as np
import shapely as sh
from spatial_mask import SpatialMask,ComponentMask,intersecting_components
from landscape_checkpoint import save,load,signature


class LandscapeCheckpoint(unittest.TestCase):
    def test_exact_geometry_precision_predicates_and_tree_order(self):
        g=sh.set_precision(sh.union_all([sh.box(2125,8070,2137,8072),
            sh.box(2155,8080,2157,8089)]),.00001)
        g=sh.set_srid(g,3857)
        sh.prepare(g)
        spatial=SpatialMask(g,5);component=ComponentMask(g)
        probes=[sh.box(2124,8069,2126,8071),sh.Point(2137,8072),
                sh.box(2140,8070,2160,8090),sh.box(2000,8000,2200,8200)]
        for p in probes:spatial.near(p);component.covers(p)
        indexed=np.asarray([sh.box(x,8070,x+1,8072) for x in range(2124,2159)],dtype=object)
        tree=sh.STRtree(indexed)
        original=dict(g=g,alias=g,spatial=spatial,component=component,tree=tree,
            array=np.arange(32,dtype='<f8').reshape(4,8))
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'layout.pkl.gz';key=dict(version=1,source='exact')
            save(path,key,original);restored=load(path,key)
        self.assertIs(restored['g'],restored['alias'])
        self.assertEqual(restored['g'].wkb,g.wkb)
        self.assertEqual(sh.get_precision(restored['g']),.00001)
        self.assertEqual(sh.get_srid(restored['g']),3857)
        self.assertTrue(sh.is_prepared(restored['g']))
        self.assertEqual(restored['array'].tobytes(),original['array'].tobytes())
        self.assertEqual([p.wkb for p in restored['spatial'].cells],[p.wkb for p in spatial.cells])
        for p in probes:
            self.assertEqual(restored['spatial'].near(p).wkb,spatial.near(p).wkb)
            self.assertEqual(restored['component'].covers(p),component.covers(p))
            self.assertEqual(restored['component'].intersects(p),component.intersects(p))
            np.testing.assert_array_equal(intersecting_components(restored['tree'],p),tree.query(p,predicate='intersects'))

    def test_cache_rejects_changed_inputs_code_and_corrupt_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp)/'base';code=Path(tmp)/'code';base.mkdir();code.mkdir()
            for name in ['validation.json','canonical/validation.json','canonical/full/scene.json',
                         'canonical/terrain.npz','canonical/urban-model.json.gz']:
                p=base/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(name.encode())
            (code/'algorithm.py').write_text('VERSION=1\n')
            key=signature(base,code);path=base/'layout.pkl.gz';save(path,key,{'geometry':sh.box(0,0,1,1)})
            self.assertIsNotNone(load(path,key))
            (code/'algorithm.py').write_text('VERSION=2\n')
            self.assertIsNone(load(path,signature(base,code)))
            (code/'algorithm.py').write_text('VERSION=1\n')
            (base/'canonical/terrain.npz').write_bytes(b'changed terrain')
            self.assertIsNone(load(path,signature(base,code)))
            with path.open('ab') as stream:stream.write(b'corrupt')
            self.assertIsNone(load(path,key))

    def test_failed_save_retains_previous_cache_and_cleans_temporary(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'layout.pkl.gz';key={'version':1}
            save(path,key,{'original':True});before=path.read_bytes()
            with patch('landscape_checkpoint.restore_geometry',side_effect=ValueError('cannot roundtrip')):
                with self.assertRaises(ValueError):save(path,key,sh.box(0,0,1,1))
            self.assertEqual(path.read_bytes(),before)
            self.assertFalse(Path(str(path)+'.tmp').exists())
            self.assertEqual(load(path,key),{'original':True})
            Path(str(path)+'.json').write_text('invalid metadata')
            self.assertIsNone(load(path,key))


if __name__=='__main__':unittest.main()
