import unittest
from railway_surfaces import confirmed_owners

def slab(name,x0,x1,y0=0,y1=100,z=5,tier=1):
    return dict(id=name,layer='Transport_Roadbed',geometryType='polygon',
        properties=dict(db_tiers=[tier],db_road_part='roadbed_overpass'),
        coordinates=[[x0,y0,z],[x1,y0,z],[x0,y1,z],[x1,y1,z]])

def rail(x=2,y0=0,y1=100,tier=1):
    return dict(id='rail',layer='Railroad_line',geometryType='polyline',
                properties=dict(db_tiers=[tier]),coordinates=[[x,y0,0],[x,y1,0]])

class ContinuousRailSlabTests(unittest.TestCase):
    def owners(self,*features):return {r['source'] for r in confirmed_owners(list(features))}
    def test_longitudinal_shoulder_without_axis(self):
        self.assertEqual(self.owners(slab('bed',0,4),slab('shoulder',-2,0),rail()),{'bed','shoulder'})
    def test_different_height_does_not_propagate(self):
        self.assertEqual(self.owners(slab('bed',0,4),slab('upper',-2,0,z=10),rail()),{'bed'})
    def test_different_tier_does_not_propagate(self):
        self.assertEqual(self.owners(slab('bed',0,4),slab('other',-2,0,tier=2),rail()),{'bed'})
    def test_nearby_but_detached_is_not_rail(self):
        self.assertEqual(self.owners(slab('bed',0,4),slab('near',-2,-.02),rail()),{'bed'})
    def test_transverse_crossing_is_not_rail(self):
        self.assertEqual(self.owners(slab('crossing',-50,50,y0=45,y1=49),rail()),set())
    def test_ramp_continuity(self):
        a=slab('bed',0,4);b=slab('ramp',0,4,100,130)
        for v in b['coordinates']:
            if v[1]==130:v[2]=0
        self.assertEqual(self.owners(a,b,rail()),{'bed','ramp'})

if __name__=='__main__':unittest.main()
