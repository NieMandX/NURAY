import unittest
import numpy as np
import shapely as sh
from railway_support import Floors, floor_group


def source(id, tier):
    return dict(id=id, layer='Railroad_line', properties={'db_tiers': [tier]})


def cell(id, tier, height, bounds=(-10,-10,10,10), material=210):
    return dict(id=id, owner=id, kind='roadbed_overpass', tiers=[tier],
                geometry=sh.geometry.mapping(sh.box(*bounds)), material=material,
                heightPlane=[0,0,height])


class RailSupportTests(unittest.TestCase):
    def test_ground_water_crossing_uses_both_banks_not_water_or_foreign_deck(self):
        rail=dict(source('r',0),geometryType='polyline',coordinates=[[-10,0,0],[10,0,0]])
        left=dict(cell('left',0,2,(-20,-9,-6,9)),kind='land')
        right=dict(cell('right',0,6,(6,-9,20,9)),kind='land')
        water=dict(cell('water',0,-100,(-6,-9,6,9)),kind='water')
        floor=Floors(dict(boundsMSK=[-20,-9,20,9],features=[rail],surfaces=[left,right,water,cell('foreign',2,50)]))
        np.testing.assert_allclose(floor.sample([[-6,0],[0,0],[6,0]],'ground','r'),[2.02,4.02,6.02])
        self.assertEqual(floor.owners['r'],{'left','right'})
        self.assertEqual(len(floor.water_profiles['r']),1)
        self.assertAlmostEqual(floor.water_profiles['r'][0]['lengthM'],12)
        self.assertEqual(floor.water_samples,1)

    def test_missing_ground_is_not_assumed_to_be_a_water_crossing(self):
        rail=dict(source('r',0),geometryType='polyline',coordinates=[[-10,0,0],[10,0,0]])
        rows=[dict(cell('left',0,2,(-20,-9,-6,9)),kind='land'),dict(cell('right',0,6,(6,-9,20,9)),kind='land')]
        floor=Floors(dict(boundsMSK=[-20,-9,20,9],features=[rail],surfaces=rows))
        with self.assertRaisesRegex(ValueError,'No confirmed'):floor.sample([[0,0]],'ground','r')
        # A line ending in the water has no confirmed opposite bank.
        rail['coordinates']=[[-10,0,0],[0,0,0]]
        rows.append(dict(cell('water',0,-100,(-6,-9,6,9)),kind='water'))
        floor=Floors(dict(boundsMSK=[-20,-9,20,9],features=[rail],surfaces=rows))
        with self.assertRaisesRegex(ValueError,'No confirmed'):floor.sample([[0,0]],'ground','r')

    def test_inferred_ribbon_must_remain_above_water(self):
        from railway_layer import generate
        rail=dict(source('r',0),geometryType='polyline',coordinates=[[-10,0,0],[10,0,0]])
        rows=[dict(cell('left',0,2,(-20,-9,-6,9)),kind='land'),
              dict(cell('right',0,2,(6,-9,20,9)),kind='land'),
              dict(cell('water',0,10,(-6,-9,6,9)),kind='water')]
        with self.assertRaisesRegex(ValueError,'intersects source water'):
            generate(dict(boundsMSK=[-20,-9,20,9],originMSK=[0,0,0],features=[rail],surfaces=rows),dict(bed=0,rail=1))

    def test_every_positive_tier_is_elevated(self):
        for tier in (1,2,3,9):self.assertEqual(floor_group(source('r',tier)), 'elevated')
        self.assertEqual(floor_group(source('r',0)), 'ground')
        self.assertEqual(floor_group(source('r',-2)), 'below')

    def test_stacked_crossing_stays_on_each_source_tier_after_restyle(self):
        rails=[source('lower',1),source('upper',3)]
        rows=[cell('upper-deck',3,15),cell('lower-deck',1,6)]
        for order in (rows,rows[::-1]):
            floor=Floors(dict(boundsMSK=[-9,-9,9,9],surfaces=order,features=rails))
            np.testing.assert_allclose(floor.sample([[-2,0],[0,0],[2,0]],'elevated','lower'),6.12)
            np.testing.assert_allclose(floor.sample([[-2,0],[0,0],[2,0]],'elevated','upper'),15.12)

    def test_nearest_edge_does_not_pick_a_covering_foreign_tier(self):
        floor=Floors(dict(boundsMSK=[-9,-9,9,9],features=[source('r',2)],
             surfaces=[cell('same',2,7,bounds=(-2,-2,2,2)),cell('foreign',1,20)]))
        np.testing.assert_allclose(floor.sample([[2.1,0]],'elevated','r'),7.12)
        self.assertEqual(floor.owners['r'],{'same'})

    def test_initial_unstyled_transport_and_restyled_rail_are_equivalent(self):
        for material,purpose in ((12,'transport-unspecified'),(210,'railway')):
            row=cell('slab',2,8,material=material);row['purpose']=purpose
            road=cell('road',2,20,material=0);road['purpose']='motor-traffic'
            floor=Floors(dict(boundsMSK=[-9,-9,9,9],features=[source('r',2)],surfaces=[row,road]))
            np.testing.assert_allclose(floor.sample([[0,0]],'elevated','r'),8.12)

    def test_missing_or_ambiguous_sheet_is_not_silently_projected(self):
        base=dict(boundsMSK=[-9,-9,9,9],features=[source('r',2)])
        floor=Floors(dict(base,surfaces=[cell('other',1,4)]))
        with self.assertRaisesRegex(ValueError,'source-tier'):floor.sample([[0,0]],'elevated','r')
        floor=Floors(dict(base,surfaces=[cell('a',2,4),cell('b',2,12)]))
        with self.assertRaisesRegex(ValueError,'Ambiguous'):floor.sample([[0,0]],'elevated','r')

    def test_ramp_uses_floor_plane_not_numeric_tier_as_height(self):
        row=cell('ramp',3,0);row['heightPlane']=[.05,0,4]
        floor=Floors(dict(boundsMSK=[-9,-9,9,9],features=[source('r',3)],surfaces=[row]))
        np.testing.assert_allclose(floor.sample([[-2,0],[2,0]],'elevated','r'),[4.02,4.22])

    def test_complete_ribbons_cross_without_vertical_spikes(self):
        from railway_layer import generate
        lower=dict(source('lower',1),geometryType='polyline',coordinates=[[-5,0,0],[5,0,0]])
        upper=dict(source('upper',3),geometryType='polyline',coordinates=[[0,-5,0],[0,5,0]])
        city=dict(boundsMSK=[-9,-9,9,9],originMSK=[0,0,0],features=[lower,upper],
                  surfaces=[cell('upper-slab',3,15),cell('lower-slab',1,6)])
        chunks,meta=generate(city,dict(bed=193,rail=194))
        self.assertEqual(meta['stats']['components'],2)
        for id,triangles,materials in chunks:
            np.testing.assert_allclose(triangles[:,:,1],15.12 if id=='upper' else 6.12)
            self.assertEqual(set(materials),{193,194})

    def test_drawing_tier_change_on_continuous_ramp_has_welded_cross_section(self):
        from railway_layer import generate
        a=dict(source('a',3),geometryType='polyline',coordinates=[[-5,0,0],[0,0,0]])
        b=dict(source('b',2),geometryType='polyline',coordinates=[[0,0,0],[5,0,0]])
        left=cell('left',3,6,(-9,-9,0,9));right=cell('right',2,6,(0,-9,9,9))
        left['heightPlane']=right['heightPlane']=[.05,0,6]
        _,meta=generate(dict(boundsMSK=[-9,-9,9,9],originMSK=[0,0,0],features=[a,b],surfaces=[left,right]),dict(bed=193,rail=194))
        self.assertEqual(meta['stats']['continuousSourceJoints'],1)
        self.assertLess(meta['stats']['maxSourceJointGapM'],1e-10)
        self.assertLess(meta['stats']['maxSourceJointPhaseError'],1e-10)


if __name__=='__main__':unittest.main()
