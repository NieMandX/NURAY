import unittest,tempfile,gzip,copy,shutil
from pathlib import Path
import numpy as np
import shapely as sh
from walking_structure_refresh import affected_profiles,position_keys,replacement_mask,serialized_words
from transport_ground import triangle_words,restore_land


class WalkingStructureRefresh(unittest.TestCase):
    def test_same_name_different_materials_use_parent_buffer_layout(self):
        from apply_walking_structures import replace_structural_meshes
        from prepare_road_paint import write,read
        origin=np.zeros(3);old_groups={};new_groups={};scene={'chunks':[]}
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory)/'base';out=Path(directory)/'out';folder=base/'canonical/full';folder.mkdir(parents=True)
            for index,material in enumerate((11,10)):
                face=np.array([[[0,0,index],[1,0,index],[0,1,index]]],float)
                retained=face+[100,100,0];key=('parapet_side',material)
                old_groups[key]=face;new_groups[key]=np.concatenate([face+[0,0,2],face+[0,0,4]])
                words=triangle_words(np.concatenate([face,retained]),origin,material)
                file=f'mesh-{index}.gz';meta=write(folder/file,words)
                scene['chunks'].append(dict(id=index,name=key[0],file=file,**meta))
            shutil.copytree(base,out);original=copy.deepcopy(scene)
            changes,matches=replace_structural_meshes(base,out,scene,original,
                dict(old=dict(groups=old_groups),new=dict(groups=new_groups)),origin)
            self.assertEqual(len(changes),2)
            for c in scene['chunks']:
                material=(11,10)[c['id']];actual=read(out,c)
                self.assertEqual(len(actual),3)
                self.assertTrue(np.all((actual[:,0,6]&0x7fffffff)==material))
                retained=read(base,original['chunks'][c['id']])[1:]
                self.assertTrue(replacement_mask(actual,position_keys(retained)).any())

    def test_matches_existing_packer_after_float32_collapse(self):
        from object_geometry import pack
        from prepare_transport_surfaces import attrs
        faces=np.array([[[5000,5000,20],[5001,5000,20],[5000,5001,20]],
                        [[5000,5000,20],[5000.000001,5000,20],[5000,5001,20]]])
        origin=np.zeros(3)
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'mesh.gz';meta=pack(attrs(faces,origin),np.array([10,10]),path)
            raw=gzip.decompress(path.read_bytes());vertices=np.frombuffer(raw[:meta['vertexBytes']],'<u4').reshape(-1,8)
            indices=np.frombuffer(raw[meta['vertexBytes']:],'<u4').reshape(-1,3)
            actual=position_keys(vertices[indices]);expected=position_keys(serialized_words(faces,origin,10))
        self.assertEqual(len(expected),1)
        np.testing.assert_array_equal(actual,expected)

    def test_triangle_ownership_distinguishes_stacked_decks(self):
        face=np.array([[[0,0,2],[1,0,2],[0,1,2]]],float)
        original=triangle_words(face,np.zeros(3),10)
        stacked=triangle_words(face+[0,0,4],np.zeros(3),10)
        expected=position_keys(original)
        rotated=original[:,[1,2,0],:].copy();rotated[:,:,3]=0
        self.assertEqual(replacement_mask(np.concatenate([rotated,stacked]),expected).tolist(),[True,False])
        nearby=triangle_words(face+[0,0,.002],np.zeros(3),10)
        self.assertFalse(replacement_mask(nearby,expected).any())

    def test_dependency_selection_ignores_ordinal_renumbering(self):
        def profile(x,owner):return dict(sideOverhangM=1,sourceParents=[owner],asphaltGeometry=sh.geometry.mapping(sh.box(x,0,x+2,10)))
        profiles=[profile(0,'a'),profile(5,'b'),profile(100,'c'),profile(500,'a')]
        entry=dict(id='old',kind='roadbed_overpass',transport='pedestrian',sourceParents=['a'],
                   mouthGeometry=sh.geometry.mapping(sh.LineString([(0,0),(2,0)])))
        selected,changed=affected_profiles(profiles,[entry],[dict(entry,id='new',evidence='new wording')])
        self.assertEqual((selected,changed),([],[]))
        selected,changed=affected_profiles(profiles,[],[entry])
        self.assertEqual(selected,[0,1,3])

    def test_repeated_ground_repairs_have_distinct_stable_ids(self):
        dem=[(sh.box(-5,-5,5,5),np.array([0.,0.,0.]))];tree=sh.STRtree([dem[0][0]])
        a=restore_land(sh.box(0,0,1,1),[],dem,tree)
        b=restore_land(sh.box(2,0,3,1),[],dem,tree)
        self.assertEqual(a,restore_land(sh.box(0,0,1,1),[],dem,tree))
        self.assertFalse({s['id'] for s in a}.intersection(s['id'] for s in b))


if __name__=='__main__':unittest.main()
