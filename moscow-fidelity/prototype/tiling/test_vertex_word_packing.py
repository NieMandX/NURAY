import gzip
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from object_geometry import pack, unique_vertex_words


class VertexWordPacking(unittest.TestCase):
    def assert_same(self, words):
        expected, old_inverse=np.unique(words,axis=0,return_inverse=True)
        actual, inverse=unique_vertex_words(words)
        self.assertEqual(actual.dtype,expected.dtype)
        self.assertEqual(actual.shape,expected.shape)
        self.assertEqual(actual.tobytes(),expected.tobytes())
        self.assertEqual(inverse.tobytes(),old_inverse.tobytes())
        np.testing.assert_array_equal(actual[inverse],words)

    def test_all_word_bits_duplicates_and_noncontiguous_input(self):
        rng=np.random.default_rng(20261108)
        words=rng.integers(0,2**32,size=(30000,8),dtype='<u4')
        words[:,6]=rng.integers(0,400,size=len(words),dtype='<u4')|0x80000000
        words[10000:20000]=words[:10000]
        self.assert_same(words)
        self.assert_same(words[::3])
        self.assert_same(np.empty((0,8),dtype='<u4'))

    def test_numeric_order_is_not_little_endian_byte_order(self):
        bits=[0,1,255,256,65535,65536,0x7fffffff,0x80000000,0xffffffff]
        rows=[]
        for field in range(8):
            for bit in bits:
                row=[0]*8;row[field]=bit;rows.append(row)
        self.assert_same(np.array(rows[::-1],dtype='<u4'))

    def test_serialized_mesh_matches_previous_packer_exactly(self):
        rng=np.random.default_rng(91)
        triangles=rng.normal(size=(3000,3,8)).astype('<f4')
        triangles[1000:2000]=triangles[:1000]
        triangles[2000:2100,1]=triangles[2000:2100,0]
        triangles[0,0,:3]=[0.,-0.,3.]
        materials=rng.integers(0,400,size=len(triangles),dtype='<u4')
        materials[1000:2000]=materials[:1000]
        tints=rng.uniform(.3,1.2,size=len(triangles)*3).astype('<f4')
        with tempfile.TemporaryDirectory() as folder:
            old=Path(folder)/'old.gz';new=Path(folder)/'new.gz'
            for color in (None,tints):
                with patch('object_geometry.unique_vertex_words',side_effect=lambda a:np.unique(a,axis=0,return_inverse=True)):
                    before=pack(triangles,materials,old,color)
                after=pack(triangles,materials,new,color)
                self.assertEqual(before,after)
                self.assertEqual(gzip.decompress(old.read_bytes()),gzip.decompress(new.read_bytes()))


if __name__=='__main__':unittest.main()
