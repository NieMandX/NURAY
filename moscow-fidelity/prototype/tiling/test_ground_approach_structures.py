"""Real multi-level Moscow contacts must clear without loosening the audit."""
import gzip,json,unittest
from collections import defaultdict
from pathlib import Path
import numpy as np
import shapely as sh
from shapely.affinity import translate
from build import triangulate,z_at,plane
from overpasses import build as build_decks
from tunnel_walls import build as build_walls
from interface_validation import check_interfaces


class GroundApproachStructures(unittest.TestCase):
    def test_real_contacts_and_translated_copy(self):
        path=Path(__file__).resolve().parents[1]/'fixtures/ground-approach-structures.json.gz'
        fixture=json.loads(gzip.decompress(path.read_bytes()))
        serialized=fixture['serialized']
        volumes=[(r['interface'],[(sh.geometry.shape(g),np.asarray(p)) for g,p in r['cells']])
                 for r in serialized['volumes']]
        before=check_interfaces(volumes,[(n,np.asarray(t)) for n,t in serialized['meshes']])
        self.assertEqual(sum(not r['passed'] for r in before['checks']),5)
        for dx,dy in ((0.,0.),(-2125.,-8070.)):
            with self.subTest(translation=(dx,dy)):
                city=json.loads(json.dumps(fixture['city']))
                def geometry(g):return sh.geometry.mapping(translate(sh.geometry.shape(g),dx,dy))
                def coefficients(c):return np.asarray(c)+[0,0,-c[0]*dx-c[1]*dy]
                city['originMSK'][:2]=[city['originMSK'][0]+dx,city['originMSK'][1]+dy]
                city['boundsMSK']=(np.array(city['boundsMSK'])+[dx,dy,dx,dy]).tolist()
                rows=[]
                for s in city['surfaces']:
                    rows.append(dict(s,poly=sh.geometry.shape(geometry(s['geometry'])),plane=coefficients(s['heightPlane'])))
                for f in city['features']:
                    xyz=np.array(f['coordinates']);xyz[:,:2]+=[dx,dy];f['coordinates']=xyz.tolist()
                for c in city['gradeConnections']:
                    for key in ('mouthGeometry','landingGeometry','connectorGeometry'):
                        if c.get(key):c[key]=geometry(c[key])
                dem=[(sh.geometry.shape(geometry(g)),coefficients(c)) for g,c in fixture['dem']]
                tree=sh.STRtree([p for p,c in dem]);extent=sh.box(*city['boundsMSK'])
                owners={o for p in city['overpassProfiles'] for o in p['sourceParents']}
                elevated=[s for s in rows if s['kind']=='roadbed_overpass' and s['owner'] in owners]
                groups=defaultdict(list)
                profiles,_=build_decks(elevated,dem,tree,groups,extent,1e-5,triangulate,z_at,plane,
                    city['gradeConnections'],collision_floors=rows)
                self.assertTrue(all(p['passed'] for p in profiles))
                _,walls=build_walls(rows,city['features'],dem,tree,groups,extent,1e-5,
                    city['gradeConnections'],city['sourceStyle'],triangulate,z_at,plane)
                self.assertTrue(walls['passed'])
                replaced={n for n,m in groups};origin=np.array(city['originMSK'])
                meshes=[(n,np.asarray(ts)) for n,ts in serialized['meshes'] if n not in replaced]
                meshes.extend((name,((np.asarray(ts)-origin)[:,:,[0,2,1]]*[1,1,-1]).astype('f4').astype(float))
                    for (name,material),ts in groups.items() if len(ts))
                after=check_interfaces(volumes,meshes)
                self.assertTrue(after['passed'],after)
                self.assertEqual(sum(r['blockingFaceAreaM2'] for r in after['checks']),0)
                self.assertEqual(before['areaToleranceM2'],after['areaToleranceM2'])


if __name__=='__main__':unittest.main()
