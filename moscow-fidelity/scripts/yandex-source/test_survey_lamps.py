import unittest
import numpy as np
import shapely as sh
from survey_lamps import plan

class Identity:
    def transform(self,x,y): return x,y
class Ground:
    def ground(self,x,z):
        return None if x>50 else dict(height=10+x*.01,chunk=0,triangle=0)

def point(i,x,y,family='lamp-single',layer='Фонари_электрические_на_жб_стбп'):
    return dict(handle=i,point=[x,y,9999],family=family,layer=layer,rotation=0,scale=[100,100,100])

class SurveyLamps(unittest.TestCase):
    def run_plan(self,points):
        return plan(dict(points=points),Identity(),Ground(),
                    dict(building=sh.box(-2,-2,2,2),water=sh.box(20,20,25,25)),sh.box(-20,-10,20,-5))
    def test_source_xy_and_ground_height_override_symbol_values(self):
        r=self.run_plan([point(1,5,0)])[0]
        m=np.array(r['matrix']).reshape(3,4)
        np.testing.assert_allclose(m[:,3],[5,10.05,0])
        np.testing.assert_allclose(m[:,:3].T@m[:,:3],np.eye(3),atol=1e-12)
        np.testing.assert_allclose(m[:,2],[0,0,1],atol=1e-12)  # arm faces south road
        self.assertEqual(r['sourcePoint'][2],9999)
        self.assertEqual(r['model'],'lamppost-concrete1')
    def test_no_snapping_out_of_collisions_or_missing_ground(self):
        r=self.run_plan([point(1,0,0),point(2,22,22),point(3,5,-7),point(4,60,0)])
        self.assertEqual([v['reason'] for v in r],['building-clearance','water-clearance','inside-drivable-surface','no-containing-finished-ground'])
        self.assertTrue(all('matrix' not in v for v in r))
    def test_duplicate_conflicts_are_order_independent(self):
        points=[point(4,8,0),point(2,8.01,0),point(5,10,0),point(6,10.01,0,'lamp-double')]
        a=self.run_plan(points);b=self.run_plan(points[::-1]);self.assertEqual(a,b)
        self.assertEqual([r['status'] for r in a],['accepted','deferred','deferred','deferred'])
        self.assertEqual(a[1]['reason'],'duplicate-source-point')
        self.assertEqual(a[2]['reason'],'conflicting-duplicate-types')

if __name__=='__main__':unittest.main()
