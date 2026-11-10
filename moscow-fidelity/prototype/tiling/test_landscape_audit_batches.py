"""Bounded audit temporaries must retain every original comparison."""
import unittest
import numpy as np
import shapely as sh
from landscape_validation import verify_preserved_non_lawn,terrain_height_error


def encoded(triangles):
    vertices=np.asarray(triangles,dtype='<u4').reshape(-1,8)
    indices=np.arange(len(vertices),dtype='<u4')
    return vertices.tobytes()+indices.tobytes(),vertices.nbytes


class LandscapeAuditBatches(unittest.TestCase):
    def test_retained_corners_across_different_partition_boundaries(self):
        rng=np.random.default_rng(329)
        before=rng.integers(0,2**32,size=(29,3,8),dtype='<u4')
        materials=np.array(([2,7,30,2,2,7,2]*5)[:len(before)],dtype='<u4')
        before[:,:,6]=materials[:,None]|0x80000000
        retained=before[materials!=2]
        green=before[materials==2].copy();green[:,:,6]=0x80000021
        after=np.concatenate([green[:3],retained[:2],green[3:7],retained[2:9],green[7:],retained[9:]])
        a,av=encoded(before);b,bv=encoded(after)
        for size in (1,2,3,7,13,100):
            self.assertEqual(verify_preserved_non_lawn(a,av,b,bv,{2,33},batch_size=size),len(retained))
            corrupt=after.copy();j=np.flatnonzero((corrupt[:,0,6]&0x7fffffff)==7)[-1]
            corrupt[j,2,4]^=1
            bad,bad_bytes=encoded(corrupt)
            with self.assertRaisesRegex(AssertionError,'non-lawn corners'):
                verify_preserved_non_lawn(a,av,bad,bad_bytes,{2,33},batch_size=size)
            shortened,short_bytes=encoded(after[:-1])
            with self.assertRaisesRegex(AssertionError,'non-lawn corners'):
                verify_preserved_non_lawn(a,av,shortened,short_bytes,{2,33},batch_size=size)

    def test_ignored_materials_are_still_checked_and_empty_output_is_valid(self):
        tris=np.zeros((5,3,8),dtype='<u4');tris[:,:,6]=0x80000002
        a,av=encoded(tris)
        self.assertEqual(verify_preserved_non_lawn(a,av,a,av,{2},batch_size=2),0)
        corrupt=tris.copy();corrupt[-1,-1,6]=0x80000007;b,bv=encoded(corrupt)
        with self.assertRaisesRegex(AssertionError,'Mixed material'):
            verify_preserved_non_lawn(a,av,b,bv,{2},batch_size=2)
        no_lawn=tris.copy();no_lawn[:,:,6]=0x80000007;b,bv=encoded(no_lawn)
        with self.assertRaisesRegex(AssertionError,'no source lawn'):
            verify_preserved_non_lawn(b,bv,b,bv,{2},batch_size=2)

    def test_height_batching_preserves_tree_ties_and_exact_error(self):
        polys=[sh.box(x,y,x+1,y+1) for x in range(4) for y in range(4)]
        tree=sh.STRtree(polys)
        planes=np.arange(48,dtype=float).reshape(-1,3)*.000007
        rng=np.random.default_rng(819)
        xy=np.concatenate([rng.uniform(-.5,4.5,(1037,2)),np.array([[x,y] for x in range(5) for y in range(5)])])
        ids=tree.nearest(sh.points(xy));base=(planes[ids,:2]*xy).sum(1)+planes[ids,2]
        points=np.column_stack([xy,base+.2+rng.uniform(-.001,.001,len(xy))])
        expected=float(np.abs(points[:,2]-base-.2).max(initial=0))
        class BoundedTree:
            def __init__(self,limit):self.limit=limit
            def nearest(self,points):
                selftest.assertLessEqual(len(points),self.limit)
                return tree.nearest(points)
        selftest=self
        for size in (1,17,128,10000):
            self.assertEqual(terrain_height_error(points,planes,BoundedTree(size),.2,batch_size=size),expected)
        self.assertEqual(terrain_height_error(points[:0],planes,tree,.2),0.)
        points[-1,2]=np.nan
        self.assertTrue(np.isnan(terrain_height_error(points,planes,tree,.2,batch_size=17)))


if __name__=='__main__':unittest.main()
