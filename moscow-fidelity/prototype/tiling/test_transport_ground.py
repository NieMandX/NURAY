import unittest
import numpy as np
import shapely as sh
from transport_ground import clip_mesh,restore_land,ground_words
from prepare_road_paint import world

def words(t):
    out=np.zeros((1,3,8),dtype='<u4')
    v=out.view('<f4')
    v[0,:,:3]=np.asarray(t)[:,[0,2,1]]*[1,1,-1]
    v[0,:,4:6]=v[0][:,[0,2]]
    out[:,:,6]=0x80000009
    return out

class GroundPartitionTests(unittest.TestCase):
    def test_sloping_ground_keeps_height_material_and_outside_area(self):
        source=words([[0,0,0],[4,0,.4],[0,4,.8]])
        cut=sh.box(1,-1,3,5)
        result=clip_mesh(source,np.zeros(3),cut)
        triangles=world(result,np.zeros(3))
        area=sh.union_all([sh.Polygon(t[:,:2]) for t in triangles])
        expected=sh.Polygon([[0,0],[4,0],[0,4]]).difference(cut)
        self.assertLess(area.symmetric_difference(expected).area,1e-6)
        np.testing.assert_allclose(triangles[:,:,2],triangles[:,:,0]*.1+triangles[:,:,1]*.2,atol=1e-6)
        self.assertTrue(np.all(result[:,:,6]==0x80000009))

    def test_vertical_curb_is_clipped_in_its_own_plane(self):
        source=words([[0,0,0],[4,0,0],[4,0,.1]])
        result=clip_mesh(source,np.zeros(3),sh.box(1,-1,3,1))
        triangles=world(result,np.zeros(3))
        for t in triangles:
            self.assertTrue(t[:,0].max()<=1.000001 or t[:,0].min()>=2.999999)
            self.assertLessEqual(t[:,2].max(),.100001)
        area=sum(np.linalg.norm(np.cross(t[1]-t[0],t[2]-t[0]))/2 for t in triangles)
        self.assertAlmostEqual(area,.1,places=6)

    def test_remote_terrain_is_unchanged(self):
        self.assertIsNone(clip_mesh(words([[0,0,0],[4,0,0],[0,4,0]]),np.zeros(3),sh.box(10,10,11,11)))

    def test_exposed_ground_uses_source_priority_and_same_sloping_terrain(self):
        def feature(name,bounds,rank,material):
            x0,y0,x1,y1=bounds
            return dict(id=name,geometryType='polygon',
                coordinates=[[x0,y0,0],[x1,y0,0],[x0,y1,0],[x1,y1,0]],
                semantics=dict(kind='land',status='built',rank=rank,material=material,
                    purpose='land-cover',construction='ground',surface='paving',styleId=None))
        dem=[(sh.box(-10,-10,10,10),np.array([.1,.2,5]))]
        region=sh.box(0,0,3,2)
        rows=restore_land(region,[feature('background',(0,0,2,2),0,1),
                                  feature('platform',(1,0,2,2),20,7)],
                          dem,sh.STRtree([dem[0][0]]))
        self.assertEqual({s['owner']:sh.geometry.shape(s['geometry']).area for s in rows},
                         {'platform':2.,'background':2.,'inferred:unclassified-land':2.})
        source=words([[-3,-3,0],[-2,-3,0],[-3,-2,0]])
        packed=ground_words(source,np.zeros(3),sh.GeometryCollection(),rows)
        np.testing.assert_array_equal(packed[:1],source)
        tris=world(packed[1:],np.zeros(3))
        np.testing.assert_allclose(tris[:,:,2],tris[:,:,0]*.1+tris[:,:,1]*.2+5.1,atol=1e-6)
        self.assertAlmostEqual(sh.union_all([sh.Polygon(t[:,:2]) for t in tris]).area,6.)
        self.assertEqual(set(packed[1:,0,6]&0x7fffffff),{1,7,8})

if __name__=='__main__':unittest.main()
