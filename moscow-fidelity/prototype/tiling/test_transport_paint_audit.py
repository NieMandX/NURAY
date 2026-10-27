import unittest,tempfile,copy
from pathlib import Path
from unittest.mock import patch
import numpy as np
from prepare_transport_surfaces import incremental_paint_audit
from prepare_road_paint import write
from test_transport_ground import words

class IncrementalPaintAuditTests(unittest.TestCase):
    def check(self,change):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp)/'base';out=Path(tmp)/'out'
            for root in (base,out):(root/'canonical/full').mkdir(parents=True)
            paint=words([[0,0,.003],[1,0,.003],[0,1,.003]]);paint[:,:,6]=0x80000003
            asphalt=words([[0,0,0],[1,0,0],[0,1,0]]);asphalt[:,:,6]=0x80000000
            rail=words([[2,0,0],[3,0,0],[2,1,0]]);rail[:,:,6]=0x8000000c
            meshes=[paint,np.concatenate([asphalt,rail])];old={'chunks':[]};scene={'chunks':[]}
            for i,(name,data) in enumerate(zip(['paint','roadbed_overpass'],meshes)):
                file=f'mesh-{i}.bin.gz';meta=write(base/'canonical/full'/file,data)
                old['chunks'].append(dict(id=i,name=name,file=file,**meta))
                edited=data.copy();change(i,edited)
                meta=write(out/'canonical/full'/file,edited)
                scene['chunks'].append(dict(id=i,name=name,file=file,**meta))
            parent=dict(passed=True,trianglesChecked=42,unsupportedAreaM2=0.,worstTriangleM2=0.)
            with patch('prepare_transport_surfaces.audit',return_value=dict(passed=True,trianglesChecked=7,unsupportedAreaM2=0.,worstTriangleM2=0.)) as audit:
                result=incremental_paint_audit(base,out,old,scene,np.zeros(3),[2],parent)
                self.assertEqual(audit.call_args.args[-1],{2})
                return result
    def test_rail_restyle_preserves_validated_asphalt_and_paint(self):
        def change(i,w):
            if i==1:w[1,:,6]=0x800000d2
        result=self.check(change)
        self.assertTrue(result['passed']);self.assertEqual(result['trianglesChecked'],49)
    def test_asphalt_change_invalidates_inherited_proof(self):
        def change(i,w):
            if i==1:w.view('<f4')[0,:,1]+=.01
        with self.assertRaisesRegex(AssertionError,'asphalt changed'):self.check(change)
    def test_paint_change_invalidates_inherited_proof(self):
        def change(i,w):
            if i==0:w.view('<f4')[:,:,0]+=.1
        with self.assertRaisesRegex(AssertionError,'paint changed'):self.check(change)

if __name__=='__main__':unittest.main()
