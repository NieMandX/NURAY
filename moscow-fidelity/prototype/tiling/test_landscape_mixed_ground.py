"""Restored paving in a grass batch must survive lawn refinement exactly."""
import gzip,tempfile,unittest
from pathlib import Path
import numpy as np
from object_geometry import pack
from prepare_landscape import lawn_remainder,append_unchanged_ground
from landscape_validation import verify_preserved_non_lawn


def triangles(path,meta):
    data=gzip.decompress(path.read_bytes());u=np.frombuffer(data[:meta['vertexBytes']],'<u4').reshape(-1,8)
    ix=np.frombuffer(data[meta['vertexBytes']:],'<u4').reshape(-1,3)
    return u[ix]


class MixedGround(unittest.TestCase):
    def test_rebuild_grass_preserves_other_materials_uv_normals_and_tint(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'mesh.bin.gz'
            attrs=np.zeros((3,3,8),dtype='<f4')
            for i in range(3):
                attrs[i,:,:3]=[[i*2,0,0],[i*2+1,0,0],[i*2,0,1]]
                attrs[i,:,3:6]=[.1,.99,.02]
                attrs[i,:,6:8]=[[12.125,-3.75],[12.75,-3.75],[12.125,-3.25]]
            old=pack(attrs,[2,7,30],path,tints=np.arange(9,dtype='f4')*.01+1)
            before=gzip.decompress(path.read_bytes())
            old_triangles=triangles(path,old)
            remainder=lawn_remainder(gzip.decompress(path.read_bytes()),old['vertexBytes'])
            self.assertEqual(remainder.tobytes(),old_triangles[1:].tobytes())
            attrs[:1,:,1]=.1
            new=pack(attrs[:1],[2],path)
            expected_grass=triangles(path,new).copy()
            append_unchanged_ground(path,new,remainder)
            actual=triangles(path,new)
            self.assertEqual(new['triangles'],3)
            self.assertEqual(actual[:1].tobytes(),expected_grass.tobytes())
            self.assertEqual(actual[1:].tobytes(),old_triangles[1:].tobytes())
            self.assertEqual(new['bounds']['max'],[5.,float(np.float32(.1)),1.])
            after=gzip.decompress(path.read_bytes())
            self.assertEqual(verify_preserved_non_lawn(before,old['vertexBytes'],after,new['vertexBytes'],{2}),2)
            corrupted=bytearray(after)
            u=np.frombuffer(corrupted[:new['vertexBytes']],'<u4').reshape(-1,8).copy()
            i=np.flatnonzero((u[:,6]&0x7fffffff)==7)[0];u[i,4]^=1
            corrupted[:new['vertexBytes']]=u.tobytes()
            with self.assertRaisesRegex(AssertionError,'non-lawn corners'):
                verify_preserved_non_lawn(before,old['vertexBytes'],bytes(corrupted),new['vertexBytes'],{2})
            with self.assertRaisesRegex(AssertionError,'non-lawn corners'):
                verify_preserved_non_lawn(before,old['vertexBytes'],after[:-12],new['vertexBytes'],{2})

    def test_pure_and_non_lawn_batches(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'mesh.bin.gz';attrs=np.zeros((1,3,8),dtype='<f4')
            attrs[0,:,:3]=[[0,0,0],[1,0,0],[0,0,1]];attrs[:,:,4]=1
            for material in (2,7):
                meta=pack(attrs,[material],path);data=gzip.decompress(path.read_bytes())
                remainder=lawn_remainder(data,meta['vertexBytes'])
                if material==7:self.assertIsNone(remainder)
                else:
                    self.assertEqual(len(remainder),0)
                    before=path.read_bytes();append_unchanged_ground(path,meta,remainder)
                    self.assertEqual(path.read_bytes(),before)


if __name__=='__main__':unittest.main()
