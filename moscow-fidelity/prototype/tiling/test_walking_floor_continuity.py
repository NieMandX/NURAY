import gzip,json,unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
import shapely as sh
from walking_floor_continuity import WalkingFloorContinuity
from transport_clearance_validation import source_candidates,volumes
from interface_validation import check_interfaces


class WalkingFloorChecks(unittest.TestCase):
    def make(self, gap=.02, height=0., slope=.3, same_side=False):
        p=sh.box(gap if not same_side else -3,0,3 if not same_side else -gap,4)
        c=np.array([slope,0,height-slope*(gap if not same_side else -gap)])
        return dict(id='ramp',transport='pedestrian',part='roadbed_overpass',tiers=[1],poly=p,patches=[(p,c)])

    def resolve(self,row):
        return WalkingFloorContinuity([row]).owners(sh.LineString([(0,0),(0,4)]),sh.box(-4,0,0,4),{'platform'})

    def test_continuous_zero_height_edge_across_drawing_tier(self):
        self.assertEqual(self.resolve(self.make()),{'ramp'})

    def test_high_unconnected_crossing_does_not_replace_ground_floor(self):
        self.assertFalse(self.resolve(self.make(height=3.)))
        self.assertFalse(self.resolve(self.make(gap=.3)))
        self.assertFalse(self.resolve(self.make(same_side=True)))

    def test_one_touching_zero_vertex_is_not_a_continuous_edge(self):
        row=self.make();row['patches']=[(row['poly'],np.array([.3,.5,-.006]))]
        self.assertFalse(self.resolve(row))

    def test_transverse_edge_does_not_count_as_parallel_continuation(self):
        row=self.make();p=sh.box(-2,3.99,2,5)
        row.update(poly=p,patches=[(p,np.array([0,.3,-3.99*.3]))])
        self.assertFalse(self.resolve(row))

    def actual(self):
        path=Path(__file__).resolve().parents[1]/'fixtures/walking-platform-floor.json.gz'
        with gzip.open(path,'rt') as f:data=json.load(f)
        city=data['city'];rows=source_candidates(city)
        dem=[(sh.geometry.shape(p),np.asarray(c)) for p,c in data['dem']]
        # Exact retained source interface; unrelated out-of-fixture entrances
        # have no complete source floors and are not part of this local test.
        with patch('transport_clearance_validation.inventory',return_value=(rows,[data['interface']],[])):
            gates,_,source=volumes(city,dem,sh.STRtree([p for p,_ in dem]))
        self.assertTrue(source['passed'])
        return gates,[(k,np.asarray(v)) for k,v in data['meshes']]

    def test_retained_moscow_slab_underside_is_below_its_actual_floor(self):
        gates,meshes=self.actual()
        self.assertTrue(check_interfaces(gates,meshes)['passed'])

    def test_real_obstruction_above_same_ramp_is_still_rejected(self):
        gates,meshes=self.actual()
        shifted=[(k,v+[0,.25,0]) for k,v in meshes if k=='overpass_side']
        self.assertFalse(check_interfaces(gates,shifted)['passed'])


if __name__=='__main__':unittest.main()
