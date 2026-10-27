"""Packed-coordinate uncertainty must not mask a real passage barrier."""
import json,sys,unittest
from pathlib import Path
import numpy as np
import shapely as sh
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent)]
from interface_validation import check_interfaces


def gate(x0,x1,z0,z1):
    return sh.box(x0,z0,x1,z1),np.array([[1,0,0,-x0],[-1,0,0,x1],
        [0,0,1,-z0],[0,0,-1,z1],[0,1,0,-.02],[0,-1,0,.75]])


def volume(cells):
    return [(dict(id='test',ends=[dict(kind='roadbed_flat')],mouthWidthM=4),cells)]


class InterfacePrecision(unittest.TestCase):
    def test_real_serialized_sub_precision_contacts(self):
        f=json.loads((Path(__file__).resolve().parents[1]/'fixtures/serialized-interface-precision.json').read_text())
        vs=[(r['interface'],[(sh.geometry.shape(g),np.asarray(p)) for g,p in r['cells']]) for r in f['volumes']]
        report=check_interfaces(vs,[(n,np.asarray(ts)) for n,ts in f['meshes']])
        self.assertTrue(report['passed'],report)
        self.assertGreater(sum(c['blockingFaceAreaM2'] for c in report['checks']),.001)
        self.assertEqual(sum(c['resolvedBlockingFaceAreaM2'] for c in report['checks']),0)

    def test_vertical_barrier_on_internal_cell_boundary(self):
        # Eroding cells separately would hide this wall entirely.
        cells=[gate(2499,2500,-2,2),gate(2500,2501,-2,2)]
        wall=np.array([[[2500,.02,-2],[2500,.75,-2],[2500,.75,2]],
                       [[2500,.02,-2],[2500,.75,2],[2500,.02,2]]])
        report=check_interfaces(volume(cells),[('tunnel_wall_side',wall)])
        self.assertFalse(report['passed'])
        self.assertGreater(report['checks'][0]['resolvedBlockingFaceAreaM2'],2.8)

    def test_horizontal_barrier_merges_fine_tessellation(self):
        # Every input strip is narrower than rounding uncertainty, but the
        # complete 2 mm obstruction is real and must remain a failure.
        cells=[gate(2499,2501,-2,2)];triangles=[]
        for x0,x1 in zip(np.linspace(2500,2500.002,41)[:-1],np.linspace(2500,2500.002,41)[1:]):
            triangles.extend([[[x0,.1,-2],[x1,.1,-2],[x1,.1,2]],[[x0,.1,-2],[x1,.1,2],[x0,.1,2]]])
        self.assertFalse(check_interfaces(volume(cells),[('land',np.asarray(triangles))])['passed'])

    def test_real_vertical_edge_intrusion_remains_failure(self):
        cells=[gate(2499,2501,-2,2)]
        wall=np.array([[[2499.002,.02,-2],[2499.002,.75,-2],[2499.002,.75,2]]])
        self.assertFalse(check_interfaces(volume(cells),[('tunnel_wall_side',wall)])['passed'])

    def test_finely_split_cap_on_outer_boundary_stays_detectable(self):
        triangles=[]
        for z0,z1 in zip(np.linspace(0,.002,41)[:-1],np.linspace(0,.002,41)[1:]):
            triangles.extend([[[2499,.02,z0],[2499,.75,z0],[2499,.75,z1]],
                              [[2499,.02,z0],[2499,.75,z1],[2499,.02,z1]]])
        self.assertFalse(check_interfaces(volume([gate(2499,2501,-2,2)]),
                                         [('parapet_side',np.asarray(triangles))])['passed'])

    def test_unacceptable_coordinate_precision_fails(self):
        self.assertFalse(check_interfaces(volume([gate(1e6,1e6+1,0,1)]),[])['passed'])


if __name__=='__main__':unittest.main()
