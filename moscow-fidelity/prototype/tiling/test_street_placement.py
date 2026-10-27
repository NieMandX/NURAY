import json,tempfile,unittest
from pathlib import Path
import numpy as np
from street_placement import evaluate,model_rule,owner,station_points,SurfaceSampler,GROUND_NAMES,transform,clip_segment
from street_library import Mesh,model
from object_geometry import pack

class StreetPlacementTests(unittest.TestCase):
    def test_source_aliases_override_internal_numeric_enum(self):
        p={'sublayer':65535,'db_sublayer':'Porch','objectClass':65535,'db_object_class':'porch'}
        self.assertTrue(evaluate(['all',['==',['get','sublayer'],'Porch'],['==',['get','objectClass'],'porch']],p))
        with self.assertRaises(ValueError):evaluate(['unsupported',1],p)
    def test_icons_and_traffic_cannot_become_models(self):
        r={'sourceRecordId':'x','layer':'Traffic_light','properties':{}}
        rules=[{'id':'fake','type':'model','style':{'modelSrc':'lamppost1'},'filter':True}]
        self.assertIsNone(model_rule(r,rules));r['layer']='Poi_trash';rules[0]['type']='point'
        self.assertIsNone(model_rule(r,rules))
    def test_source_rotation_and_axis_scale(self):
        m=np.array(transform([0,0,90],[2,3,4],[10,20,30])).reshape(3,4)
        np.testing.assert_allclose(m@np.array([1,0,0,1]),[10,20,28])
        np.testing.assert_allclose(m@np.array([0,1,0,1]),[10,24,30])
    def test_station_phase_survives_source_split(self):
        whole=[tuple(np.round(p,6)) for _,p in station_points([[0,0],[10,0]],1.3,0)]
        split=[tuple(np.round(p,6)) for coords,phase in [([[0,0],[4.1,0]],0),([[4.1,0],[10,0]],4.1)] for _,p in station_points(coords,1.3,phase)]
        self.assertEqual(whole,split)
        self.assertEqual(owner(250,250,[0,0,1000,1000],250),'1-1');self.assertIsNone(owner(1000,0,[0,0,1000,1000],250))
    def test_partial_fence_is_retained_at_region_edge(self):
        self.assertEqual(clip_segment([-5,5],[5,5],[0,0,10,10]),[[0,5],[5,5]])
        self.assertIsNone(clip_segment([-5,5],[-1,5],[0,0,10,10]))
    def test_ground_is_not_highest_bridge_or_nearest_extrapolation(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);folder=root/'canonical/full';folder.mkdir(parents=True);chunks=[]
            for name,y in [('land',0),('pedestrian_path',.1),('green_curb_top',.2),('roadbed_overpass',8)]:
                m=Mesh();m.quad([[0,y,0],[0,y,10],[10,y,10],[10,y,0]],0);t,a=m.arrays();f=f'{name}.gz';meta=pack(t,a,folder/f);chunks.append(dict(id=len(chunks),name=name,file=f,**meta))
            g=SurfaceSampler(root,{'chunks':chunks},GROUND_NAMES)
            self.assertAlmostEqual(g.ground(3,4)['height'],.2,places=6)
            self.assertIsNone(g.ground(11,4))
    def test_library_is_finite_and_bounded(self):
        from street_placement import MODELS
        for name in MODELS:
            t,m=model(name).arrays();self.assertTrue(np.isfinite(t).all(),name)
            self.assertLess(t[:,:,:3].max(),10,name);self.assertLessEqual(m.max(),8)
            np.testing.assert_allclose(np.linalg.norm(t[:,:,3:6],axis=2),1,atol=1e-6)
    def test_shelter_front_matches_source_orientation(self):
        t,m=model('busstation').arrays()
        panels=t[m==3,:,:3];wide=panels[:,:,0].max(1)-panels[:,:,0].min(1)>4
        self.assertTrue(wide.any())
        self.assertLess(panels[wide,:,2].max(),0,'Back glass must not block the +Z entrance')
        self.assertLess(t[m==1,:,2].mean(),0,'Seat stays next to the back glass')
    def test_thin_long_rail_uv_has_metric_scale(self):
        m=Mesh();m.face([[0,0,0],[89,0,0],[89,0,.025]],0);t,_=m.arrays()
        np.testing.assert_allclose(t[0,2,6:],[89,.025])
    def test_seats_open_toward_provider_front(self):
        for name in ['bench1','swing3']:
            t,m=model(name).arrays();wood=t[m==1,:,:3]
            backs=wood[(wood[:,:,1]>.65).all(1)]
            self.assertTrue(len(backs),name)
            self.assertLess(backs[:,:,2].max(),0,name+' back must leave local +Z open')
    def test_cap_follows_slope_and_extends_only_deck_plane(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);folder=root/'canonical/full';folder.mkdir(parents=True)
            m=Mesh();m.quad([[0,4,0],[0,4,4],[10,6,4],[10,6,0]],0);t,a=m.arrays();meta=pack(t,a,folder/'deck.gz')
            s=SurfaceSampler(root,{'chunks':[dict(id=0,name='overpass_bottom',file='deck.gz',**meta)]},{'overpass_bottom'})
            anchor=s.hits(5,2)[0]
            self.assertAlmostEqual(s.deck_profile(0,2,anchor)['height'],4)
            self.assertAlmostEqual(s.deck_profile(10,2,anchor)['height'],6)
            self.assertAlmostEqual(s.deck_profile(11,2,anchor)['height'],6.2)
            self.assertIsNone(s.ground(11,2))

if __name__=='__main__':unittest.main()
