"""The bounded audit still rejects corrupted materials and face orientations."""
import gzip
import tempfile
import unittest
from pathlib import Path
import numpy as np
from fence_geometry import profile, TYPES, DEFAULT
from object_geometry import pack, decode_normals
from prepare_fence_types import verify_mesh
from street_library import Mesh


def original_audit(raw, chunk, materials):
    words=np.frombuffer(raw[:chunk['vertexBytes']],'<u4').reshape(-1,8)
    ix=np.frombuffer(raw[chunk['vertexBytes']:],'<u4').reshape(-1,3)
    assert np.isin(words[:,6]&0x7fffffff,materials).all()
    p=words.view('<f4')[ix,:3].astype(float)
    n=np.cross(p[:,1]-p[:,0],p[:,2]-p[:,0])
    valid=np.linalg.norm(n,axis=1)>1e-9
    assert np.all(np.sum(n[valid]*decode_normals(words[:,3])[ix[valid,0]],axis=1)>0)


class FenceMeshAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        mesh=Mesh()
        for i,spec in enumerate([*TYPES.values(),DEFAULT]):
            profile(mesh,[i*5,0],[i*5+3,1],.1,.7,
                    dict(heightM=spec[3],material=spec[5],family=spec[2]))
        t,m=mesh.arrays()
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'fences.gz';cls.chunk=pack(t,m,p);cls.raw=gzip.decompress(p.read_bytes())
        cls.materials=list(range(11))

    def compare(self, raw, expected):
        for batch in [1,7,37,250_000]:
            with self.subTest(batch=batch):
                if expected:
                    verify_mesh(raw,self.chunk,self.materials,batch_size=batch)
                else:
                    with self.assertRaises(AssertionError):
                        verify_mesh(raw,self.chunk,self.materials,batch_size=batch)
        if expected:original_audit(raw,self.chunk,self.materials)
        else:
            with self.assertRaises(AssertionError):original_audit(raw,self.chunk,self.materials)

    def test_all_types_and_slopes_match_original(self):
        self.compare(self.raw,True)

    def test_last_face_reversed_is_rejected(self):
        raw=bytearray(self.raw)
        ix=np.frombuffer(raw,'<u4',offset=self.chunk['vertexBytes']).reshape(-1,3)
        ix[-1]=ix[-1,::-1]
        self.compare(raw,False)

    def test_unreferenced_vertex_with_invalid_material_is_rejected(self):
        raw=bytearray(self.raw)
        words=np.frombuffer(raw,'<u4',count=self.chunk['vertexBytes']//4).reshape(-1,8)
        ix=np.frombuffer(raw,'<u4',offset=self.chunk['vertexBytes']).reshape(-1,3)
        # Even unused vertices were checked by the previous validator.
        ix[ix==len(words)-1]=0
        words[-1,6]=0x80000000|999
        self.compare(raw,False)

    def test_degenerate_face_policy_is_unchanged(self):
        raw=bytearray(self.raw)
        ix=np.frombuffer(raw,'<u4',offset=self.chunk['vertexBytes']).reshape(-1,3)
        ix[-1]=ix[-1,0]
        self.compare(raw,True)

    def test_empty_mesh_is_accepted_as_before(self):
        chunk=dict(vertexBytes=0)
        original_audit(b'',chunk,[])
        verify_mesh(b'',chunk,[])


if __name__=='__main__':unittest.main()
