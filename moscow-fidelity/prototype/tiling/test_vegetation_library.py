"""Geometry contracts for every original library model, not image snapshots."""
import json, unittest
from pathlib import Path
from collections import Counter
import numpy as np
from vegetation_library import catalog, PALETTE

class LibraryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source=Path(__file__).resolve().parents[2]/'web-preview/prototype/tiles/assets-km1-vegetation/canonical/full/scene.json'
        cls.source=json.loads(source.read_text());cls.models=catalog(cls.source)

    def test_inventory_and_reproducibility(self):
        self.assertEqual(len(self.models),20)
        self.assertEqual(len({m['layer'] for m in self.models}),9)
        for a,b in zip(self.models,catalog(self.source)):
            self.assertEqual(a['id'],b['id'])
            self.assertTrue(np.array_equal(a['attributes'],b['attributes']))
            self.assertTrue(np.array_equal(a['materials'],b['materials']))

    def test_geometry_envelopes_and_closed_components(self):
        for row in self.models:
            with self.subTest(model=row['id']):
                a=row['attributes'];p=a[:,:,:3];n=a[:,:,3:6]
                self.assertLessEqual(len(a),400)
                self.assertTrue(np.isfinite(a).all())
                self.assertTrue(np.allclose(np.linalg.norm(n,axis=2),1,atol=1e-10))
                self.assertTrue(np.allclose(p.min((0,1)),row['sourceBounds']['min'],rtol=0,atol=1e-9))
                self.assertTrue(np.allclose(p.max((0,1)),row['sourceBounds']['max'],rtol=0,atol=1e-9))
                self.assertTrue(np.all((row['materials']>=0)&(row['materials']<len(PALETTE))))
                for start,end in row['components']:
                    part=p[start:end];edges=Counter();directions=Counter()
                    cross=np.cross(part[:,1]-part[:,0],part[:,2]-part[:,0])
                    self.assertTrue(np.all(np.linalg.norm(cross,axis=1)>1e-8))
                    self.assertTrue(np.all(np.sum(cross*n[start:end,0],axis=1)>0))
                    # Signed volume must be positive; each edge occurs twice
                    # in opposite directions (closed, consistently oriented).
                    self.assertGreater(np.sum(part[:,0]*np.cross(part[:,1],part[:,2]))/6,1e-8)
                    for t in np.round(part,8):
                        v=list(map(tuple,t))
                        for x,y in ((v[0],v[1]),(v[1],v[2]),(v[2],v[0])):
                            edges[tuple(sorted((x,y)))]+=1;directions[x,y]+=1
                    self.assertTrue(all(k==2 for k in edges.values()))
                    self.assertTrue(all(directions[y,x]==count for (x,y),count in directions.items()))

if __name__=='__main__':unittest.main()
