"""Information geometry must not become physical, even with overlapping bounds."""
import unittest
import numpy as np
from physical_geometry import partition, filter_mesh, ranges, arrays, classify
from source_objects import source_class

class PhysicalGeometryTest(unittest.TestCase):
    def row(self,layer,identity='123'):
        return dict(id=layer+identity,sourceLayer=layer+'_'+identity,sourceBuildingId=identity,category='building')

    def test_information_is_not_a_house(self):
        for identity in ('1','999999','elsewhere'):
            real=self.row('Technical_house',identity);info=self.row('Metro_station_house',identity)
            self.assertEqual(partition([info,real]),([real],[info]))
            self.assertEqual(source_class(info),'Metro_station_house')
        for geometry in ('polygon','polyline','point'):
            self.assertEqual(classify('Metro_station_house',{'db_road_part':'roadbed_flat'},geometry)['status'],'non-rendering')

    def test_unknown_does_not_guess_physical(self):
        with self.assertRaises(ValueError):partition([self.row('Unreviewed_house')])
        self.assertNotEqual(classify('Unreviewed_house',{},'polygon')['purpose'],'building')

    def test_real_structures_and_detailed_station_stay(self):
        rows=[self.row(x) for x in ['Underground_house','Underpass_entrance','Canopy','Dwelling_house_roof']]
        rows.append(dict(id='station-glb',category='landmark',sourceFile='station.glb'))
        self.assertEqual(partition(rows),(rows,[]))

    def test_overlapping_geometry_only_removes_information_owner(self):
        words=np.zeros((12,8),dtype='<u4');f=words.view('<f4')
        f[:,:3]=np.tile([[0,0,0],[1,0,0],[0,0,1]],(4,1))
        # Distinct normals, UVs, material and curvature despite identical positions.
        words[:,3]=np.arange(12)+100;f[:,4:6]=np.arange(24).reshape(-1,2)/24
        words[:,6]=0x80000007;f[:,7]=np.linspace(.7,1.1,12)
        ix=np.arange(12,dtype='<u4').reshape(-1,3);raw=words.tobytes()+ix.tobytes()
        chunk=dict(id=2,vertexBytes=words.nbytes,vertexCount=12,triangles=4)
        owners=['a','info','info','b'];filtered,meta=filter_mesh(raw,chunk,owners,{'info'})
        v,i=arrays(filtered,meta)
        np.testing.assert_array_equal(v[i],words[ix[[0,3]]])
        self.assertEqual(meta['sourceObjectRanges'],[dict(id='a',first=0,count=1),dict(id='b',first=1,count=1)])
        self.assertEqual(meta['vertexCount'],6)
        self.assertEqual(filter_mesh(raw,chunk,owners,set()),(raw,chunk))
        with self.assertRaises(ValueError):filter_mesh(raw,chunk,owners,set(owners))

    def test_ranges_preserve_split_owners(self):
        self.assertEqual(ranges(['a','a','b','a']),[dict(id='a',first=0,count=2),dict(id='b',first=2,count=1),dict(id='a',first=3,count=1)])

if __name__=='__main__':unittest.main()
