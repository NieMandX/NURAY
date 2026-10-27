import unittest,tempfile,json
from pathlib import Path
import numpy as np
import shapely as sh
from waterfront import wall_geometry,bank_triangles
from waterfront_finish import finished_bank,cornice_geometry,PROJECTION,HEIGHT,shoreline_uv

class FinishTests(unittest.TestCase):
 def bank(self,g,bounds):
  _,_,b=wall_geometry(g,np.array([g],dtype=object),np.array([[.01,0,3.]]),[],bounds,[0,0,0]);return b
 def test_wall_preserved_and_wet_band_not_repeated(self):
  b=self.bank(sh.box(0,0,8,5),[-1,-1,9,6]);b['top']+=.2
  old=bank_triangles(b,[0,0,0]);new=finished_bank(b,[0,0,0])
  np.testing.assert_array_equal(old[:,:,:6],new[:,:,:6]);self.assertEqual(set(new[:,:,7].ravel()),{0.,1.})
 def test_continuous_limited_profile_on_ring_with_hole(self):
  g=sh.box(0,0,12,7).difference(sh.box(2,2,4,4));b=self.bank(g,[-1,-1,13,8]);tri,stats=cornice_geometry(b,[0,0,0],g)
  self.assertTrue(np.isfinite(tri).all());self.assertLessEqual(stats['maxProjectionM'],PROJECTION*2+1e-9)
  self.assertTrue(sh.covers(g.buffer(.00004),sh.points(np.column_stack([tri[:,:,0].ravel(),-tri[:,:,2].ravel()]))).all())
  self.assertLessEqual(tri[:,:,1].max(),b['top'].max()+1e-8);self.assertGreaterEqual(tri[:,:,1].min(),b['top'].min()-HEIGHT-1e-8)
  self.assertTrue(np.allclose(np.linalg.norm(tri[:,:,3:6],axis=2),1))
 def test_closed_ring_has_integer_uv_period(self):
  b=self.bank(sh.box(0,0,8.3,5.2),[-1,-1,10,7]);uv=shoreline_uv(b)
  self.assertAlmostEqual(uv.min(),0);self.assertAlmostEqual(uv.max(),round(uv.max()))
  tri,_=cornice_geometry(b,[0,0,0],sh.box(0,0,8.3,5.2))
  horizontal=abs(tri[:,:,4].mean(1))>.99
  self.assertTrue((tri[horizontal,:,4].mean(1)>0).any());self.assertTrue((tri[horizontal,:,4].mean(1)<0).any())
 def test_no_acquisition_cross_wall_and_narrow_waterway(self):
  g=sh.box(0,0,8,.08);b=self.bank(g,[0,-1,9,1]);tri,_=cornice_geometry(b,[0,0,0],g)
  self.assertTrue(sh.covers(g.buffer(.00004),sh.points(np.column_stack([tri[:,:,0].ravel(),-tri[:,:,2].ravel()]))).all())
  self.assertFalse(((tri[:,:,0]==0).all(1)&(np.ptp(tri[:,:,2],axis=1)>.08)).any())
 def test_fresh_waterfront_installs_current_finish(self):
  from waterfront import install
  from waterfront_finish import MATERIAL,POLICY
  from object_geometry import pack
  xyz=np.array([[[0,3,0],[10,3,0],[10,3,-4]],[[0,3,0],[10,3,-4],[0,3,-4]]],float)
  tri=np.concatenate([xyz,np.tile([0,1,0],(2,3,1)),np.zeros((2,3,2))],axis=2)
  with tempfile.TemporaryDirectory() as d:
   folder=Path(d);c=dict(id=0,name='water',category='water',file='water.gz',**pack(tri,np.zeros(2),folder/'water.gz'))
   scene=dict(origin=[0,0,0],chunks=[c],instances=[dict(mesh=0,matrix=[1,0,0,0,0,1,0,0,0,0,1,0])],materials=[dict(name='water')],textures={},stats=dict(uniqueTriangles=2,expandedTriangles=2))
   source=dict(layer='Water_area',geometryType='polygon',coordinates=[[-1,0,0],[11,0,0],[-1,4,0],[11,4,0]])
   row=dict(id='water:1',geometry=json.loads(sh.to_geojson(sh.box(0,0,10,4))),heightPlane=[0,0,3],material=0)
   result=install([source],[row],[],scene,folder,[0,-1,10,10])
   self.assertEqual(scene['waterfront']['finish']['policy'],POLICY)
   self.assertEqual(scene['materials'][-1],MATERIAL)
   self.assertGreater(scene['waterfront']['stats']['corniceTriangles'],0)
   self.assertFalse(scene['waterfront']['finish']['policy']['highParapet'])
 def test_subprecision_bridge_residue_and_safe_bank_cache(self):
  from waterfront import install
  from object_geometry import pack
  import copy
  xyz=np.array([[[1000,3,0],[1010,3,0],[1010,3,-4]],[[1000,3,0],[1010,3,-4],[1000,3,-4]]],float)
  tri=np.concatenate([xyz,np.tile([0,1,0],(2,3,1)),np.zeros((2,3,2))],axis=2)
  def source(layer,x0,y0,x1,y1):return dict(layer=layer,geometryType='polygon',coordinates=[[x0,y0,0],[x1,y0,0],[x0,y1,0],[x1,y1,0]])
  domain=sh.box(1000,0,1010,4).difference(sh.box(1004,1,1004.00001,2))
  with tempfile.TemporaryDirectory() as d:
   folder=Path(d)/'full';folder.mkdir()
   np.savez(Path(d)/'terrain.npz',polygons=np.array([sh.to_wkb(sh.box(1000,-1,1010,5),hex=True)]),planes=np.array([[0,0,3.]]))
   c=dict(id=0,name='water',category='water',file='water.gz',**pack(tri,np.zeros(2),folder/'water.gz'))
   original=dict(origin=[0,0,0],chunks=[c],instances=[dict(mesh=0,matrix=[1,0,0,0,0,1,0,0,0,0,1,0])],materials=[dict(name='water')],textures={},stats=dict(uniqueTriangles=2,expandedTriangles=2))
   features=[source('Water_area',999,0,1011,4),source('Bridge_area',1003.9,.9,1004.1,2.1)]
   row=dict(id='water:1',geometry=json.loads(sh.to_geojson(domain)),heightPlane=[0,0,3],material=0)
   scene=copy.deepcopy(original);install(features,[row],[],scene,folder,[1000,-1,1010,5],bank_cache_key='same-input')
   self.assertGreater(scene['waterfront']['stats']['subprecisionBridgeRepairAreaM2'],0)
   self.assertEqual(scene['waterfront']['stats']['bridgeWaterTriangles'],0)
   self.assertFalse(any(c['name']=='water-bridge-continuation' for c in scene['chunks']))
   def no_rescan():
    raise AssertionError('Unchanged bank inputs should reuse the completed height scan')
    yield
   pack(tri,np.zeros(2),folder/'water.gz');repeat=copy.deepcopy(original)
   install(features,[row],no_rescan(),repeat,folder,[1000,-1,1010,5],bank_cache_key='same-input')
   self.assertEqual(scene['waterfront'],repeat['waterfront'])
if __name__=='__main__':unittest.main()
