"""Wide vehicle/walking clearance regressions, independent of city coordinates."""
import json,sys,unittest
from pathlib import Path
import numpy as np
import shapely as sh
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from transport_clearance_validation import inventory,audit,source_terminal_evidence
from test_railway_tunnels import wall


def fixture(mode='pedestrian',overpass=False):
    features=[];surfaces=[];layer='Roadbed_underpasses' if mode=='pedestrian' else 'Main_Roadbed'
    sign=1 if overpass else -1
    def slab(owner,x0,x1,kind,height,level):
        xy=np.array([[x0,0],[x0,4],[x1,0],[x1,4]],float)
        xyz=np.c_[xy,xy@np.array(height[:2])+height[2]]
        features.append(dict(id=owner,layer=layer,geometryType='polygon',coordinates=xyz.tolist(),
            properties=dict(db_road_part=kind,db_tiers=[level])))
        surfaces.append(dict(owner=owner,kind=kind,tiers=[level],geometry=sh.geometry.mapping(sh.box(x0,0,x1,4)),
            heightPlane=(np.array(height)+[0,0,.1 if mode=='pedestrian' else 0]).tolist()))
    slab('slab',0,12,'roadbed_overpass' if overpass else 'roadbed_tunnel_descent',[sign*.25,0,0],sign)
    if not overpass:slab('tunnel',12,20,'roadbed_tunnel',[0,0,-3],-1)
    if mode=='vehicle':slab('ground',-6,0,'roadbed_flat',[0,0,0],0)
    else:
        for owner,coords,tier,begin,end in [('ground',[[-5,2,0],[0,2,0]],0,0,0),('axis',[[0,2,0],[12,2,0]],sign,0,sign)]:
            features.append(dict(id=owner,layer='Pedestrian_road',geometryType='polyline',coordinates=coords,
                properties=dict(db_tiers=[tier],db_segment_begin_level=begin,db_segment_end_level=end,beginningIsCut=1,endingIsCut=1)))
    return dict(features=features,surfaces=surfaces,boundsMSK=[-10,-10,25,20],originMSK=[0,0,0],
        groundRoadGeometry=sh.geometry.mapping(sh.box(-6,0,0,4) if mode=='vehicle' else sh.Polygon()))


class TransportClearanceChecks(unittest.TestCase):
    def test_ground_overlap_uses_structural_floor(self):
        c=fixture('vehicle',True)
        ground=next(s for s in c['surfaces'] if s['owner']=='ground')
        ground['geometry']=sh.geometry.mapping(sh.box(-6,0,1,4))
        # Below the ramp, above the old ground: buried concrete is harmless.
        r=self.check_meshes([('overpass_side',wall(.8,.03,.15))],c)
        self.assertTrue(r['fullWidth']['passed'])
        self.assertFalse(self.check_meshes([('overpass_side',wall(.8,.21,.7))],c)['fullWidth']['passed'])

    def test_covered_tunnel_interiors_are_explicitly_outside_exposed_scope(self):
        c=fixture('vehicle')
        # Continue the buried tunnel in another display tier.
        c['features'].append(dict(id='covered',layer='Main_Roadbed',geometryType='polygon',
            coordinates=[[20,0,-3],[20,4,-3],[24,0,-3],[24,4,-3]],properties=dict(db_road_part='roadbed_tunnel',db_tiers=[-2])))
        c['surfaces'].append(dict(owner='covered',kind='roadbed_tunnel',tiers=[-2],
            geometry=sh.geometry.mapping(sh.box(20,0,24,4)),heightPlane=[0,0,-3]))
        r=self.check_meshes([('land',wall(20,-2.9,0))],c)
        self.assertEqual(len(r['source']['coveredInteriorInterfaces']),1)
        self.assertTrue(r['fullWidth']['passed'])
        # The exposed descent-to-tunnel portal still detects its own cap.
        self.assertFalse(self.check_meshes([('tunnel_wall_side',wall(12,-3,0))],c)['fullWidth']['passed'])

    def check_meshes(self,items,city=None):
        c=city or fixture();dem=[(sh.box(*c['boundsMSK']),np.zeros(3))]
        return audit(c,dem,sh.STRtree([dem[0][0]]),iter(items))

    def test_pedestrian_generic_layer_and_source_cut_flags(self):
        _,interfaces,cs=inventory(fixture())
        self.assertEqual(len(interfaces),2)
        self.assertEqual(len(cs),1)
        self.assertTrue(cs[0]['passed'])
        self.assertTrue(self.check_meshes([])['passed'])

    def test_caps_before_after_and_midway(self):
        for mode,offset in [('vehicle',0),('pedestrian',.1)]:
            for x,base in [(-1,0),(.8,-.2),(6,-1.5),(11.8,-2.95),(12.8,-3)]:
                with self.subTest(mode=mode,x=x):
                    r=self.check_meshes([('tunnel_wall_side',wall(x,base+offset,base+offset+1))],fixture(mode))
                    self.assertFalse(r['passed'])

    def test_bridge_outer_overhang_cap(self):
        for mode,offset in [('vehicle',0),('pedestrian',.1)]:
            c=fixture(mode,True)
            self.assertFalse(self.check_meshes([('parapet_side',wall(-1,offset,offset+1))],c)['passed'])

    def test_header_buried_foundation_and_lateral_wall(self):
        side=np.array([[[0,1.1,0],[12,1.1,0],[12,-3,0]],[[0,1.1,0],[12,-3,0],[0,.1,0]]])
        r=self.check_meshes([('tunnel_wall_side',side),('portal_guard_side',wall(12,-.5,1.1)),('overpass_bottom',wall(6,-3,-1.4))])
        self.assertTrue(r['passed']);self.assertTrue(r['fullWidth']['passed'])
        self.assertFalse(self.check_meshes([('portal_guard_side',wall(12,-3,1.1))])['passed'])

    def test_partial_edge_intrusions_are_reported_not_hidden(self):
        edge=wall(.8,-.1,.9);edge[:,:,2]*=.1
        r=self.check_meshes([('tunnel_wall_side',edge)])
        self.assertTrue(r['passed'])
        self.assertFalse(r['fullWidth']['passed'])
        self.assertGreater(sum(c['blockingFaceAreaM2'] for c in r['fullWidth']['checks']),0)

    def test_short_centre_kerb_is_not_reported_as_a_full_cap(self):
        nib=wall(-.8,.1,.2);nib[:,:,2]=nib[:,:,2]*.025-1.95
        r=self.check_meshes([('curb_back',nib)])
        self.assertTrue(r['passed'])
        self.assertFalse(r['fullWidth']['passed'])
        self.assertTrue(r['partialContacts'])
        self.assertLess(next(c for c in r['checks'] if 'blockedCoreSpanFraction' in c)['blockedCoreSpanFraction'],.1)

    def test_split_cap_is_still_detected(self):
        left=wall(-1,.1,1.1);left[:,:,2]*=.5
        right=left+[0,0,-2]
        self.assertFalse(self.check_meshes([('curb_back',left),('parapet_side',right)])['passed'])

    def test_missing_source_endpoint_fails_coverage(self):
        c=fixture();c['features']=[f for f in c['features'] if f['id']!='ground']
        self.assertFalse(self.check_meshes([],c)['passed'])

    def test_wrong_level_and_xy_crossing_are_not_connections(self):
        c=fixture();next(f for f in c['features'] if f['id']=='ground')['properties']['db_segment_end_level']=1
        self.assertFalse(self.check_meshes([],c)['passed'])
        c=fixture();next(f for f in c['features'] if f['id']=='ground')['coordinates']=[[-5,2,0],[5,2,0]]
        self.assertFalse(self.check_meshes([],c)['passed'])

    def test_explicit_portal_does_not_require_buried_tunnel_mesh(self):
        c=fixture();c['features']=[f for f in c['features'] if f['id']!='tunnel']
        c['features'].append(dict(id='arch',layer='Roadbed_outline_underpasses',geometryType='polyline',
            coordinates=[[12,0,-3],[12,4,-3]],properties={'db_road_part':'tunnel_arch'}))
        self.assertTrue(self.check_meshes([],c)['passed'])
        c['features'][-1]['coordinates']=[[0,0,0],[0,4,0]]
        self.assertFalse(self.check_meshes([],c)['passed'])

    def test_zero_height_rim_does_not_make_a_depression_a_flat_landing(self):
        from build import plane
        ring=np.array([[0,0,0],[4,0,0],[4,4,0],[0,4,0]],float)
        patches=[]
        for i in range(4):
            t=np.array([ring[i],ring[(i+1)%4],[2,2,-3]])
            patches.append((sh.Polygon(t[:,:2]),plane(t)))
        evidence=source_terminal_evidence(sh.box(0,0,4,4),[dict(patches=patches)],[],sh.box(-1,-1,5,5))
        self.assertGreater(evidence['groundLevelBoundaryM'],15.9)
        self.assertFalse(evidence['terrainLevelWalkingSurface'])

    def test_ground_node_shared_with_another_structure_is_a_connection(self):
        c=fixture();g=next(f for f in c['features'] if f['id']=='ground')
        g['properties'].update(db_tiers=[1],db_segment_begin_level=1)
        self.assertEqual(len(inventory(c)[1]),2)
        self.assertTrue(self.check_meshes([],c)['passed'])
        g['properties']['db_segment_end_level']=1
        self.assertFalse(self.check_meshes([],c)['passed'])

    def test_walking_exit_onto_asphalt_uses_its_lower_floor(self):
        c=fixture();motor=fixture('vehicle')
        c['features'].append(next(f for f in motor['features'] if f['id']=='ground')|{'id':'asphalt'})
        c['surfaces'].append(next(f for f in motor['surfaces'] if f['owner']=='ground')|{'owner':'asphalt'})
        c['groundRoadGeometry']=motor['groundRoadGeometry']
        self.assertTrue(self.check_meshes([],c)['passed'])
        # The obstructing 8 cm curb lies below the hypothetical sidewalk plane.
        blocked=self.check_meshes([('curb_back',wall(-.8,0,.08))],c)
        self.assertFalse(blocked['fullWidth']['passed'])

    def test_missing_floor_witness_cannot_pass(self):
        c=fixture();c['surfaces']=[s for s in c['surfaces'] if s['owner']!='slab']
        with self.assertRaises(AssertionError):self.check_meshes([],c)

    def test_reversed_sources(self):
        c=fixture()
        for f in c['features']:
            f['coordinates'].reverse()
            if f['geometryType']=='polyline':
                p=f['properties'];p['db_segment_begin_level'],p['db_segment_end_level']=p['db_segment_end_level'],p['db_segment_begin_level']
        self.assertTrue(self.check_meshes([],c)['passed'])

    def test_walking_path_can_join_sideways(self):
        c=fixture(overpass=True)
        next(f for f in c['features'] if f['id']=='ground')['coordinates']=[[0,2,0],[0,8,0]]
        # Walking connectivity is a shared source node and level, not a
        # requirement that two tangents continue like a railway alignment.
        self.assertTrue(self.check_meshes([],c)['passed'])
        self.assertEqual(self.check_meshes([],c)['source']['groundWalkingEntries'],1)

    def test_curved_side_is_preserved_but_real_side_intrusion_fails(self):
        c=fixture();xy=np.array([[0,0],[0,4],[1,0],[1,3.5],[12,0],[12,4]],float)
        slab=next(f for f in c['features'] if f['id']=='slab')
        slab['coordinates']=np.c_[xy,-.25*xy[:,0]].tolist()
        next(s for s in c['surfaces'] if s['owner']=='slab')['geometry']=sh.geometry.mapping(sh.Polygon([(0,0),(12,0),(12,4),(1,3.5),(0,4)]))
        a=np.array([0,.1,-4]);b=np.array([1,-.15,-3.5]);aa=a+[0,1,0];bb=b+[0,1,0]
        side=np.array([[a,b,bb],[a,bb,aa]])
        self.assertTrue(self.check_meshes([('tunnel_wall_side',side)],c)['fullWidth']['passed'])
        # Move it across the actual source boundary, not just into an arbitrary
        # rectangle beside the curved floor: even a partial nib must fail.
        self.assertFalse(self.check_meshes([('tunnel_wall_side',side+[0,0,.15])],c)['fullWidth']['passed'])

    def test_release_connection_registry_survives_json(self):
        from prepare_passage_clearance import discover_ground
        c=fixture()
        for f in c['features']:
            if f['geometryType']=='polygon':f['semantics']={'purpose':'pedestrian'}
        cs,ifs=discover_ground(c)
        self.assertEqual(len(cs),1)
        self.assertEqual(cs,json.loads(json.dumps(cs)))
        self.assertEqual(ifs,json.loads(json.dumps(ifs)))
        self.assertGreater(sh.geometry.shape(cs[0]['landingGeometry']).area,4)


if __name__=='__main__':unittest.main()
