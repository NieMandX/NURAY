import copy,gzip,json,unittest,tempfile,hashlib
from pathlib import Path
import numpy as np
import shapely as sh
from passage_curb_refinement import plan,refine_words,additions,same_effective_entries,local_mesh_changes,edited_surfaces,restored_parent,addition_targets
from transport_ground import triangle_words
from interface_validation import check_interfaces
from prepare_road_paint import read,write
from canonical_store import dump_compact


class LocalCurbChecks(unittest.TestCase):
    def fixture(self):
        path=Path(__file__).resolve().parents[1]/'fixtures/passage-curb-contacts.json.gz'
        with gzip.open(path,'rt') as f:c=json.load(f)
        volumes=[(r,[(sh.geometry.shape(g),np.asarray(p)) for g,p in cells]) for r,cells in c['volumes']]
        dem=[(sh.geometry.shape(g),np.asarray(p)) for g,p in c['dem']]
        meshes=[(k,np.asarray(v)) for k,v in c['meshes']]
        actual=check_interfaces(volumes,meshes)
        self.assertFalse(actual['passed'])
        return c,volumes,dem,meshes,actual

    def product(self):
        c,v,dem,m,a=self.fixture()
        product=plan(c,v,a['checks'],dem,sh.STRtree([p for p,_ in dem]))
        return c,v,m,product

    def test_both_actual_passages_clear_without_moving_the_terrain(self):
        c,volumes,meshes,p=self.product();origin=np.asarray(c['originMSK']);out=[]
        for name,ts in meshes:
            words=triangle_words(ts[:,:,[0,2,1]]*[1,-1,1]+origin,origin,9)
            refined=refine_words(name,words,origin,p)
            out.append((name,(words if refined is None else refined).view('<f4')[:,:,:3]))
        for name,words in additions(p,origin).items():out.append((name,words.view('<f4')[:,:,:3]))
        self.assertTrue(check_interfaces(volumes,out)['passed'])
        old={s['id']:s for s in c['surfaces']}
        for s in p['paving']:
            self.assertEqual(s['heightPlane'],old[s['replacedCurbSurface']]['heightPlane'])
        # The old horizontal cover is partitioned, never deleted into a hole.
        before=sh.union_all([sh.geometry.shape(old[i]['geometry']) for i in p['edits']])
        after=sh.union_all([sh.geometry.shape(s['geometry']) for s in [*p['edits'].values(),*p['paving']] if s])
        self.assertLess(before.symmetric_difference(after).area,1e-7)

    def test_unrelated_triangles_retain_all_packed_attributes(self):
        c,_,_,p=self.product();origin=np.asarray(c['originMSK'])
        words=triangle_words([[[0,0,0],[1,0,0],[0,1,0]]],origin,9)
        self.assertIsNone(refine_words('curb_top',words,origin,p))
        self.assertIsNone(refine_words('overpass_side',words,origin,p))
        self.assertIsNone(refine_words('land',words,origin,p))

    def test_mixed_structural_obstruction_requires_other_builder(self):
        c,v,d,m,a=self.fixture();a['checks'][0]['resolvedBlockingKinds']['overpass_side']=1.
        with self.assertRaisesRegex(AssertionError,'Non-curb obstruction'):
            plan(c,v,a['checks'],d,sh.STRtree([p for p,_ in d]))

    def test_effective_entry_allows_only_disconnected_apron_removal(self):
        mouth=sh.LineString([(0,0),(0,2)]);connected=sh.box(-1,0,0,2);island=sh.box(-4,0,-3,1)
        a=dict(id='entry',mouthGeometry=sh.geometry.mapping(mouth),landingGeometry=sh.geometry.mapping(sh.union_all([connected,island])))
        b=dict(a,landingGeometry=sh.geometry.mapping(connected))
        self.assertTrue(same_effective_entries([a],[b]))
        bad=dict(b,landingGeometry=sh.geometry.mapping(sh.box(-.5,0,0,2)))
        self.assertFalse(same_effective_entries([a],[bad]))
        self.assertFalse(same_effective_entries([a],[dict(b,id='other')]))

    def test_serialized_local_repair_preserves_unrelated_mesh_and_land_attributes(self):
        c,volumes,meshes,p=self.product();origin=np.asarray(c['originMSK'])
        untouched=triangle_words([[[0,0,0],[1,0,0],[0,1,0]]],origin,7)
        scene=dict(chunks=[])
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory)/'base';out=Path(directory)/'out'
            for root in (base,out):(root/'canonical/full').mkdir(parents=True)
            for i,(name,ts) in enumerate(meshes+[('land',untouched.view('<f4')[:,:,:3]),('building',untouched.view('<f4')[:,:,:3])]):
                words=triangle_words(ts[:,:,[0,2,1]]*[1,-1,1]+origin,origin,7 if name=='land' else 9)
                path=f'mesh-{i}.bin.gz';meta=write(base/'canonical/full'/path,words)
                scene['chunks'].append(dict(id=i,name=name,file=path,**meta))
                (out/'canonical/full'/path).write_bytes((base/'canonical/full'/path).read_bytes())
            original=copy.deepcopy(scene)
            local_mesh_changes(base,out,scene,p,origin)
            land=next(x for x in original['chunks'] if x['name']=='land')
            np.testing.assert_array_equal(read(base,land),read(out,scene['chunks'][land['id']])[:land['triangles']])
            building=next(x for x in original['chunks'] if x['name']=='building')
            self.assertEqual((base/'canonical/full'/building['file']).read_bytes(),(out/'canonical/full'/building['file']).read_bytes())
            current=[(x['name'],read(out,x).view('<f4')[:,:,:3]) for x in scene['chunks']]
            self.assertTrue(check_interfaces(volumes,current)['passed'])
            # Reproduce the release audit on the serialized, indexed meshes,
            # including exact normals/UV/material words, not just occupancy.
            extra=additions(p,origin);targets=addition_targets(base,original,extra)
            for a,b in zip(original['chunks'],scene['chunks']):
                words=read(base,a);expected=refine_words(a['name'],words,origin,p)
                if expected is None:expected=words
                if targets.get(a['name'])==a['id']:
                    expected=np.concatenate([expected,extra[a['name']]])
                if a['name'] in ('curb_top','curb_bottom','curb_front','curb_back'):
                    pts=expected.view('<f4')[:,:,:3]
                    expected=expected[np.linalg.norm(np.cross(pts[:,1]-pts[:,0],pts[:,2]-pts[:,0]),axis=1)>1e-9]
                np.testing.assert_array_equal(expected,read(out,b))

    def test_parent_reconstruction_proves_all_unrelated_canonical_values(self):
        c,_,_,p=self.product();before=dict(c,rules={'old':'retained'},geometryRevision={'type':'prior'})
        h=hashlib.sha256()
        class Writer:
            def write(self,text):h.update(text.encode())
        dump_compact(before,Writer())
        rev=dict(previousRevision=before['geometryRevision'],beforeRules=before['rules'],
            beforeSurfaces=[dict(index=i,row=s) for i,s in enumerate(before['surfaces']) if s['id'] in p['edits']],
            pavingIds=[s['id'] for s in p['paving']],parentCanonicalSha256=h.hexdigest())
        current=dict(before,surfaces=edited_surfaces(before['surfaces'],p),rules={'new':'rule'},geometryRevision=rev)
        current=json.loads(json.dumps(current))
        self.assertEqual(restored_parent(current),before)
        changed=dict(current,originMSK=[0,0,0])
        with self.assertRaisesRegex(AssertionError,'unrelated canonical'):restored_parent(changed)

    def test_paving_is_not_appended_to_an_existing_lawn_batch(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'canonical/full').mkdir(parents=True)
            scene=dict(chunks=[])
            for i,material in enumerate((1,7)):
                words=triangle_words([[[0,0,0],[1,0,0],[0,1,0]]],np.zeros(3),material)
                name=f'mesh-{i}.gz';meta=write(root/'canonical/full'/name,words)
                scene['chunks'].append(dict(id=i,name='land',file=name,**meta))
            self.assertEqual(addition_targets(root,scene,{'land':words}),{'land':1})

    def test_actual_surface_replay_survives_canonical_json_roundtrip(self):
        c,_,_,p=self.product()
        expected=edited_surfaces(c['surfaces'],p)
        persisted=json.loads(json.dumps(expected))
        # The release verifier compares reloaded JSON with a fresh replay.
        # GEOS mapping tuples must not create false geometry differences.
        self.assertEqual(persisted,expected)
        changed=copy.deepcopy(persisted)
        changed[-1]['geometry']['coordinates'][0][0][0]+=.01
        self.assertNotEqual(changed,expected)


if __name__=='__main__':unittest.main()
