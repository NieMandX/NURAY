"""Information geometry must not become physical, even with overlapping bounds."""
import unittest
import copy,json
from pathlib import Path
import numpy as np
from physical_geometry import partition, filter_mesh, ranges, arrays, classify, verify_owner_bounds
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


class RaisedRoofOwnershipTest(unittest.TestCase):
    def setUp(self):
        self.row=dict(id='ordinary-house',category='building',bounds=dict(min=[0,0,0],max=[10,10,5]),
            placement=dict(shiftM=0),flatRoof=dict(raiseM=.6,depthM=.4,parapetHeightM=1.,
                patches=[dict(heightM=5.,raiseM=.6,bounds=[1,-9,9,-1])]))
        self.points=np.array([[[1,5.6,-1],[9,5.6,-1],[1,5.6,-9]]],dtype='<f4').astype(float)

    def test_recorded_parapet_is_part_of_its_owner(self):
        original=copy.deepcopy(self.row)
        verify_owner_bounds(self.points,self.row,np.zeros(3))
        self.assertEqual(self.row,original)

    def test_extension_requires_roof_provenance(self):
        del self.row['flatRoof']
        with self.assertRaisesRegex(AssertionError,'ownership upper bound'):
            verify_owner_bounds(self.points,self.row,np.zeros(3))

    def test_raised_area_is_not_a_blanket_height_allowance(self):
        points=self.points.copy();points[0,0,0]=.5 # within the house, outside its modified roof patch
        with self.assertRaisesRegex(AssertionError,'ownership upper bound'):
            verify_owner_bounds(points,self.row,np.zeros(3))

    def test_too_high_sideways_or_lowered_geometry_still_fails(self):
        for axis,value in ((1,5.62),(0,10.02),(1,-.02)):
            with self.subTest(axis=axis,value=value):
                points=self.points.copy();points[0,0,axis]=value
                with self.assertRaises(AssertionError):verify_owner_bounds(points,self.row,np.zeros(3))

    def test_patch_cannot_claim_an_unrelated_upper_storey(self):
        self.row['flatRoof']['patches'][0]['heightM']=9.
        with self.assertRaisesRegex(AssertionError,'roof outside source height'):
            verify_owner_bounds(self.points,self.row,np.zeros(3))

    def test_source_buildings_without_edits_keep_original_bounds(self):
        points=self.points.copy();points[:,:,1]=5.
        del self.row['flatRoof']
        verify_owner_bounds(points,self.row,np.zeros(3))

    def test_actual_processed_roof_and_rigid_coordinate_translation(self):
        folder=Path(__file__).with_name('fixtures')
        data=json.loads((folder/'raised-roof-ownership.json').read_text())
        points=np.load(folder/'raised-roof-ownership.npz')['faces'].view('<f4')[:,:,:3].astype(float)
        original=copy.deepcopy(data['row'])
        verify_owner_bounds(points,data['row'],np.asarray(data['originMSK']))
        shift=np.array([12345.,-23456.,100.])
        data['originMSK']=(np.asarray(data['originMSK'])+shift).tolist()
        for k in ('min','max'):data['row']['bounds'][k]=(np.asarray(data['row']['bounds'][k])+shift).tolist()
        verify_owner_bounds(points,data['row'],np.asarray(data['originMSK']))
        self.assertEqual(original['flatRoof'],data['row']['flatRoof'])

if __name__=='__main__':unittest.main()
