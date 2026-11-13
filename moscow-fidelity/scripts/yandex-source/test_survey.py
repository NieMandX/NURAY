import unittest,tempfile,gzip
from pathlib import Path
import numpy as np
import shapely as sh
from build_scene import Terrain
from apply_survey import Reproject,normals,building_selection
from survey_terrain import safe_sample
from object_geometry import pack

class SurveyGeometryTests(unittest.TestCase):
    def test_neutral_tint_sentinel_survives_mixed_repacking(self):
        t=np.zeros((1,3,8));t[0,:,:3]=[[0,0,0],[1,0,0],[0,1,0]];normals(t)
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'mesh.gz';c=pack(t,np.array([7]),p,tints=np.array([[0,.8,1]]));raw=gzip.decompress(p.read_bytes())
            v=np.frombuffer(raw[:c['vertexBytes']],'<f4').reshape(-1,8);ix=np.frombuffer(raw[c['vertexBytes']:],'<u4')
            np.testing.assert_array_equal(v[ix,7],np.array([0,.8,1],dtype='f4'))

    def setUp(self):
        xy=np.array([[[0,0],[2,0],[1,1]],[[2,0],[2,2],[1,1]],[[2,2],[0,2],[1,1]],[[0,2],[0,0],[1,1]]],float)
        self.old=Terrain(np.concatenate([xy,np.zeros((4,3,1))],axis=2))
        self.new=Terrain(np.concatenate([xy,np.tile([0,0,1],(4,1))[:,:,None]],axis=2))
        self.patch=Reproject(self.old,self.new,self.new,sh.box(0,0,2,2),0)
    def test_shared_wall_neighbours_are_selected_as_a_component(self):
        f={'layer':'building','metadata':{}}
        rows=[(f,sh.box(x,0,x+2,2),sh.LineString()) for x in (0,2,4,9)]
        chosen,records,initial,selected=building_selection(rows,sh.Polygon(),sh.box(-1,-1,1,1))
        self.assertEqual(initial,{0});self.assertEqual(selected,{0,1,2});self.assertEqual(len(chosen),3)
    def test_skin_is_split_at_relief_ridge(self):
        t=np.zeros((1,3,8));t[0,:,:3]=[[0,.075,0],[2,.075,0],[0,.075,-2]];t[:,:,6:]=t[:,:,[0,2]];normals(t)
        out,m,tint,n=self.patch.mesh(t,np.array([7]),np.ones((1,3)))
        self.assertGreater(len(out),1);self.assertTrue((m==7).all())
        xy=out[:,:,[0,2]]*[1,-1]
        np.testing.assert_allclose(out[:,:,1].ravel(),safe_sample(self.new,xy.reshape(-1,2))+.075,atol=1e-10)
        np.testing.assert_allclose(out[:,:,6:],out[:,:,[0,2]])
        area=abs(np.linalg.det(xy[:,1:]-xy[:,:1])).sum()/2;self.assertAlmostEqual(area,2)
    def test_vertical_footing_follows_tin(self):
        t=np.zeros((2,3,8));t[0,:,:3]=[[0,0,-1],[2,0,-1],[2,.1,-1]];t[1,:,:3]=[[0,0,-1],[2,.1,-1],[0,.1,-1]];normals(t)
        out,m,c,n=self.patch.mesh(t,np.array([8,8]),np.ones((2,3)))
        self.assertGreater(len(out),2)
        xy=out[:,:,[0,2]]*[1,-1];h=out[:,:,1]-safe_sample(self.new,xy.reshape(-1,2)).reshape(-1,3)
        self.assertLess(h.min(),1e-9);self.assertLess(h.max(),.10000001)
        cross=np.cross(out[:,1,:3]-out[:,0,:3],out[:,2,:3]-out[:,0,:3]);self.assertTrue(((cross*out[:,0,3:6]).sum(1)>=0).all())
    def test_old_water_bottom_does_not_move(self):
        t=np.zeros((2,3,8));t[0,:,:3]=[[0,-2.12,-1],[2,-2.12,-1],[2,0,-1]];t[1,:,:3]=[[0,-2.12,-1],[2,0,-1],[0,0,-1]];normals(t)
        out,m,c,n=self.patch.mesh(t,np.array([8,8]),np.ones((2,3)),bank=True)
        self.assertAlmostEqual(float(out[:,:,1].min()),-2.12)
        self.assertGreater(float(out[:,:,1].max()),.9)

if __name__=='__main__':unittest.main()
