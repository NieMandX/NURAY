import json,tempfile,unittest
from pathlib import Path
import shapely as sh
import numpy as np
from source_topology_cache import cached_inventory


class SourceTopologyCacheTests(unittest.TestCase):
    def test_cache_retains_precision_and_overlay_results(self):
        city=dict(boundsMSK=[0,0,10,10],groundRoadGeometry=sh.geometry.mapping(sh.box(0,0,2,2)),features=[])
        calls=[]
        polygon=sh.set_srid(sh.set_precision(sh.box(0,0,2,2),.01),3857)
        line=sh.set_precision(sh.LineString([(0,0,1),(2,2,3)]),.00001)
        cutter=sh.box(.004,-1,1.006,3)
        def build(c):
            calls.append(1)
            return dict(rows=[(polygon,np.array([line],dtype=object))],empty=sh.Polygon())
        with tempfile.TemporaryDirectory() as directory:
            first=cached_inventory(city,build,Path(directory))
            second=cached_inventory(city,build,Path(directory))
            self.assertEqual(len(calls),1)
            for a,b in [(first['rows'][0][0],second['rows'][0][0]),
                        (first['rows'][0][1][0],second['rows'][0][1][0]),(first['empty'],second['empty'])]:
                self.assertEqual(sh.to_wkb(a,include_srid=True),sh.to_wkb(b,include_srid=True))
                self.assertEqual(sh.get_precision(a),sh.get_precision(b))
                self.assertEqual(sh.get_srid(a),sh.get_srid(b))
                self.assertEqual(a.intersection(cutter).wkb,b.intersection(cutter).wkb)
            # This overlay is precision-sensitive: the regression must detect
            # the default WKB/pickle round-trip that silently loses the grid.
            self.assertNotEqual(polygon.intersection(cutter).wkb,
                                sh.from_wkb(polygon.wkb).intersection(cutter).wkb)

    def test_exact_inputs_and_integrity_required(self):
        city=dict(boundsMSK=[0,0,10,10],groundRoadGeometry=sh.geometry.mapping(sh.box(0,0,2,2)),features=[dict(id='a',coordinates=[[0,0,0]])])
        calls=[]
        def build(c):calls.append(1);return dict(poly=sh.box(0,0,2,2),features=c['features'])
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)
            first=cached_inventory(city,build,path);second=cached_inventory(city,build,path)
            self.assertTrue(first['poly'].equals(second['poly']));self.assertEqual(len(calls),1)
            next(path.glob('*.pkl')).write_bytes(b'corrupt')
            self.assertTrue(cached_inventory(city,build,path)['poly'].equals(first['poly']));self.assertEqual(len(calls),2)
            city['features'][0]['coordinates'][0][0]=.1
            cached_inventory(city,build,path);self.assertEqual(len(calls),3)
            city['boundsMSK']=[0,0,20,20]
            cached_inventory(city,build,path);self.assertEqual(len(calls),4)
            city['groundRoadGeometry']=sh.geometry.mapping(sh.box(0,0,3,3))
            cached_inventory(city,build,path);self.assertEqual(len(calls),5)


if __name__=='__main__':unittest.main()
