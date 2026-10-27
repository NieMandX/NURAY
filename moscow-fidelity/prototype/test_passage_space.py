"""Boundary decorations cannot consume confirmed ground approaches."""
import unittest
from collections import defaultdict
import numpy as np
import shapely as sh
from shapely.affinity import rotate,translate
from passage_space import ground_approach,walking_reserve,stable_area,APPROACH_LENGTH
from curbs import band
from landscape import plan
from tunnel_walls import build
from source_styles import load
from build import triangulate,z_at,plane,SOURCE

class PassageSpaceTests(unittest.TestCase):
    def test_full_width_outward_apron_preserves_curved_inside_edge(self):
        floor=sh.Polygon([(0,0),(0,4),(1,4.6),(4,6),(10,6),(10,0)])
        mouth=sh.LineString([(0,0),(0,4)])
        apron=ground_approach(mouth,floor)
        self.assertAlmostEqual(apron.area,4*APPROACH_LENGTH)
        self.assertTrue(apron.covers(sh.Point(-1,3.9)))
        self.assertFalse(apron.intersects(sh.Point(.5,4.4)))
        self.assertEqual(apron.intersection(floor).area,0)
        self.assertTrue(apron.equals(ground_approach(sh.reverse(mouth),floor)))

    def test_split_rotated_translated_mouth_is_invariant(self):
        floor=sh.box(0,0,10,4);full=sh.LineString([(0,0),(0,4)])
        split=sh.LineString([(0,0),(0,2),(0,4)])
        expected=ground_approach(full,floor)
        self.assertLess(expected.symmetric_difference(ground_approach(split,floor)).area,1e-9)
        f=lambda g:translate(rotate(g,37,origin=(0,0)),3000,8000)
        actual=ground_approach(f(split),f(floor))
        self.assertLess(actual.symmetric_difference(f(expected)).area,1e-4)

    def test_numeric_curb_remnant_not_extruded_real_island_preserved(self):
        tiny=sh.Polygon([(1,1),(1.1,1.1),(1.10001,1.1)])
        island=sh.box(3,3,3.03,4)
        clean=stable_area(sh.union_all([tiny,island]),1e-5)
        self.assertFalse(clean.intersects(tiny));self.assertTrue(clean.equals(island))
        extent=sh.box(0,0,10,10);road=sh.box(1,1,8,8)
        curbs=band(road,sh.box(8.00001,1,10,8),extent,1e-5)
        # Legitimate corner profiles remain, alongside real narrow islands.
        self.assertGreater(curbs.area,1)

    def test_lawn_yields_full_mouth_width_beyond_narrow_axis(self):
        floor=sh.box(0,0,10,4);mouth=sh.LineString([(0,0),(0,4)])
        landing=ground_approach(mouth,floor);extent=sh.box(-8,-4,14,8)
        f=dict(id='walk',layer='Pedestrian_road',geometryType='polyline',coordinates=[[-8,2,0],[0,2,0]],properties={})
        green=sh.box(-8,0,0,4)
        layout,_=plan([f],green,sh.Polygon(),extent,landing)
        self.assertLess(layout['raised'].intersection(landing).area,1e-9)
        self.assertLess(layout['band'].intersection(landing).area,1e-9)
        self.assertGreater(green.intersection(landing).difference(sh.LineString([(-8,2),(0,2)]).buffer(1)).area,1)

    def test_upper_landing_clips_neighbor_header_corner_not_portal(self):
        first=sh.box(0,0,10,4);second=sh.box(5,4.1,10.15,7.1)
        rows=[dict(kind='roadbed_tunnel_descent',transport='pedestrian',tiers=[-1],owner='first',poly=first,plane=np.array([-.3,0,.1])),
              dict(kind='roadbed_tunnel_descent',transport='pedestrian',tiers=[-1],owner='second',poly=second,plane=np.array([.3,0,.1-3.045]))]
        records=[]
        for owner,x0,x1,y0,y1,height in [('first',0,10,0,4,lambda x:-.3*x),('second',5,10.15,4.1,7.1,lambda x:.3*x-3.045)]:
            for y in (y0,y1):records.append(dict(id=f'{owner}:{y}',layer='Roadbed_outline_underpasses',geometryType='polyline',
                coordinates=[[x0,y,height(x0)],[x1,y,height(x1)]],properties=dict(db_road_part='border_tunnel_descent',db_tiers=[-1])))
        records.append(dict(id='arch',layer='Roadbed_outline_underpasses',geometryType='polyline',
            coordinates=[[10,0,0],[10,4,0]],properties=dict(db_road_part='tunnel_arch',db_tiers=[-1])))
        connections=[]
        for owner,mouth,foot in [('first',sh.LineString([(0,0),(0,4)]),first),('second',sh.LineString([(10.15,4.1),(10.15,7.1)]),second)]:
            connections.append(dict(kind='roadbed_tunnel_descent',sourceParents=[owner],peerParents=[],level=[-1],atGround=True,
                peerKind='pedestrian_ground',mouthGeometry=sh.geometry.mapping(mouth),landingGeometry=sh.geometry.mapping(ground_approach(mouth,foot))))
        # Source display tiers differ; both approaches are explicitly at ground.
        connections[-1]['level']=[0]
        extent=sh.box(-5,-5,20,15);dem=[(extent,np.zeros(3))];groups=defaultdict(list)
        _,report=build(rows,records,dem,sh.STRtree([extent]),groups,extent,1e-5,connections,load(SOURCE/'source/style_flat.json'),triangulate,z_at,plane)
        self.assertTrue(report['passed']);group=report['groups'][0];reserve=walking_reserve(connections)
        for g in (group['bandGeometry'],group['portalHeaders']['bandGeometry']):self.assertLess(sh.geometry.shape(g).intersection(reserve).area,1e-8)
        header=sh.geometry.shape(group['portalHeaders']['bandGeometry'])
        self.assertLess(sh.LineString([(10,0),(10,4)]).difference(sh.union_all([header,sh.geometry.shape(group['bandGeometry'])]).buffer(.0001)).length,.001)
        self.assertEqual(group['guardAboveLandM'],1)
        self.assertGreater(group['portalHeaders']['minPassageHeightM'],2)

class PrecisionRingChecks(unittest.TestCase):
    def test_attached_numerical_tail_removed_without_inflating_real_outline(self):
        island=sh.box(0,0,.02,1)
        tail=sh.box(.019,.5,5,.50002)
        original=sh.union_all([island,tail])
        for transform in (lambda g:g,lambda g:translate(rotate(g,37,origin=(0,0)),3000,8000)):
            p=sh.set_precision(transform(original),1e-5)
            cleaned=stable_area(p,1e-5)
            self.assertFalse(cleaned.intersects(transform(sh.Point(2,.50001))))
            self.assertLess(cleaned.symmetric_difference(transform(island)).area,2e-5)
            self.assertLess(cleaned.difference(p).area,1e-9)

    def test_real_closed_curb_ring_survives_width_probe(self):
        import json
        from pathlib import Path
        from shapely.affinity import rotate,translate
        original=sh.geometry.shape(json.loads((Path(__file__).parent/'fixtures/curb-ring-precision.json').read_text()))
        for p in (original,translate(original,xoff=-3300,yoff=-5500),rotate(original,37)):
            p=sh.set_precision(p,1e-5)
            cleaned=stable_area(p,1e-5)
            self.assertGreater(cleaned.area,21)
            self.assertLess(cleaned.symmetric_difference(p).area,1e-8)
        tiny=sh.set_precision(sh.box(0,0,50,.00002),1e-5)
        self.assertTrue(stable_area(tiny,1e-5).is_empty)

if __name__=='__main__':unittest.main()
