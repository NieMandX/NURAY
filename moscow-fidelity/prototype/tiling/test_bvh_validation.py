import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
from bvh_validation import validate,validate_cached


class BvhProofTest(unittest.TestCase):
    def setUp(self):
        self.points=np.array([[[0,0,0],[1,0,0],[0,1,0]],[[1,0,0],[2,0,0],[2,1,0]]],dtype=float)
        self.nf=np.zeros((3,8),dtype='<f4');self.nu=self.nf.view('<u4')
        self.nf[:,4:7]=[[2,1,0],[1,1,0],[2,1,0]]
        self.nf[2,:3]=[1,0,0]
        self.nu[:,3]=[3,0,1];self.nu[:,7]=[0,1,1]
        self.chunk=dict(format='test',vertexBytes=144,indexBytes=24,nodeBytes=96,lineageBytes=8,nodeCount=3,triangles=2)

    def digest(self):
        return hashlib.sha256(self.points.tobytes()+self.nf.tobytes()).hexdigest()

    def test_leaf_bounds_and_escape_structure(self):
        validate(self.points,self.nf,self.nu)
        self.nu[0,3]=2
        with self.assertRaises(AssertionError):validate(self.points,self.nf,self.nu)

    def test_exact_hit_and_changed_geometry(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertFalse(validate_cached(folder,self.chunk,self.digest(),self.points,self.nf,self.nu))
            with patch('bvh_validation.validate',side_effect=RuntimeError('unexpected recomputation')):
                self.assertTrue(validate_cached(folder,self.chunk,self.digest(),self.points,self.nf,self.nu))
            self.points[0,0,0]=-1
            with self.assertRaises(AssertionError):validate_cached(folder,self.chunk,self.digest(),self.points,self.nf,self.nu)

    def test_changed_layout_requires_new_proof(self):
        with tempfile.TemporaryDirectory() as folder:
            validate_cached(folder,self.chunk,self.digest(),self.points,self.nf,self.nu)
            self.chunk['format']='different-layout'
            with patch('bvh_validation.validate',side_effect=RuntimeError('rechecked')):
                with self.assertRaisesRegex(RuntimeError,'rechecked'):
                    validate_cached(folder,self.chunk,self.digest(),self.points,self.nf,self.nu)

    def test_corrupt_proof_rechecks(self):
        with tempfile.TemporaryDirectory() as folder:
            validate_cached(folder,self.chunk,self.digest(),self.points,self.nf,self.nu)
            next(Path(folder).rglob('*.json')).write_text('invalid')
            self.assertFalse(validate_cached(folder,self.chunk,self.digest(),self.points,self.nf,self.nu))

    def test_changed_validator_requires_new_proof(self):
        with tempfile.TemporaryDirectory() as folder:
            validate_cached(folder,self.chunk,self.digest(),self.points,self.nf,self.nu)
            with patch('bvh_validation.RECIPE','new-validator'):
                self.assertFalse(validate_cached(folder,self.chunk,self.digest(),self.points,self.nf,self.nu))

    def test_duplicate_leaf_ownership_rejected(self):
        self.nu[2,3]=0
        self.nf[2,:3]=[0,0,0]  # Both leaves now contain triangle zero geometrically.
        with self.assertRaises(AssertionError):validate(self.points,self.nf,self.nu)


if __name__=='__main__':unittest.main()
