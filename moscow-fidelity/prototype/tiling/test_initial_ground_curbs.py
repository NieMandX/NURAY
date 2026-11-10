import copy
import json
import tempfile
import unittest
from collections import defaultdict
from pathlib import Path
from unittest.mock import patch
import numpy as np
import shapely as sh
from build import triangulate,z_at
from curbs import solid_sides
from prepare_road_paint import read,write,world
from transport_ground import restore_land,initial_curb_faces,triangle_words,apply,clip_mesh,plan


class InitialGroundCurbs(unittest.TestCase):
    def test_initial_build_restores_curbs_but_targeted_release_still_rejects_them(self):
        road=sh.box(-4,-3,4,0);missing=sh.box(1,0,2,1);old=sh.box(0,0,1,.15)
        rows=[dict(id='road',kind='roadbed_flat',geometry=sh.geometry.mapping(road)),
              dict(id='old-curb',kind='curb_top',geometry=sh.geometry.mapping(old))]
        class Document:
            def read(self,key):return dict(groundRoadGeometry=sh.geometry.mapping(road),gradeConnections=[])[key]
            def items(self,key):return iter(rows if key=='surfaces' else [])
        terrain=[(sh.box(-5,-5,5,5),np.array([.03,.02,4.]))]
        context=(terrain,sh.STRtree([terrain[0][0]]))
        delta={key:dict(groundContactGeometry=sh.geometry.mapping(geometry))
               for key,geometry in [('added',sh.Polygon()),('removed',missing)]}
        with patch('transport_ground.audit',return_value=delta):
            with self.assertRaisesRegex(AssertionError,'road curb'):
                plan(None,[],Document(),terrain=context)
            cut,edits,deleted,restored,proof=plan(None,[],Document(),terrain=context,allow_initial_curbs=True)
        self.assertLess(proof['exposedGroundHoleM2'],1e-7)
        self.assertAlmostEqual(proof['curbRepair']['addedTopM2'],.15)
        self.assertEqual({s['kind'] for s in restored},{'land','curb_top'})
        self.assertTrue(cut.is_empty);self.assertFalse(edits);self.assertFalse(deleted)

    def test_real_narrow_moscow_tip_preserves_the_joined_outer_boundary(self):
        data=json.loads((Path(__file__).resolve().parents[1]/'fixtures/initial-ground-curb.json').read_text())
        old=sh.geometry.shape(data['old']);added=sh.geometry.shape(data['added']);road=sh.geometry.shape(data['road'])
        combined=sh.union_all([old,added],grid_size=1e-5)
        extent=combined.envelope.buffer(5);plane=np.asarray(data['plane'])-[0,0,.1]
        dem=[(extent,plane)];tree=sh.STRtree([extent]);origin=np.asarray(data['origin'])
        region=added.buffer(.05,join_style='mitre')
        rows=restore_land(added,[],dem,tree,curb=added)
        ground=dict(curbRepair=dict(combinedGeometry=sh.geometry.mapping(combined),sideRegionGeometry=sh.geometry.mapping(region)))
        new,_=initial_curb_faces(ground,rows,road,dem,tree,extent)
        original=defaultdict(list);expected=defaultdict(list)
        solid_sides(old,road,dem,tree,original,z_at,extent)
        solid_sides(combined,road,dem,tree,expected,z_at,extent)
        for kind in ('curb_front','curb_back'):
            words=triangle_words(original[(kind,9)],origin,9)
            retained=clip_mesh(words,origin,region)
            actual=np.concatenate([world(words if retained is None else retained,origin),np.asarray(new[(kind,9)]).reshape(-1,3,3)])
            reference=np.asarray(expected[(kind,9)]).reshape(-1,3,3)
            area=lambda ts:np.linalg.norm(np.cross(ts[:,1]-ts[:,0],ts[:,2]-ts[:,0]),axis=1).sum()/2
            self.assertAlmostEqual(area(actual),area(reference),delta=.0002)
            for tri in actual:
                # Millimetre audit bound remains unchanged after Float32 packing.
                self.assertLess(sh.Point(tri[:,:2].mean(0)).distance(combined.boundary),.001)

    def test_restored_curb_is_closed_and_has_no_internal_cap_on_sloping_ground(self):
        extent=sh.box(-5,-5,5,5);dem=[(extent,np.array([.03,.02,4.]))]
        tree=sh.STRtree([extent]);road=sh.box(-4,-3,4,0)
        old=sh.box(0,0,1,.15);added=sh.box(1,0,2,.15);region=sh.box(1,0,2,1)
        side_region=added.buffer(.05,join_style='mitre')
        restored=restore_land(region,[],dem,tree,curb=added)
        area=lambda kind:sh.union_all([sh.geometry.shape(s['geometry']) for s in restored if s['kind']==kind])
        self.assertAlmostEqual(area('curb_top').area,.15)
        self.assertAlmostEqual(area('land').area,.85)
        ground=dict(curbRepair=dict(combinedGeometry=sh.geometry.mapping(old.union(added)),
            sideRegionGeometry=sh.geometry.mapping(side_region)))
        new,mask=initial_curb_faces(ground,restored,road,dem,tree,extent)
        groups=defaultdict(list)
        solid_sides(old,road,dem,tree,groups,z_at,extent)
        groups[('curb_top',9)]=triangulate(old,dem[0][1]+[0,0,.1])
        groups[('curb_bottom',9)]=[t[::-1] for t in triangulate(old,dem[0][1])]
        groups[('land',7)]=triangulate(sh.box(-2,1,-1,2),dem[0][1]+[0,0,.1])
        origin=np.array([10.,20.,3.]);scene=dict(chunks=[])
        with tempfile.TemporaryDirectory() as temporary:
            base=Path(temporary)/'base';out=Path(temporary)/'out'
            for path in (base,out):(path/'canonical/full').mkdir(parents=True)
            for i,((kind,mid),faces) in enumerate(groups.items()):
                words=triangle_words(faces,origin,mid);name=f'mesh-{i:03d}.bin.gz'
                meta=write(base/'canonical/full'/name,words)
                scene['chunks'].append(dict(id=i,name=kind,file=name,**meta))
                (out/'canonical/full'/name).write_bytes((base/'canonical/full'/name).read_bytes())
            before=copy.deepcopy(scene)
            old_land=next(c for c in before['chunks'] if c['name']=='land')
            old_land_words=read(base,old_land)
            apply(base,out,scene,before,origin,sh.Polygon(),restored,curb_faces=new,curb_side_region=mask)
            loaded={c['name']:world(read(out,c),origin) for c in scene['chunks']}
            # The added land occupies its own material and kind; the original
            # packed faces, including their UVs and normals, remain exact.
            land=next(c for c in scene['chunks'] if c['name']=='land')
            np.testing.assert_array_equal(read(out,land)[:len(old_land_words)],old_land_words)
            for kind in ('curb_top','curb_bottom'):
                tris=loaded[kind]
                coverage=sh.union_all([sh.Polygon(t[:,:2]) for t in tris])
                self.assertLess(coverage.symmetric_difference(old.union(added)).area,5e-6)
                level=4.1 if kind=='curb_top' else 4.
                np.testing.assert_allclose(tris[:,:,2],tris[:,:,0]*.03+tris[:,:,1]*.02+level,atol=2e-6)
                normals=np.cross(tris[:,1]-tris[:,0],tris[:,2]-tris[:,0])[:,2]
                self.assertTrue(np.all(normals>0) if kind=='curb_top' else np.all(normals<0))
            sides=np.concatenate([loaded[k] for k in ('curb_front','curb_back')])
            cap=[t for t in sides if np.max(abs(t[:,0]-1))<1e-5]
            self.assertFalse(cap,'The former end cap must disappear inside the joined curb')
            boundary=old.union(added).boundary
            for t in sides:
                self.assertLess(sh.LineString(t[:,:2]).distance(boundary),2e-6)
            front=loaded['curb_front']
            np.testing.assert_allclose(front[:,:,1],0,atol=2e-6)


if __name__=='__main__':unittest.main()
