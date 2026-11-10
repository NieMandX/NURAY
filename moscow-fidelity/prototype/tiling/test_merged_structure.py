import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import numpy as np
from merged_asset import read_container, write_container
from test_merged_glb import validate


class MergedStructureTests(unittest.TestCase):
    def fixture(self, folder, external):
        words=np.zeros((3,8),dtype='<u4')
        words.view('<f4')[:,:3]=[[0,0,0],[1,0,0],[0,0,1]]
        indices=np.array([0,1,2],dtype='<u4')
        normals=np.tile(np.array([0,1,0],dtype='<f4'),(3,1))
        vertices=words.tobytes();ix=indices.tobytes();raw=vertices+ix+normals.tobytes()
        draw=dict(vertexView=0,indexView=1,triangles=1,vertexCount=3)
        doc=dict(asset={'version':'2.0'},buffers=[{'byteLength':len(raw)}],
                 bufferViews=[dict(byteOffset=0,byteLength=len(vertices)),
                              dict(byteOffset=len(vertices),byteLength=len(ix)),
                              dict(byteOffset=len(vertices)+len(ix),byteLength=normals.nbytes)],
                 accessors=[dict(bufferView=0,count=3),dict(bufferView=2,count=3),
                            dict(bufferView=0,count=3,byteOffset=16),
                            dict(bufferView=1,count=3,byteOffset=0)],
                 meshes=[{'primitives':[dict(attributes={'POSITION':0,'NORMAL':1,'TEXCOORD_0':2},indices=3,material=0)]}],
                 materials=[{}],nodes=[{'mesh':0}],images=[],
                 extras={'nuray':{'draws':[draw],'nodes':1}})
        proof=dict(passed=True,objects=1,batches=[{'packedSha256':hashlib.sha256(vertices+ix).hexdigest()}])
        folder.mkdir();binary=folder/'model.bin.tmp';binary.write_bytes(raw)
        (folder/'validation.json').write_text(json.dumps(proof))
        asset=write_container(folder,copy.deepcopy(doc),binary,glb_limit=100 if external else 2**32)
        return folder/asset['file']

    def test_both_containers_pass_same_geometry_audit(self):
        with tempfile.TemporaryDirectory() as d:
            for external in [False,True]:
                path=self.fixture(Path(d)/str(external),external)
                self.assertTrue(validate(path)['passed'])

    def test_payload_corruption_is_rejected_in_both_containers(self):
        with tempfile.TemporaryDirectory() as d:
            for external in [False,True]:
                path=self.fixture(Path(d)/str(external),external)
                _,binary,offset,_,_=read_container(path)
                with binary.open('r+b') as f:
                    f.seek(offset);f.write(b'\x01')
                with self.assertRaises(AssertionError):validate(path)

    def test_missing_batch_proof_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            path=self.fixture(Path(d)/'scene',True)
            proof=path.parent/'validation.json';doc=json.loads(proof.read_text());doc['batches']=[];proof.write_text(json.dumps(doc))
            with self.assertRaises(AssertionError):validate(path)

    def test_invalid_external_attribute_count_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            path=self.fixture(Path(d)/'scene',True)
            doc=json.loads(path.read_text());doc['accessors'][1]['count']=4;path.write_text(json.dumps(doc))
            with self.assertRaises(AssertionError):validate(path)


if __name__=='__main__':unittest.main()
