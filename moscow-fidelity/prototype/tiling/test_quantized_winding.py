import gzip,tempfile,unittest
from pathlib import Path
import numpy as np
from object_geometry import pack
from prepare_fence_types import verify_mesh
from quantized_winding import repair_faces,repair_packed


class QuantizedWindingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture=np.load(Path(__file__).with_name('fixtures')/'fence-quantized-winding.npz')
        cls.originals=fixture['triangles'];cls.packed=fixture['packedCorners']

    def test_actual_profiles_are_fixed_without_changing_any_vertex_attribute(self):
        for original,corners in zip(self.originals,self.packed):
            words=corners.copy();ix=np.array([[0,1,2]],dtype='<u4');before=words.copy()
            self.assertEqual(repair_packed(words,ix,original[None]),1)
            np.testing.assert_array_equal(words,before)
            np.testing.assert_array_equal(ix,[[0,2,1]])
            self.assertEqual(repair_packed(words,ix,original[None]),0)
            raw=words.tobytes()+ix.tobytes()
            verify_mesh(raw,{'vertexBytes':words.nbytes},[int(words[0,6]&0x7fffffff)])

    def test_fresh_pack_has_same_positions_uv_normals_and_face_count(self):
        with tempfile.TemporaryDirectory() as d:
            for i,(original,corners) in enumerate(zip(self.originals,self.packed)):
                path=Path(d)/str(i);material=int(corners[0,6]&0x7fffffff)
                meta=pack(original[None],np.array([material]),path)
                self.assertEqual(meta['triangles'],1);self.assertEqual(meta['quantizedWindingRepairs'],1)
                raw=gzip.decompress(path.read_bytes())
                w=np.frombuffer(raw,'<u4',count=meta['vertexBytes']//4).reshape(-1,8)
                ix=np.frombuffer(raw,'<u4',offset=meta['vertexBytes']).reshape(-1,3)
                np.testing.assert_array_equal(w[ix][0],corners[[0,2,1]])
                verify_mesh(raw,meta,[material])

    def test_bad_source_normals_are_not_disguised_as_rounding(self):
        original=self.originals[:1].copy();original[:,:,3:6]*=-1
        with self.assertRaisesRegex(AssertionError,'before quantization'):
            repair_faces(self.packed[0].copy(),np.array([[0,1,2]],dtype='<u4'),[0],original)

    def test_changed_source_positions_are_rejected(self):
        original=self.originals[:1].copy();original[:,:,0]+=1
        with self.assertRaisesRegex(AssertionError,'rounded source'):
            repair_faces(self.packed[0].copy(),np.array([[0,1,2]],dtype='<u4'),[0],original)

    def test_invalid_source_is_left_for_the_normal_audit_to_reject(self):
        original=self.originals[:1].copy();original[:,:,3:6]*=-1
        words=self.packed[0].copy();ix=np.array([[0,1,2]],dtype='<u4')
        self.assertEqual(repair_packed(words,ix,original),0)
        np.testing.assert_array_equal(ix,[[0,1,2]])
        with self.assertRaises(AssertionError):
            verify_mesh(words.tobytes()+ix.tobytes(),{'vertexBytes':words.nbytes},[int(words[0,6]&0x7fffffff)])

    def test_ordinary_faces_keep_their_original_order(self):
        words=np.zeros((3,8),dtype='<u4');words.view('<f4')[:,:3]=[[0,0,0],[1,0,0],[0,0,1]]
        # Octahedral -Y normal, consistent with this triangle's winding.
        words[:,3]=np.array([0,-32767],dtype='<i2').view('<u4')[0]
        ix=np.array([[0,1,2]],dtype='<u4');before=ix.copy()
        self.assertEqual(repair_packed(words,ix,np.zeros((1,3,8))),0)
        np.testing.assert_array_equal(ix,before)


if __name__=='__main__':unittest.main()
