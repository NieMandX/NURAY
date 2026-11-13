import tempfile,unittest,types
from pathlib import Path
import numpy as np
from road_crossfall import solve
from apply_crossfall import RoadField,reproject_paint,cut_fill_faces
from build_scene import Builder
import shapely as sh

class CrossfallTest(unittest.TestCase):
    def test_batched_signed_edges_match_individual_walls(self):
        rng=np.random.default_rng(71);a=rng.uniform(-5,5,(120,2));direction=rng.normal(size=(120,2));direction/=np.linalg.norm(direction,axis=1)[:,None]
        xy=np.stack([a,a+direction*rng.uniform(.01,2,(120,1))],axis=1)
        terrain=types.SimpleNamespace(sample=lambda q:np.asarray(q)[:,0]*.3+9)
        field=types.SimpleNamespace(sample=lambda q:(np.sin(np.asarray(q)[:,0])*.5,np.zeros(len(q)),np.abs(np.sin(np.asarray(q)[:,1]))))
        offset=lambda q:np.where(np.asarray(q)[:,0]>0,.075,.175)
        out=[];builder=Builder.__new__(Builder);builder.alt=8;builder.add=lambda t,*args:out.append(t)
        for edge in xy:
            if field.sample([edge.mean(0)])[2][0]<.065:continue
            d=edge[1]-edge[0];n=np.array([d[1],-d[0]])/np.linalg.norm(d)*.015
            base=terrain.sample(edge);old=base+offset(edge+n);bottom=base+.035+field.sample(edge)[0];connection=np.maximum(bottom,np.minimum(old,bottom+.1))
            if np.max(abs(connection-old))<.003:continue
            low=lambda q:np.interp(np.linalg.norm(q-edge[0],axis=1),[0,np.linalg.norm(d)],old)
            high=lambda q:np.interp(np.linalg.norm(q-edge[0],axis=1),[0,np.linalg.norm(d)],connection)
            builder.wall(sh.LineString(edge),low,high,8,'test')
        np.testing.assert_array_equal(cut_fill_faces(xy,terrain,field,offset,8),np.concatenate(out))

    def test_fine_patch_meets_unsplit_road_edge(self):
        # Two fine triangles meet the long edge of their coarse neighbour.
        xy=np.array([[[0,0],[8,0],[0,8]],[[0,-8],[4,0],[0,0]],[[0,-8],[8,0],[4,0]]],float)
        xy[1:,1:,1]+=1e-15 # clipping roundoff must not create separate heights
        z=xy[:,:,0]*.08+xy[:,:,1]*.35
        with tempfile.TemporaryDirectory() as d:
            report=solve(xy,z,np.array([[[0,-8],[0,8]]],float),d)
            f=RoadField(Path(d)/'road-height-field.npz')
            self.assertGreater(report['edgeContinuityConstraints'],0)
            self.assertLess(report['edgeContinuityMaxErrorM'],1e-6)
            self.assertAlmostEqual(f.z[1,1],(f.z[0,0]+f.z[0,1])/2,places=6)
            delta,original,_=f.sample(xy.reshape(-1,2))
            np.testing.assert_allclose(delta+original,f.z.ravel(),atol=1e-6)

    def test_paint_is_split_at_road_profile_kink(self):
        xy=np.array([[[0,0],[4,0],[0,4]],[[4,0],[4,4],[0,4]]],float)
        z=np.array([[0,0,0],[0,1,0]],float)
        paint_xy=np.array([[[0,0],[4,0],[4,4]],[[0,0],[4,4],[0,4]]],float)
        t=np.zeros((3,3,8));t[:2,:,0]=paint_xy[:,:,0];t[:2,:,2]=-paint_xy[:,:,1];t[:2,:,1]=.02;t[:2,:,4]=1
        t[2]=t[0];t[2,:,1]+=10 # separate deck paint must retain its own level
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'field.npz';np.savez(p,xy=xy,z0=np.zeros((2,3)),z=z);f=RoadField(p)
            out,m,colors,report=reproject_paint(t,np.zeros(3,int),np.zeros((3,3)),f)
            np.testing.assert_array_equal(out[0],t[2]);ground=out[1:]
            centers=ground[:,:,[0,2]].mean(1)*[1,-1];delta,original,_=f.sample(centers)
            np.testing.assert_allclose(ground[:,:,1].mean(1),delta+original+.02,atol=1e-10)
            self.assertEqual(len(ground),4);self.assertAlmostEqual(report['clippedAreaM2'],0)

    def test_shared_intersection_and_longitudinal_grade(self):
        # Longitudinal 30% grade is intentional. Crossfall starts at 40%.
        xy=np.array([[[0,-4],[12,-4],[0,4]],[[12,-4],[12,4],[0,4]]],float)
        z=xy[:,:,0]*.3+xy[:,:,1]*.4
        with tempfile.TemporaryDirectory() as d:
            report=solve(xy,z,np.array([[[0,0],[12,0]]],float),d)
            f=RoadField(Path(d)/'road-height-field.npz');new=f.z
            gradients=np.linalg.solve(xy[:,1:]-xy[:,:1],(new[:,1:]-new[:,:1])[:,:,None])[:,:,0]
            self.assertLessEqual(report['afterMaxDegrees'],5)
            np.testing.assert_allclose(gradients[:,0],.3,atol=1e-6)
            self.assertEqual(new[0,1],new[1,0]);self.assertEqual(new[0,2],new[1,2])
            delta,original,distance=f.sample([[6,0],[6,5]])
            np.testing.assert_allclose(original,[1.8,3.4],atol=1e-8)
            np.testing.assert_allclose(distance,[0,1],atol=1e-8)

if __name__=='__main__':unittest.main()
