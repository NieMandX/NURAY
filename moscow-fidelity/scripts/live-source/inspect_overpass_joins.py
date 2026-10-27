"""Extract exact failed shoulder joins and a compact structural-only witness.

Reads a trusted, receipt-checked local checkpoint. No scene geometry is edited.
The witness retains GEOS precision and every road/terrain cell within the
construction algorithm's reach; downstream rebuilds still validate all joins.
"""
import argparse,json,sys,pickle,faulthandler,signal
from pathlib import Path
import numpy as np
import shapely as sh
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'prototype'))
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'prototype/tiling'))
import build as b
from region_checkpoint import restore
from geometry_pickle import dump


def main():
    p=argparse.ArgumentParser();p.add_argument('checkpoint',type=Path);p.add_argument('output',type=Path)
    a=p.parse_args();a.output.mkdir(parents=True,exist_ok=True)
    faulthandler.register(signal.SIGUSR1,all_threads=True)
    restore(b,a.checkpoint)
    elevated=[s for s in b.surfaces if s['kind']=='roadbed_overpass']
    floors=[s for s in b.surfaces if s['kind'].startswith('roadbed')]
    print('RESTORED',len(b.surfaces),'cells;',len(elevated),'elevated',flush=True)
    reports=[]
    for profile in b.overpass_profiles:
        if profile['passed']:continue
        parents=set(profile['sourceParents']);rows=[s for s in elevated if s['owner'] in parents]
        supports=[dict(poly=sh.set_precision(sh.geometry.shape(s['geometry']),b.GRID,mode='pointwise'),
                       plane=np.asarray(s['heightPlane'])) for s in profile['extensionHeightCells']]
        tree=sh.STRtree([s['poly'] for s in supports]);witnesses=[]
        for row in rows:
            for j in tree.query(row['poly'],predicate='intersects'):
                other=supports[int(j)]
                for line in b.parts(row['poly'].intersection(other['poly']),'LineString'):
                    xy=np.asarray(line.coords)[:,:2]
                    errors=abs(b.z_at(other['plane'],xy)-b.z_at(row['plane'],xy))
                    if max(errors,default=0)<.0005:continue
                    witnesses.append(dict(errorM=float(max(errors)),points=xy.tolist(),
                        roadId=row['id'],owner=row['owner'],roadPlane=row['plane'].tolist(),
                        supportPlane=other['plane'].tolist(),road=sh.geometry.mapping(row['poly']),
                        support=sh.geometry.mapping(other['poly']),
                        distancesToSupport=[sh.Point(q).distance(other['poly']) for q in xy],
                        distancesToRoad=[sh.Point(q).distance(row['poly']) for q in xy]))
        witnesses.sort(key=lambda w:-w['errorM'])
        reports.append(dict(profile={k:v for k,v in profile.items() if 'Geometry' not in k and k!='extensionHeightCells'},
                            witnesses=witnesses[:100],witnessCount=len(witnesses)))
    (a.output/'failed-joins.json').write_text(json.dumps(reports,ensure_ascii=False,indent=2))
    print('FAILED JOIN WITNESSES',[(r['witnessCount'],r['witnesses'][0]['errorM'] if r['witnesses'] else None) for r in reports],flush=True)
    # Structural partitioning compares owners within four overhangs. Include
    # that whole reach, plus the 0.01 m numerical margin, in the retained DEM.
    width=max((r.get('profile',{}).get('overhang',1.) for r in elevated),default=1.)
    reach=sh.union_all([r['poly'] for r in elevated],grid_size=b.GRID).buffer(width*5+.01)
    dem=[b.dem[int(i)] for i in sorted(b.demtree.query(reach,predicate='intersects'))]
    tree=sh.STRtree([s['poly'] for s in floors])
    nearby=[floors[int(i)] for i in sorted(tree.query(reach,predicate='intersects'))]
    witness=dict(connections=b.grade_connections,dem=dem,extent=b.EXTENT,surfaces=elevated,collisionFloors=nearby)
    path=a.output/'structural-input.pkl';temporary=path.with_suffix('.tmp')
    with temporary.open('wb') as stream:dump(witness,stream)
    temporary.replace(path)
    print('STRUCTURAL WITNESS',len(elevated),len(dem),len(nearby),path,flush=True)


if __name__=='__main__':main()
