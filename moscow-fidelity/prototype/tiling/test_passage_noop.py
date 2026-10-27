import unittest,copy,json,tempfile,hashlib
from pathlib import Path
from prepare_passage_clearance import already_clear,preserve_clear_version


class PassageNoop(unittest.TestCase):
    def setUp(self):
        self.c=[dict(id='a',peerKind='pedestrian_ground',landingGeometry={'coordinates':[[0,0],[1,0]]})]
        self.i=[dict(id='i',ends=[dict(kind='pedestrian_ground')])]
        self.city=dict(gradeConnections=self.c,roadInterfaces=self.i,
            landscape=dict(version=2,numericCleanup=dict(minResolvedWidthM=.0001)),
            tunnelWalls=dict(ruleVersion=4,groups=[dict(guardAboveLandM=1.)]))
        self.audit={'source':{'passed':True},'fullWidth':{'passed':True}}

    def test_current_exact_topology_and_mesh_audit(self):
        self.assertTrue(already_clear(self.city,self.c,self.i,self.audit))

    def test_region_without_walking_structures_can_be_preserved(self):
        city=copy.deepcopy(self.city);city['gradeConnections']=[];city['roadInterfaces']=[]
        self.assertTrue(already_clear(city,[],[],self.audit))

    def test_geometry_or_source_obstruction_requires_rebuild(self):
        for key in ('source','fullWidth'):
            audit=copy.deepcopy(self.audit);audit[key]['passed']=False
            self.assertFalse(already_clear(self.city,self.c,self.i,audit))

    def test_changed_mouth_or_missing_interface_requires_rebuild(self):
        changed=copy.deepcopy(self.c);changed[0]['landingGeometry']['coordinates'][1][0]=2
        self.assertFalse(already_clear(self.city,changed,self.i,self.audit))
        self.assertFalse(already_clear(self.city,self.c,[],self.audit))
        self.assertFalse(already_clear(self.city,[],[],self.audit))

    def test_legacy_recipe_requires_rebuild_even_with_clear_mouth(self):
        for path,value in [('version',1),('numericCleanup',{})]:
            city=copy.deepcopy(self.city);city['landscape'][path]=value
            self.assertFalse(already_clear(city,self.c,self.i,self.audit))
        city=copy.deepcopy(self.city);city['tunnelWalls']['groups'][0]['guardAboveLandM']=.1
        self.assertFalse(already_clear(city,self.c,self.i,self.audit))

    def test_preserved_release_keeps_meshes_and_parent_bytes(self):
        with tempfile.TemporaryDirectory() as folder:
            base=Path(folder)/'base';out=Path(folder)/'checked'
            (base/'canonical/full').mkdir(parents=True)
            city=copy.deepcopy(self.city);city.update(geometryRevision={'type':'prior'},rules={'test':'prior'})
            source=json.dumps(city).encode();(base/'canonical/urban-model.json').write_bytes(source)
            (base/'canonical/terrain.npz').write_bytes(b'unchanged terrain')
            (base/'canonical/full/scene.json').write_text('{"chunks":[]}')
            mesh=b'\x00\x01original mesh\xff';(base/'canonical/full/mesh.bin.gz').write_bytes(mesh)
            parent_proof=b'{"passed":true}';(base/'validation.json').write_bytes(parent_proof)
            (base/'canonical/validation.json').write_bytes(parent_proof)
            preserve_clear_version(base,out,city,{},dict(passed=True),self.audit,self.c,self.i)
            self.assertEqual((base/'canonical/urban-model.json').read_bytes(),source)
            self.assertEqual((out/'canonical/full/mesh.bin.gz').read_bytes(),mesh)
            self.assertEqual((out/'canonical/full/scene.json').read_bytes(),(base/'canonical/full/scene.json').read_bytes())
            saved=json.loads((out/'canonical/urban-model.json').read_text())
            self.assertEqual(saved['geometryRevision']['parentValidationSha256'],hashlib.sha256(parent_proof).hexdigest())
            self.assertEqual(saved['geometryRevision']['changedChunks'],[])
            self.assertEqual(saved['geometryRevision']['previousRevision'],{'type':'prior'})


if __name__=='__main__':unittest.main()
