"""Topology regressions independent of the Moscow location and transport grid."""
import copy, unittest, sys
from pathlib import Path
from collections import defaultdict
import numpy as np
import shapely as sh
from railway_transitions import discover,source_candidates
from build import z_at,triangulate,plane
from overpasses import build as decks


def fixture():
    slab=dict(id='slab',layer='Transport_Roadbed',geometryType='polygon',
        properties={'db_road_part':'roadbed_overpass','db_tiers':[1]},
        coordinates=[[0,0,0],[0,4,0],[12,0,3],[12,4,3]])
    def rail(name,xy,tiers,begin,end):
        return dict(id=name,layer='Railroad_line',geometryType='polyline',
            properties=dict(db_tiers=tiers,db_segment_begin_level=begin,db_segment_end_level=end),
            coordinates=[[x,y,0] for x,y in xy])
    return [slab,rail('up',[(0,2),(12,2)],[1],0,1),rail('ground',[(-8,2),(0,2)],[0],0,0)]


class RailTransitions(unittest.TestCase):
    def discover(self,fs,extent=None):
        extent=extent if extent is not None else sh.box(-10,-10,20,20)
        return discover(source_candidates(fs,extent),fs,extent,1e-5,z_at)

    def test_full_width_and_side_rails(self):
        fs=fixture();cs,ifs=self.discover(fs)
        self.assertEqual(len(cs),1);self.assertAlmostEqual(cs[0]['mouthWidthM'],4)
        dem=[(sh.box(-10,-10,20,20),np.zeros(3))];groups=defaultdict(list)
        rows=[dict(kind='roadbed_overpass',tiers=[1],owner='slab',poly=sh.box(0,0,12,4),plane=np.array([.25,0,0]))]
        profiles,_=decks(rows,dem,sh.STRtree([dem[0][0]]),groups,dem[0][0],1e-5,triangulate,z_at,plane,cs)
        p=profiles[0];self.assertTrue(p['passed'])
        parapet=sh.geometry.shape(p['parapetGeometry'])
        self.assertFalse(parapet.intersects(sh.box(-1,.1,.01,3.9)))
        self.assertTrue(parapet.covers(sh.Point(5,-.9)))
        self.assertTrue(parapet.covers(sh.Point(5,4.9)))

    def test_reversed_source_direction(self):
        fs=fixture()
        for f in fs[1:]:
            f['coordinates'].reverse();p=f['properties'];p['db_segment_begin_level'],p['db_segment_end_level']=p['db_segment_end_level'],p['db_segment_begin_level']
        self.assertEqual(len(self.discover(fs)[0]),1)

    def test_cut_fragments_still_require_real_matching_peer(self):
        fs=fixture()
        for f in fs[1:]:f['properties'].update(beginningIsCut=1,endingIsCut=1)
        self.assertEqual(len(self.discover(fs)[0]),1)
        self.assertFalse(self.discover(fs[:-1])[0])

    def test_overhead_crossing_not_a_connection(self):
        fs=fixture()
        for p in fs[0]['coordinates']:p[2]+=4
        self.assertFalse(self.discover(fs)[0])

    def test_wrong_endpoint_level(self):
        fs=fixture();fs[1]['properties']['db_segment_begin_level']=1
        self.assertFalse(self.discover(fs)[0])

    def test_ground_crossing_at_interior_is_not_an_endpoint(self):
        fs=fixture();fs[2]['coordinates']=[[-4,2,0],[4,2,0]]
        self.assertFalse(self.discover(fs)[0])

    def test_grazing_or_same_side_routes_do_not_open(self):
        for xy in [[(0,2),(0,-5)],[(0,2),(8,2)]]:
            fs=fixture();fs[2]['coordinates']=[[x,y,0] for x,y in xy]
            self.assertFalse(self.discover(fs)[0])

    def test_region_cut_cannot_become_portal(self):
        self.assertFalse(self.discover(fixture(),sh.box(0,-10,20,20))[0])

    def test_endpoint_tolerance_is_bounded(self):
        fs=fixture();fs[2]['coordinates'][-1][0]=-.2
        self.assertFalse(self.discover(fs)[0])

    def test_rotation_translation_and_source_triangle_split(self):
        fs=fixture();a=.73;rot=np.array([[np.cos(a),-np.sin(a)],[np.sin(a),np.cos(a)]])
        for f in fs:
            p=np.asarray(f['coordinates'],float);p[:,:2]=p[:,:2]@rot.T+[100,200];f['coordinates']=p.tolist()
        cs,_=self.discover(fs,sh.box(80,180,130,230))
        self.assertEqual(len(cs),1);self.assertAlmostEqual(cs[0]['mouthWidthM'],4,places=4)
        fs=fixture();a=copy.deepcopy(fs[0]);a['id']='slab2'
        fs[0]['coordinates']=[[0,0,0],[0,4,0],[6,0,1.5],[6,4,1.5]]
        a['coordinates']=[[6,0,1.5],[6,4,1.5],[12,0,3],[12,4,3]]
        self.assertEqual(len(self.discover(fs+[a])[0]),1)

    def test_serialized_barrier_audit_covers_outer_deck_cap(self):
        sys.path.insert(0,str(Path(__file__).parent/'tiling'))
        from prepare_railway_entries import passages,near_passages
        from interface_validation import check_interfaces
        _,ifs=self.discover(fixture());dem=[(sh.box(-10,-10,20,20),np.zeros(3))]
        city=dict(originMSK=[0,0,0],features=fixture(),surfaces=[dict(owner='slab',kind='roadbed_overpass',
            tiers=[1],geometry=sh.geometry.mapping(sh.box(0,0,12,4)),heightPlane=[.25,0,0])])
        volumes=passages(city,ifs,dem,sh.STRtree([dem[0][0]]))
        # Wall is one metre OUTSIDE the mouth, where the old narrow audit
        # missed the actual obstruction. Coordinates here are renderer Y-up.
        wall=np.array([[[-1,0,0],[-1,.7,-4],[-1,.7,0]],[[-1,0,0],[-1,0,-4],[-1,.7,-4]]])
        blocked=check_interfaces(volumes,near_passages([('parapet_side',wall)],volumes))
        self.assertFalse(blocked['passed'])
        for shift in [[0,5,0],[0,-1,0]]:
            self.assertTrue(check_interfaces(volumes,[('parapet_side',wall+shift)])['passed'])

    def test_curved_entry_keeps_lateral_shoulder_but_rejects_cap(self):
        import json
        sys.path.insert(0,str(Path(__file__).parent/'tiling'))
        from prepare_railway_entries import passages
        from interface_validation import check_interfaces
        f=json.loads((Path(__file__).parent/'fixtures/curved-railway-entry.json').read_text())
        dem=[(sh.geometry.shape(p),np.asarray(h)) for p,h in f['terrain']]
        volumes=passages(f,[f['interface']],dem,sh.STRtree([p for p,h in dem]))
        meshes=[(name,np.asarray(ts)) for name,ts in f['meshes']]
        self.assertTrue(check_interfaces(volumes,meshes)['passed'])
        line=sh.geometry.shape(f['interface']['mouthGeometry']);xy=np.asarray(line.coords)
        middle=line.interpolate(.5,normalized=True)
        floor=min(f['surfaces'],key=lambda s:sh.geometry.shape(s['geometry']).distance(middle))
        z=z_at(floor['heightPlane'],xy)
        ox,oy,oz=f['originMSK']
        a,b=np.c_[xy[:,0]-ox,z+.1-oz,oy-xy[:,1]]
        wall=np.array([[a,b,b+[0,.9,0]],[a,b+[0,.9,0],a+[0,.9,0]]])
        self.assertFalse(check_interfaces(volumes,meshes+[('parapet_side',wall)])['passed'])


if __name__=='__main__':unittest.main()
