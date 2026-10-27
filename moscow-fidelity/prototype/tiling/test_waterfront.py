import unittest, tempfile, json
from pathlib import Path
import numpy as np
import shapely as sh
from waterfront import source_network,water_domain,wall_geometry,bank_segments,make_texture,bridge_continuation,bridge_geometry

def source_box(x0,y0,x1,y1):
    return dict(layer='Water_area',geometryType='polygon',coordinates=[[x0,y0,0],[x1,y0,0],[x0,y1,0],[x1,y1,0]])
def water(g,z=3):return dict(geometry=json.loads(sh.to_geojson(g)),heightPlane=[0,0,z],kind='water')

class WaterfrontTests(unittest.TestCase):
    def test_river_leaves_and_reenters_acquisition_area(self):
        network,stats=source_network([source_box(-2,1,3,3),source_box(7,6,12,8),source_box(4,4,6,5)],[0,0,10,10])
        self.assertTrue(network.covers(sh.Point(1,2)))
        self.assertTrue(network.covers(sh.Point(9,7)))
        self.assertFalse(network.covers(sh.Point(5,4.5)))
        self.assertEqual(stats['boundarySourceComponents'],2)
    def test_explicit_channel_under_road_connects_pond(self):
        river=source_box(-1,0,11,4);pond=source_box(2,7,4,9);nearby=source_box(6,7,8,9)
        channel=dict(layer='Water_line',coordinates=[[3,3,0],[3,8,0]],source=dict(coordinateStepM=.02))
        network,stats=source_network([river,pond,nearby,channel],[0,0,10,10])
        self.assertTrue(network.covers(sh.Point(3,8)));self.assertFalse(network.covers(sh.Point(7,8)))
        self.assertEqual(stats['connectedSourceComponents'],2)
    def test_bridge_does_not_disconnect_source_network(self):
        network,_=source_network([source_box(-1,0,11,4),source_box(2,7,4,9)],[0,0,10,10])
        rows=[water(sh.box(0,0,4,4)),water(sh.box(6,0,10,4)),water(sh.box(2,7,4,9))]
        cells,selected,domain=water_domain(rows,network)
        self.assertEqual(selected.tolist(),[True,True,False]);self.assertEqual(len(sh.get_parts(domain)),2)
    def test_confirmed_bridge_restores_water_without_crosswall(self):
        network=sh.box(-1,0,11,4);domain=sh.union_all([sh.box(0,0,4,4),sh.box(6,0,10,4)])
        bridge=source_box(3,-1,7,5);bridge['layer']='Bridge_area'
        pier=source_box(4.8,1.8,5.2,2.2);pier['layer']='Pier_quarter'
        fill,spans=bridge_continuation([bridge,pier],network,domain,[0,-1,10,10])
        self.assertAlmostEqual(fill.area,7.84)
        self.assertFalse(fill.covers(sh.Point(5,2)))
        joined=sh.union_all([domain,fill],grid_size=1e-5)
        a,b,_,_,_=bank_segments(joined,[0,-1,10,10])
        self.assertFalse(sh.contains(spans.buffer(-.01),sh.points((a+b)/2)).any())
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'terrain.npz';np.savez(path,polygons=np.array([sh.to_wkb(sh.box(0,-1,10,10),hex=True)]),planes=np.array([[.01,0,3.]]))
            tri,cells,planes=bridge_geometry(fill,path,[0,0,0])
            self.assertAlmostEqual(sum(c.area for c in cells),fill.area)
            self.assertTrue(np.allclose(tri[:,:,1],tri[:,:,0]*.01+1.))
            self.assertTrue((tri[:,:,4]>0).all())

    def test_precision_slit_never_becomes_a_tall_bank(self):
        g=sh.box(0,0,10,10).difference(sh.box(3,5,7,5.000002))
        a,b,_,_,_=bank_segments(g,[-1,-1,11,11])
        inside=sh.contains(sh.box(2,4,8,6),sh.points((a+b)/2))
        self.assertLess(np.linalg.norm(b-a,axis=1)[inside].sum(),1e-4)

    def test_no_boundary_connected_water_skips_lakes(self):
        network,_=source_network([source_box(2,2,4,4)],[0,0,10,10]);self.assertTrue(network.is_empty)
    def test_global_holes_heights_and_chainage(self):
        # A triangular island stays a bank, while the artificial x=0 cut does not.
        g=sh.Polygon([(0,0),(12,0),(12,9),(0,9)],holes=[[(3,3),(5,3),(4,5)]])
        ground=sh.box(-2,-2,15,12).difference(g)
        row=water(ground,3.1);row['kind']='land'
        triangles,stats,banks=wall_geometry(g,np.array([g],dtype=object),np.array([[0,0,3.]]),[row],[0,-1,20,20],[0,0,0])
        self.assertAlmostEqual(stats['excludedAcquisitionEdgeM'],9)
        self.assertEqual(stats['rings'],2)
        self.assertTrue(np.allclose(triangles[:,:,1].min(1),1))
        self.assertAlmostEqual(triangles[:,:,1].max(),3.1)
        self.assertTrue(np.allclose(np.diff(banks['chainage']).ravel(),np.linalg.norm(banks['b']-banks['a'],axis=1)))
        self.assertTrue(np.allclose(np.linalg.norm(triangles[:,:,3:6],axis=2),1))
    def test_approved_texture_embedded_once(self):
        from waterfront_finish import ASSET
        with tempfile.TemporaryDirectory() as d:
            info=make_texture(d);p=next(Path(d).glob('*.png'))
            self.assertEqual(p.read_bytes(),ASSET.read_bytes())
            metadata=next(iter(info.values()))
            self.assertEqual(metadata['repeatM'],[4,2])
            self.assertTrue(metadata['horizontalOnly'])
            self.assertEqual(metadata['mooringRingSpacingM'],4)

if __name__=='__main__':unittest.main()
