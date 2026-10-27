"""Attribute and serialized-floor regressions, independent of the city fixture."""
import sys,tempfile,unittest,json
from pathlib import Path
import numpy as np
import shapely as sh
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from object_geometry import pack,decode_normals
from prepare_road_paint import read,interpolate,world,audit,write,serialization_xy_tolerance,clip
from paint_domain import Domain,HEIGHT_TOLERANCE

class SerializationTests(unittest.TestCase):
    def test_batch_shortcut_preserves_exact_faces_and_diagnostics(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);folder=root/'canonical/full';folder.mkdir(parents=True)
            chunks=[]
            roads=np.array([[[0,0,0],[4,0,0],[0,4,0]],
                            [[4,0,0],[4,4,0],[0,4,0]],
                            [[0,0,5],[4,0,5],[0,4,5]]],float)
            paint=np.array([[[0,0,.003],[1,0,.003],[0,1,.003]],
                            [[3,1,.003],[5,1,.003],[3,2,.003]],
                            [[0,0,5.003],[1,0,5.003],[0,1,5.003]],
                            [[0,0,2],[1,0,2],[0,1,2]]],float)
            for name,mat,faces in [('roadbed_flat',0,roads),('paint',3,paint)]:
                local=faces[:,:,[0,2,1]]*[1,1,-1]
                attrs=np.concatenate([local,np.broadcast_to([0,1,0],local.shape),local[:,:,[0,2]]],axis=2)
                file=name+'.gz'
                chunks.append(dict(pack(attrs,[mat]*len(faces),folder/file),file=file,name=name,id=len(chunks)))
            scene=dict(chunks=chunks,instances=[dict(mesh=1,matrix=[1,0,0,0,0,1,0,0,0,0,1,0])])
            city=dict(originMSK=[0,0,0],surfaces=[])
            fast,fast_stats=clip(root,city,scene);fast_audit=audit(root,city,scene)
            with patch.object(Domain,'fully_supported',lambda self,xyz,tolerance=.002:np.zeros(len(xyz),bool)):
                slow,slow_stats=clip(root,city,scene);slow_audit=audit(root,city,scene)
            np.testing.assert_array_equal(fast,slow)
            self.assertEqual(fast_stats,slow_stats)
            self.assertEqual(fast_audit,slow_audit)

    def test_large_offset_rounding_against_actual_asphalt_witnesses(self):
        fixture=json.loads((Path(__file__).resolve().parents[1]/'test_fixtures/paint-float32-large-region.json').read_text())
        origin=np.array(fixture['origin']);roads=[];paint=[]
        for row in fixture['examples']:
            t=np.array(row['triangle']);paint.append(t)
            old=Domain([dict(poly=sh.geometry.shape(c['geometry']).buffer(.0001),plane=np.array(c['plane'])) for c in row['cells']])
            self.assertGreater(sh.Polygon(t[:,:2]).difference(old.supported(t,HEIGHT_TOLERANCE+.00001)).area,1e-7)
            for c in row['cells']:
                xy=np.array(c['geometry']['coordinates'][0])[:3]
                roads.append(np.column_stack([xy,np.column_stack([xy,np.ones(3)])@np.array(c['plane'])]))
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);folder=root/'canonical/full';folder.mkdir(parents=True);chunks=[]
            for name,material,faces in [('roadbed_flat',0,roads),('paint',3,paint)]:
                local=(np.array(faces)-origin)[:,:,[0,2,1]]*[1,1,-1]
                normals=np.broadcast_to([0,1,0],local.shape)
                attrs=np.concatenate([local,normals,local[:,:,[0,2]]],axis=2)
                file=name+'.gz';chunks.append(dict(pack(attrs,[material]*len(faces),folder/file),file=file,name=name,id=len(chunks)))
            report=audit(root,{'originMSK':origin.tolist()},{'chunks':chunks})
            self.assertTrue(report['passed'],report)
            self.assertLess(report['unsupportedAreaM2'],1e-10)
            self.assertGreater(report['xyToleranceM'],.0001)
            self.assertLess(report['xyToleranceM'],.00018)
            # A visible shift cannot be excused by the format tolerance.
            words=read(root,chunks[1]).copy();words.view('<f4')[:,:,0]+=.01
            chunks[1].update(write(folder/chunks[1]['file'],words))
            self.assertFalse(audit(root,{'originMSK':origin.tolist()},{'chunks':chunks})['passed'])

    def test_precision_limit_requires_rebasing(self):
        def scene(size):return {'chunks':[dict(name='paint',bounds=dict(min=[-size,0,-size],max=[size,1,size]))]}
        self.assertEqual(serialization_xy_tolerance(scene(100)),.0001)
        self.assertLess(serialization_xy_tolerance(scene(2500)),.00018)
        with self.assertRaises(AssertionError):serialization_xy_tolerance(scene(1e6))

    def test_clipping_interpolates_uv_preserves_material_and_height(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);folder=root/'canonical/full';folder.mkdir(parents=True)
            # Render coordinates X, height, south. UVs vary independently.
            xyz=np.array([[0,.003,0],[2,.003,0],[0,.003,-2]])
            attrs=np.column_stack([xyz,np.tile([0,1,0],(3,1)),[[10,10],[14,10],[10,18]]])
            c=dict(pack(attrs[None],[4],folder/'a.gz'),file='a.gz',name='paint')
            words=read(root,c)[0];xy=np.array([[0,0],[1,0],[0,1]])
            result=interpolate(words,xy,np.zeros(3))
            np.testing.assert_allclose(result.view('<f4')[:,4:6],[[10,10],[12,10],[10,14]])
            np.testing.assert_allclose(world(result[None],np.zeros(3))[0],np.column_stack([xy,np.full(3,.003)]),atol=1e-8)
            self.assertTrue(np.all(result[:,6]==words[0,6]))
            np.testing.assert_allclose(decode_normals(result[:,3]),[[0,1,0]]*3,atol=1e-5)

    def test_actual_serialized_support_rejects_sidewalk_and_wrong_level(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);folder=root/'canonical/full';folder.mkdir(parents=True);chunks=[]
            def mesh(name,mat,height):
                xyz=np.array([[0,height,0],[2,height,0],[0,height,-2]],float)
                attrs=np.column_stack([xyz,np.tile([0,1,0],(3,1)),xyz[:,[0,2]]]);file=f'{len(chunks)}.gz'
                c=dict(pack(attrs[None],[mat],folder/file),file=file,name=name,id=len(chunks));chunks.append(c)
                return c
            mesh('land',7,0);paint=mesh('paint',3,.003);city={'originMSK':[0,0,0]}
            self.assertFalse(audit(root,city,{'chunks':chunks})['passed'])
            road=mesh('roadbed_flat',0,0)
            self.assertTrue(audit(root,city,{'chunks':chunks})['passed'])
            words=read(root,paint).copy();words.view('<f4')[:,:,1]+=.1;paint.update(write(folder/paint['file'],words))
            self.assertFalse(audit(root,city,{'chunks':chunks})['passed'])
            # Cut vertices can round ~1.5 micrometres beyond the 2 mm binding
            # threshold. Only the explicit float32 margin is admitted.
            words.view('<f4')[:,:,1]=.0050015;paint.update(write(folder/paint['file'],words))
            self.assertTrue(audit(root,city,{'chunks':chunks})['passed'])
            words.view('<f4')[:,:,1]=.00502;paint.update(write(folder/paint['file'],words))
            self.assertFalse(audit(root,city,{'chunks':chunks})['passed'])

if __name__=='__main__':unittest.main()
