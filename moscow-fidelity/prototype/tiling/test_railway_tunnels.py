"""Railway tunnel clearance regressions, independent of Moscow coordinates."""
import sys, unittest
from pathlib import Path
import numpy as np
import shapely as sh
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from test_railway_transitions import fixture
from railway_tunnel_validation import inventory,audit,volume_cells


def city_fixture():
    fs=fixture();fs[0]['properties'].update(db_road_part='roadbed_tunnel_descent',db_tiers=[-1])
    for p in fs[0]['coordinates']:p[2]*=-1
    fs[1]['properties'].update(db_tiers=[-1],db_segment_end_level=-1)
    fs.append(dict(id='tunnel',layer='Transport_Roadbed',geometryType='polygon',
        properties=dict(db_road_part='roadbed_tunnel',db_tiers=[-1]),
        coordinates=[[12,0,-3],[12,4,-3],[20,0,-3],[20,4,-3]]))
    fs.append(dict(id='underground',layer='Railroad_tunnel_line',geometryType='polyline',
        properties=dict(db_tiers=[-1],db_segment_begin_level=-1,db_segment_end_level=-1),
        coordinates=[[12,2,0],[20,2,0]]))
    surfaces=[dict(owner=owner,kind=kind,tiers=[-1],geometry=sh.geometry.mapping(poly),heightPlane=plane)
        for owner,kind,poly,plane in [('slab','roadbed_tunnel_descent',sh.box(0,0,12,4),[-.25,0,0]),
            ('tunnel','roadbed_tunnel',sh.box(12,0,20,4),[0,0,-3])]]
    return dict(features=fs,surfaces=surfaces,boundsMSK=[-10,-10,25,20],originMSK=[0,0,0])


def wall(x,bottom,top):
    # Renderer coordinates: Y is height and local Z is minus source Y.
    return np.array([[[x,bottom,0],[x,top,-4],[x,top,0]],[[x,bottom,0],[x,bottom,-4],[x,top,-4]]],float)


class RailwayTunnelChecks(unittest.TestCase):
    def test_coordinate_translation_collapse_does_not_make_nan_volume(self):
        # Source area is positive and above the triangulator's polygon cutoff,
        # but its width is smaller than one representable translated cell.
        tiny=sh.Polygon([(0,0),(1e-13,0),(0,10000)])
        self.assertGreater(tiny.area,1e-10)
        with np.errstate(invalid='raise',divide='raise'):
            self.assertEqual(volume_cells(tiny,[0,0,0],[2125,8070,145]),[])
            real=sh.box(0,0,.002,10)
            cells=volume_cells(real,[0,0,0],[2125,8070,145])
        self.assertTrue(cells)
        self.assertAlmostEqual(sum(p.area for p,_ in cells),real.area,places=9)
        self.assertTrue(all(np.isfinite(planes).all() for _,planes in cells))

    def check_meshes(self,items,city=None):
        city=city or city_fixture();dem=[(sh.box(*city['boundsMSK']),np.zeros(3))]
        return audit(city,dem,sh.STRtree([dem[0][0]]),iter(items))

    def test_both_ends_derived_from_source(self):
        top,deep,components=inventory(city_fixture())
        self.assertEqual((len(top),len(deep),len(components)),(1,1,1))
        self.assertTrue(components[0]['passed'])
        self.assertAlmostEqual(top[0]['mouthWidthM'],4)

    def test_ground_entry_both_sides_and_middle_slope_blocked(self):
        for x,base in [(-1,0),(.8,-.2),(6,-1.5),(11.8,-2.95),(12.8,-3)]:
            with self.subTest(x=x):
                self.assertFalse(self.check_meshes([('tunnel_wall_side',wall(x,base,base+1))])['passed'])

    def test_legitimate_high_header_and_buried_foundation_pass(self):
        self.assertTrue(self.check_meshes([('portal_guard_side',wall(12,-.5,1.1)),
            ('tunnel_wall_bottom',wall(6,-3,-1.5))])['passed'])
        # A header extending down to the railway floor is a genuine blockage.
        self.assertFalse(self.check_meshes([('portal_guard_side',wall(12,-3,1.1))])['passed'])

    def test_lateral_walls_are_preserved(self):
        a=np.array([[[0,1.1,0],[12,1.1,0],[12,-3,0]],[[0,1.1,0],[12,-3,0],[0,0,0]]])
        self.assertTrue(self.check_meshes([('tunnel_wall_side',np.concatenate([a,a+[0,0,-4]]))])['passed'])

    def test_missing_ground_connection_not_silently_ignored(self):
        c=city_fixture();c['features']=[f for f in c['features'] if f['id']!='ground']
        self.assertFalse(self.check_meshes([],c)['passed'])

    def test_reversed_axis_and_wrong_level(self):
        c=city_fixture()
        for f in c['features']:
            if f['geometryType']!='polyline':continue
            f['coordinates'].reverse();p=f['properties']
            p['db_segment_begin_level'],p['db_segment_end_level']=p['db_segment_end_level'],p['db_segment_begin_level']
        self.assertTrue(self.check_meshes([],c)['passed'])
        next(f for f in c['features'] if f['id']=='ground')['properties']['db_segment_begin_level']=1
        self.assertFalse(self.check_meshes([],c)['passed'])


if __name__=='__main__':unittest.main()
