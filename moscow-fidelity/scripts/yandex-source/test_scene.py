import unittest
import collections
import numpy as np
import shapely as sh
from build_scene import cdt,clip_circle_attributes,Builder
from prepare_supplement import Terrain
from refine_boundaries import flip_faces

class GeometryContracts(unittest.TestCase):
    def test_packed_reversal_changes_only_fronts_and_normals(self):
        from object_geometry import pack,decode_normals
        import tempfile,gzip
        from pathlib import Path
        b=Builder.__new__(Builder);b.alt=0.;parts=[];b.add=lambda t,*args:parts.append(t)
        b.wall(sh.LineString([(0,0),(2,0),(2,2)]),0,4,0,'wall')
        t=np.concatenate(parts)
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'wall.gz';c=pack(t,np.zeros(len(t),dtype=np.uint32),path)
            raw=gzip.decompress(path.read_bytes());u=np.frombuffer(raw[:c['vertexBytes']],'<u4').reshape(-1,8);ix=np.frombuffer(raw[c['vertexBytes']:],'<u4').reshape(-1,3)
        v,j=flip_faces(u,ix,np.ones(len(ix),dtype=bool))
        np.testing.assert_array_equal(v[:,[0,1,2,4,5,6,7]],u[:,[0,1,2,4,5,6,7]])
        np.testing.assert_array_equal(j,ix[:,[0,2,1]])
        np.testing.assert_allclose(decode_normals(v[:,3]),-decode_normals(u[:,3]),atol=.0001)
    def test_road_curb_union_keeps_crossings_and_deck_mouths_open(self):
        road=sh.union_all([sh.box(-20,-3,0,3),sh.box(0,-3,20,3)])
        b=Builder.__new__(Builder);b.alt=0.;b.circle=sh.box(-40,-40,40,40)
        b.finished={'road':road,'water':sh.box(30,30,35,35)};b.holes=sh.Polygon();b.building_footprint=sh.Polygon()
        b.groups={('road',1,'deck'):[sh.box(18,-3,35,3)]}
        b.rows=[({'layer':'road','attributes':{'class':'crosswalk'}},sh.Polygon(),sh.LineString([(0,-5),(0,5)]))]
        b.terrain=type('Plane',(),{'sample':lambda self,xy:np.asarray(xy)[:,0]*.01})()
        b.material=lambda i:i;b.surface=lambda *args,**kw:None;b.add=lambda *args,**kw:None
        b.road_curbs()
        self.assertLess(b.road_curb.intersection(road).area,1e-8)
        self.assertLess(b.road_curb.intersection(sh.box(-1.3,-6,1.3,6)).area,1e-8)
        self.assertLess(b.road_curb.intersection(sh.box(19,-3.15,21,3.15)).area,1e-8)
        self.assertAlmostEqual(b.road_curb_audit['heightAboveRoadM'],.1)
        self.assertAlmostEqual(b.road_curb_audit['widthM'],.15)
    def test_wall_fronts_face_air_for_either_winding_and_courtyards(self):
        footprint=sh.box(0,0,20,15).difference(sh.box(5,4,15,11))
        for clockwise in (True,False):
            for inward in (True,False):
                with self.subTest(clockwise=clockwise,inward=inward):
                    p=sh.orient_polygons(footprint,exterior_cw=clockwise)
                    b=Builder.__new__(Builder);b.alt=0.;result=[]
                    b.add=lambda t,*args:result.append(t)
                    b.boundary_walls(p,0,8,0,'buildings',inward=inward)
                    t=np.concatenate(result);pos=t[:,:,:3]
                    normal=np.cross(pos[:,1]-pos[:,0],pos[:,2]-pos[:,0]);normal/=np.linalg.norm(normal,axis=1,keepdims=True)
                    np.testing.assert_allclose(t[:,:,3:6],np.repeat(normal[:,None,:],3,axis=1))
                    mid=pos.mean(1)[:,[0,2]];mid[:,1]*=-1
                    outward=normal[:,[0,2]].copy();outward[:,1]*=-1
                    self.assertTrue(np.all(sh.contains(p,sh.points(mid+outward*.001))==inward))
                    self.assertTrue(np.all(sh.contains(p,sh.points(mid-outward*.001))!=inward))
    def test_clipped_wall_keeps_front_direction(self):
        p=sh.box(0,0,20,15).difference(sh.box(5,4,15,11))
        b=Builder.__new__(Builder);b.alt=0.;result=[];b.add=lambda t,*args:result.append(t)
        b.boundary_walls(p,0,8,0,'curbs',clip=sh.box(2,-2,17,17))
        t=np.concatenate(result);mid=t[:,:,:3].mean(1)[:,[0,2]];mid[:,1]*=-1
        n=t[:,0,[3,5]].copy();n[:,1]*=-1
        self.assertFalse(sh.contains(p,sh.points(mid+n*.001)).any())
        self.assertTrue(sh.contains(p,sh.points(mid-n*.001)).all())
    def test_courtyard_is_not_filled_by_roof_triangulation(self):
        polygon=sh.box(0,0,20,15).difference(sh.box(5,4,15,11))
        triangles=sh.polygons(cdt(polygon));self.assertAlmostEqual(sh.area(triangles).sum(),polygon.area)
        self.assertLess(sh.union_all(triangles).symmetric_difference(polygon).area,1e-9)
    def test_circle_clip_preserves_interpolated_height_and_uv(self):
        t=np.zeros((1,3,8));t[0,:,:3]=[[2990,2,-10],[3020,8,-10],[2990,2,10]]
        t[:,:,6]=t[:,:,0]*.01;t[:,:,7]=t[:,:,1]*2;t[:,:,4]=1
        clipped=clip_circle_attributes(t,sh.Point(0,0).buffer(3000,quad_segs=512))
        self.assertGreater(len(clipped),0)
        self.assertLessEqual(np.linalg.norm(clipped[:,:,[0,2]],axis=2).max(),3000.00001)
        np.testing.assert_allclose(clipped[:,:,6],clipped[:,:,0]*.01)
        np.testing.assert_allclose(clipped[:,:,7],clipped[:,:,1]*2)
        np.testing.assert_allclose(clipped[:,:,1],2+(clipped[:,:,0]-2990)*.2)
    def test_markings_stay_on_their_own_overlapping_deck(self):
        b=Builder.__new__(Builder);b.approaches=collections.defaultdict(list)
        b.terrain=Terrain([[[0,0,100],[10,0,100],[0,10,100]]]);p=sh.Polygon([(0,0),(10,0),(0,10)])
        b.support={1:(np.array([p],object),sh.STRtree([p]),np.array([[0,0,106]]),p),2:(np.array([p],object),sh.STRtree([p]),np.array([[0,0,112]]),p)}
        for level,height in ((0,100),(1,106),(2,112)):
            np.testing.assert_allclose(b.deck_height(level)(np.array([[2,2],[3,3]])),height)
if __name__=='__main__':unittest.main()
