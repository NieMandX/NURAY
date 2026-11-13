import unittest
import numpy as np
import shapely as sh
from survey_plants import plan,variation


class Identity:
    def transform(self,x,y):return x,y


def point(handle,x,y,family='tree-deciduous'):
    return dict(handle=handle,point=[x,y,9999],family=family,layer='Деревья_лиственные',scale=[100]*3,rotation=99)


def run(rows,existing=(),masks=None,buildings=()):
    return plan(dict(points=rows),Identity(),np.array(existing),masks or {},
                {'open':[2,8],'spruce':[2,8],'bush':[2,1]},buildings,
                sh.box(-100,-100,100,100),lambda x,y:7.5,160.)


class SurveyPlantTests(unittest.TestCase):
    def test_source_anchor_height_and_deterministic_scale(self):
        a=run([point(1,20,30)])[0]
        self.assertEqual(a['status'],'accepted')
        m=np.array(a['matrix']).reshape(3,4)
        np.testing.assert_array_equal(m[:,3],[20,7.5,-30])
        scale=variation(a['id'],'open')[1]
        np.testing.assert_allclose(m[:,:3].T@m[:,:3],np.eye(3)*scale**2,atol=1e-12)
        self.assertLess(scale,1)
        self.assertEqual(a,run([point(1,20,30)])[0])

    def test_unknown_duplicates_and_existing_do_not_create_extra_trees(self):
        rows=[point(1,0,0),point(2,0,0),point(3,20,0,'tree-conifer'),point(4,40,0)]
        a=run(rows,existing=[[41,0]])
        self.assertEqual([r['status'] for r in a],['accepted','deferred','deferred','deferred'])
        self.assertEqual(a,run(list(reversed(rows)),existing=[[41,0]]))

    def test_roots_canopies_and_green_domain(self):
        a=run([point(1,0,0),point(2,20,0),point(3,40,0),point(4,110,0)],
              masks={'road':sh.box(-1,-1,1,1)},buildings=[(sh.box(20.5,-1,21.5,1),190)])
        self.assertIn('road',a[0]['conflicts'])
        self.assertIn('buildingCanopy',a[1]['conflicts'])
        self.assertEqual(a[2]['status'],'accepted')
        self.assertEqual(a[3]['reason'],'outside-confirmed-green-surface')


if __name__=='__main__':unittest.main()
