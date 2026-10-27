import json, tempfile, unittest
from pathlib import Path
import numpy as np
from fence_geometry import build, resolve, profile, prism, TYPES, DEFAULT
from street_library import Mesh
from street_placement import SurfaceSampler
from object_geometry import pack

RULES=json.loads((Path(__file__).parents[2]/'diagnostics/source-catalog/inventory.json').read_text())['sourceRulesByLayer']['Fence']

def record(code,coords=((0,0),(8,0)),phase=0,cut=False,rid='line'):
    p=dict(db_sublayer='Fence',componentDistanceStart=phase,beginningIsCut=int(cut),endingIsCut=int(cut))
    if code is not None:p['db_fence_type']=code
    return dict(sourceRecordId=rid,layer='Fence',properties=p,source=dict(coordinateStepM=1),coordinatesMSK=[[x,-z,0] for x,z in coords])

class FenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);(self.root/'canonical/full').mkdir(parents=True)
        self.city=dict(originMSK=[0,0,0],boundsMSK=[-20,-20,20,20])
    def tearDown(self):self.tmp.cleanup()
    def ground(self,segments=((0,4,2,0),(4,8,0,2))):
        mesh=Mesh()
        for a,b,ha,hb in segments:mesh.quad([[a,ha,-3],[a,ha,3],[b,hb,3],[b,hb,-3]],0)
        t,m=mesh.arrays();meta=pack(t,m,self.root/'canonical/full/land.gz')
        return SurfaceSampler(self.root,dict(chunks=[dict(id=0,name='land',file='land.gz',**meta)]),{'land'})
    def test_actual_source_style_maps_all_seven_types(self):
        expected=['fenceconcrete','fencebrick','fencewood','fencemetalhigh','fencemetallow','fencetreehigh','fencetreelow']
        for code,resource in enumerate(expected):
            s=resolve(record(code),RULES);self.assertEqual(s['resource'],resource);self.assertEqual(s['typeStatus'],'source')
        for code,status in [(None,'missing'),(7,'unknown-code'),(999,'unknown-code')]:
            s=resolve(record(code),RULES);self.assertEqual(s['resource'],'fencedefault');self.assertEqual(s['typeStatus'],status)
    def test_closed_sections_have_outward_winding(self):
        for code in range(7):
            m=Mesh();profile(m,[0,0],[3,0],0,0,resolve(record(code),RULES));t,_=m.arrays();p=t[:,:,:3]
            volume=np.einsum('ij,ij->i',p[:,0],np.cross(p[:,1],p[:,2])).sum()/6
            self.assertGreater(volume,0,code)
            np.testing.assert_allclose(np.linalg.norm(t[:,:,3:6],axis=2),1,atol=1e-8)
    def test_solid_wall_follows_valley_instead_of_endpoint_chord(self):
        _,objects,_,_,_=build([record(0)],self.city,self.ground(),RULES)
        contacts=objects[0]['groundProfile'];self.assertTrue(any(0 in p['heights'] for p in contacts))
        self.assertTrue(all(p['b'][0]<=4.0001 or p['a'][0]>=3.9999 for p in contacts))
    def test_void_is_not_bridged(self):
        _,objects,_,_,stats=build([record(0)],self.city,self.ground(((0,3,0,0),(5,8,0,0))),RULES)
        self.assertAlmostEqual(stats['unsupportedGroundM'],2)
        for p in objects[0]['groundProfile']:self.assertTrue(p['b'][0]<=3 or p['a'][0]>=5)
    def test_bounded_contact_keeps_source_xy(self):
        mesh=Mesh();mesh.quad([[-1,0,.01],[-1,0,3],[9,0,3],[9,0,.01]],0)
        t,m=mesh.arrays();meta=pack(t,m,self.root/'canonical/full/strip.gz')
        g=SurfaceSampler(self.root,dict(chunks=[dict(id=0,name='land',file='strip.gz',**meta)]),{'land'})
        _,objects,_,_,stats=build([record(0)],self.city,g,RULES)
        self.assertAlmostEqual(stats['unsupportedGroundM'],0)
        for p in objects[0]['groundProfile']:
            self.assertEqual(p['a'][1],0);self.assertEqual(p['b'][1],0);self.assertAlmostEqual(np.linalg.norm(p['groundOffsetM']),.025)
    def test_phase_and_pickets_survive_source_split(self):
        g=self.ground(((0,8,0,0),));whole=build([record(3,cut=True)],self.city,g,RULES)[1]
        split=build([record(3,((0,0),(3.71,0)),cut=True,rid='a'),record(3,((3.71,0),(8,0)),phase=3.71,cut=True,rid='b')],self.city,g,RULES)[1]
        points=lambda objects:sorted((p['kind'],*np.round(p['point'],6)) for o in objects for p in o['uprights'])
        self.assertEqual(points(whole),points(split))
        self.assertFalse(any(abs(p['point'][0]-3.71)<.001 for o in split for p in o['uprights']))
    def test_materials_and_silhouettes_are_distinct(self):
        g=self.ground(((0,8,0,0),));counts=[]
        for code,mat in [(0,2),(1,9),(2,1),(3,0),(4,0),(5,10),(6,10),(None,0)]:
            mesh,objects,_,_,_=build([record(code)],self.city,g,RULES);t,m=mesh.arrays()
            self.assertTrue(np.isfinite(t).all());self.assertIn(mat,m)
            if code in [2,3,4]:self.assertGreater(sum(p['kind']=='picket' for p in objects[0]['uprights']),30)
            if code in [5,6]:self.assertEqual(objects[0]['uprights'],[])
            counts.append(len(t))
        self.assertGreater(counts[3],counts[-1]*3)
    def test_canonical_generation_is_independent_of_transport_grid(self):
        g=self.ground();a=build([record(3)],dict(self.city,transportTileSizeM=2),g,RULES)[0].arrays()
        b=build([record(3)],dict(self.city,transportTileSizeM=5),g,RULES)[0].arrays()
        np.testing.assert_array_equal(a[0],b[0])
    def test_revision_scope_keeps_ancestor_changes(self):
        from landscape_validation import changed_since_base
        self.assertEqual(changed_since_base(dict(changedChunks=[127],previousRevision=dict(changedChunks=[dict(id=113)],previousRevision=dict(materialRemaps=[dict(id=7)])))),{7,113,127})
    def test_generated_profile_on_raised_ground_boundary(self):
        import copy,shapely as sh
        from prepare_fence_types import profile_ground
        c=json.loads((Path(__file__).parents[1]/'fixtures/foundation-rounded-base-probe.json').read_text())
        g=object.__new__(SurfaceSampler);g.tris=np.array(c['triangles']);g.refs=c['references']
        g.polys=sh.polygons(g.tris[:,:,[0,2]]);g.tree=sh.STRtree(g.polys)
        a,b=np.array(c['a'])[[0,2]],np.array(c['b'])[[0,2]]
        _,objects,_,_,_=build([record(0,coords=[a,b])],dict(originMSK=[0,0,0],boundsMSK=[-5000,-5000,5000,5000]),g,RULES)
        self.assertTrue(objects[0]['groundProfile'])
        for p in objects[0]['groundProfile']:
            for s in [.1,.5,.9]:
                q=np.array(p['a'])*(1-s)+np.array(p['b'])*s;expected=np.dot(p['heights'],[1-s,s])
                self.assertGreater(expected-g.ground(*(q+p['groundOffsetM']))['height'],.09)
                self.assertLess(abs(profile_ground(g,p,s)['height']-expected),1e-10)
            edge=b-a;direction=np.array([-edge[1],edge[0]])/np.linalg.norm(edge)
            if direction@(g.tris[1][:,[0,2]].mean(axis=0)-(a+b)/2)>0:direction=-direction
            moved=copy.deepcopy(p);moved['a']=(np.array(p['a'])+direction*1e-7).tolist();moved['b']=(np.array(p['b'])+direction*1e-7).tolist()
            self.assertGreater(np.mean(p['heights'])-profile_ground(g,moved,.5)['height'],.09)

if __name__=='__main__':unittest.main()
