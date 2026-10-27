import tempfile, unittest
from pathlib import Path
import numpy as np
from PIL import Image
from railway_geometry import network,ribbon,densify,PERIOD
from railway_texture import make_texture
from object_geometry import clip_triangles

class RailwayTests(unittest.TestCase):
    def test_reversed_source_and_segmentation_preserve_metres(self):
        a=dict(id='a',points=[[0,0,0],[3,0,0]])
        b=dict(id='b',points=[[3,4,0],[3,0,0]])
        es,stats=network([b,a]);self.assertEqual(stats['components'],1)
        self.assertEqual(es[1]['station'][0],3);self.assertEqual(es[1]['station'][-1],7)
        whole,_=network([dict(id='whole',points=[[0,0,0],[3,0,0],[3,4,0]])])
        np.testing.assert_equal(whole[0]['station'],[0,3,7])
        self.assertEqual(es[0]['nodes'][1],es[1]['nodes'][0])

    def test_elevated_crossing_is_not_a_join(self):
        es,s=network([dict(id='ground',points=[[0,0,0],[4,0,0]]),dict(id='bridge',points=[[0,0,5],[4,0,5]])])
        self.assertEqual(s['components'],2)
        _,s=network([dict(id='x',points=[[-2,0,0],[2,0,0]]),dict(id='y',points=[[0,-2,0],[0,2,0]])])
        self.assertEqual(s['components'],2)

    def test_cycle_phase_closes_and_input_order_is_irrelevant(self):
        rows=[dict(id='a',points=[[0,0,0],[10,0,0]]),dict(id='b',points=[[10,0,0],[0,10,0]]),dict(id='c',points=[[0,10,0],[0,0,0]])]
        edges,stats=network(rows);other,_=network(rows[::-1])
        self.assertEqual(len(stats['cycleClosures']),1)
        self.assertEqual(stats['cycleClosures'][0]['source'],'b')
        self.assertLessEqual(abs(stats['cycleClosures'][0]['phaseCorrectionM']),PERIOD/2)
        phases={}
        for e,o in zip(edges,other):
            np.testing.assert_array_equal(e['station'],o['station'])
            for n,v in zip(e['nodes'],[e['station'][0]/PERIOD,e['station'][-1]/PERIOD]):
                if n in phases:self.assertAlmostEqual(v-phases[n],round(v-phases[n]),places=10)
                phases[n]=v

    def test_single_closed_curve_joins_geometry_and_texture(self):
        theta=np.linspace(0,2*np.pi,33);points=np.c_[10*np.cos(theta),10*np.sin(theta),np.zeros(len(theta))]
        edges,stats=network([dict(id='loop',points=points)])
        _,_,rings=ribbon(edges[0],lambda xy,e,z:np.zeros(len(xy)),0,1,np.zeros(3))
        np.testing.assert_allclose(rings[0,:,:3],rings[-1,:,:3],atol=1e-10)
        phase=rings[-1,:,7]-rings[0,:,7]
        np.testing.assert_allclose(phase,np.rint(phase),atol=1e-10)

    def test_miter_join_and_uv_continue_across_source_records(self):
        es,_=network([dict(id='a',points=[[0,0,0],[4,0,0]]),dict(id='b',points=[[4,0,0],[8,3,0]])])
        floor=lambda xy,e,z:np.zeros(len(xy))
        _,_,a=ribbon(es[0],floor,0,1,np.zeros(3));_,_,b=ribbon(es[1],floor,0,1,np.zeros(3))
        np.testing.assert_allclose(a[-1,:,:3],b[0,:,:3],atol=1e-12)
        np.testing.assert_allclose(a[-1,:,6:],b[0,:,6:],atol=1e-12)
        np.testing.assert_allclose(np.diff(es[1]['station']),[5])

    def test_tile_cut_keeps_unwrapped_uv_and_material_bands(self):
        es,_=network([dict(id='a',points=[[0,0,0],[10,0,0]])])
        t,m,_=ribbon(es[0],lambda xy,e,z:np.zeros(len(xy)),0,1,np.zeros(3))
        left,lm=clip_triangles(t,m,[-1,-3,5,3]);right,rm=clip_triangles(t,m,[5,-3,11,3])
        for ts,ms in ((left,lm),(right,rm)):
            cut=ts[np.abs(ts[:,:,0]-5)<1e-9]
            np.testing.assert_allclose(cut[:,7],5/PERIOD)
            self.assertEqual(set(ms),{0,1})
            np.testing.assert_allclose(ts[:,:,7],ts[:,:,0]/PERIOD)

    def test_repeat_edges_are_identical_and_rails_continuous(self):
        with tempfile.TemporaryDirectory() as d:
            name,_=make_texture(d);a=np.asarray(Image.open(Path(d)/name))
            np.testing.assert_equal(a[0],a[-1]);np.testing.assert_equal(a[:,0],a[:,-1])
            for x in (136,375):self.assertLess(float(a[:,x,:].std(0).max()),.001)
            self.assertFalse(np.array_equal(a[256,256],a[0,256]))

    def test_remote_cusp_cannot_create_a_spike_inside_region(self):
        p=densify([[0,0,0],[30,0,0],[0,.1,0]])
        edges,_=network([dict(id='cusp',points=p)])
        floor=lambda xy,e,z:np.zeros(len(xy))
        with self.assertRaises(ValueError):ribbon(edges[0],floor,0,1,np.zeros(3))
        t,m,_=ribbon(edges[0],floor,0,1,np.zeros(3),bounds=[-2,-2,5,2])
        self.assertEqual(edges[0]['outsideRegionMiters'],1)
        self.assertLess(np.abs(t[:,:,2]).max(),5)
        with self.assertRaises(ValueError):
            ribbon(edges[0],floor,0,1,np.zeros(3),bounds=[25,-2,35,2])

if __name__=='__main__':unittest.main()
