import unittest,tempfile,numpy as np,shapely as sh
from pathlib import Path
from road_grade import smooth_network,NetworkGrade
from apply_crossfall import RoadField
from paving_domains import specific_square_surfaces
from finished_grade_field import harmonic_fill

class GradeTests(unittest.TestCase):
    def test_offroad_collar_preserves_planar_climb(self):
        y,x=np.mgrid[:41,:51];plane=.08*x+.25*y
        unknown=(x>3)&(x<47)&(y>2)&(y<38)
        noisy=plane.copy();noisy[unknown]+=3*np.sin(x[unknown])
        actual,_=harmonic_fill(noisy,unknown)
        np.testing.assert_allclose(actual,plane,atol=1e-7)
    def test_between_two_roads_no_nearest_height_jump(self):
        y,x=np.mgrid[:41,:51];plane=x/5
        initial=np.where(x<25,0.,10.);unknown=(x>0)&(x<50)&(y>0)&(y<40)
        initial[~unknown]=plane[~unknown]
        actual,_=harmonic_fill(initial,unknown)
        np.testing.assert_allclose(actual,plane,atol=1e-7)
        self.assertLess(abs(np.diff(actual[20])).max(),.201)
    def test_field_repeated_corners_interior_and_nearest_edge(self):
        xy=np.array([[[0.,0],[10,0],[0,10]]]);z0=xy[:,:,0]*.1;z=z0+1+xy[:,:,1]*.2
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'field.npz';np.savez(path,xy=xy,z0=z0,z=z)
            delta,old,distance=RoadField(path).sample([[0,0],[2,3],[0,0],[-2,3]])
        np.testing.assert_allclose(delta,[1,1.6,1,1.6]);np.testing.assert_allclose(old,[0,.2,0,0])
        np.testing.assert_allclose(distance,[0,0,0,2])
    def test_ripple_removed_without_flattening_climb(self):
        x=np.arange(0,402,2.);nodes=np.column_stack([x,np.zeros(len(x))]);segments=np.stack([nodes[:-1],nodes[1:]],axis=1)
        n,ids,old,z,stats=smooth_network(segments,lambda p:.08*p[:,0]+.7*np.sin(p[:,0]*2*np.pi/16),12)
        interior=(n[:,0]>60)&(n[:,0]<340)
        self.assertLess(np.max(abs(z[interior]-.08*n[interior,0])),.02)
        self.assertLess(stats['bendingEnergyAfter'],stats['bendingEnergyBefore']*.01)
    def test_disconnected_parallel_roads_do_not_average_heights(self):
        x=np.arange(0,102,2.);a=np.column_stack([x,np.zeros(len(x))]);b=a+[0,12]
        segments=np.concatenate([np.stack([a[:-1],a[1:]],1),np.stack([b[:-1],b[1:]],1)])
        n,ids,old,z,_=smooth_network(segments,lambda p:p[:,0]*.05+p[:,1],12)
        np.testing.assert_allclose(z,old,atol=1e-8)
        sampler=NetworkGrade(n,ids,z)
        np.testing.assert_allclose(sampler.sample([[50,0],[50,12]]),[2.5,14.5],atol=.001)
    def test_square_green_does_not_erase_explicit_path(self):
        empty=sh.LineString();rows=[({'layer':'roadnet_a','attributes':{'ft_type_name':'urban-roadnet-square'}},sh.box(0,0,20,20),empty),
          ({'layer':'vegetation','attributes':{}},sh.box(2,2,18,18),empty),
          ({'layer':'road','attributes':{'class':'10_park'}},sh.Polygon(),sh.LineString([(0,10),(20,10)]))]
        green,parking=specific_square_surfaces(rows)
        self.assertTrue(green.covers(sh.Point(5,5)));self.assertFalse(green.covers(sh.Point(10,10)))
        self.assertTrue(parking.is_empty)

if __name__=='__main__':unittest.main()
