"""Rebuild structures and their exact ground partition from a fresh checkpoint."""
import argparse,gc,pickle,sys,time,signal,faulthandler,hashlib,subprocess
from pathlib import Path
import numpy as np
import shapely as sh
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import build as b
from region_checkpoint import restore,save
from finish_region import finish
from partition_refinement import refine,clip_triangle
from spatial_mask import SpatialMask

p=argparse.ArgumentParser();p.add_argument('--checkpoint',type=Path,required=True)
p.add_argument('--output-checkpoint',type=Path,required=True);p.add_argument('--source-decode',type=Path,required=True)
p.add_argument('--rebuilt-structures',type=Path)
p.add_argument('--refresh-topology',action='store_true',help='Rebuild ground connections and structures from this capture')
p.add_argument('--output-dir',type=Path,help='New immutable canonical output directory')
p.add_argument('--wait-log',type=Path,help='Wait for the verified structure producer while restoring the checkpoint')
a=p.parse_args();faulthandler.register(signal.SIGUSR1,all_threads=True)
opening,road,checks,total,bound=restore(b,a.checkpoint)
print('RESTORED STRUCTURES',len(b.surfaces),flush=True)
if a.output_dir:
    if a.output_dir.exists():raise FileExistsError(a.output_dir)
    a.output_dir.mkdir(parents=True);b.DATA=a.output_dir.resolve()
with a.source_decode.open('rb') as f:_,state,candidates,_=pickle.load(f)
for tile,digest in {r['source']['tile']:r['source']['fileSha256'] for r in state['records']}.items():
    if hashlib.sha256((b.SOURCE/'source/cache'/f'{tile}.json').read_bytes()).hexdigest()!=digest:
        raise ValueError('Source decode differs from this live capture')
del state;gc.collect()
witness=None
if a.refresh_topology:
    cs,ifs=b.discover_pedestrian_connections(candidates,b.records,road,b.EXTENT,b.GRID,b.z_at,include_mixed_ground=True)
    old=[c for c in b.grade_connections if c.get('peerKind')=='pedestrian_ground'];ids={c['id'] for c in old}
    b.grade_connections=[c for c in b.grade_connections if c.get('peerKind')!='pedestrian_ground']+cs
    b.road_interfaces=[r for r in b.road_interfaces if not any(e['kind']=='pedestrian_ground' for e in r['ends'])]+ifs
    b.relationships=[r for r in b.relationships if not (r.get('type')=='grade-connection' and r.get('owner') in ids)]
    b.relationships.extend(dict(type='grade-connection',owner=c['id'],parents=c['sourceParents']+c['peerParents'],evidence=c['evidence'],connectorAreaM2=0.) for c in cs)
    b.interface_report=b.interface_coverage(b.road_interfaces,b.grade_connections,b.GRID)
    assert b.interface_report['passed']
    print('REFRESHED WALKING ENTRIES',len(old),'->',len(cs),flush=True)
    witness=a.output_checkpoint.with_suffix('.structures-input.pkl')
    with witness.open('wb') as f:pickle.dump(dict(connections=b.grade_connections,dem=b.dem,extent=b.EXTENT,
        surfaces=[s for s in b.surfaces if s['kind']=='roadbed_overpass'],
        collisionFloors=[s for s in b.surfaces if s['kind'].startswith('roadbed')]),f)
    if not a.rebuilt_structures:
        a.rebuilt_structures=a.output_checkpoint.with_suffix('.structures-output.pkl')
        subprocess.run([sys.executable,str(Path(__file__).resolve().parents[2]/'scripts/live-source/rebuild_overpass_witness.py'),
            str(b.SOURCE),'--witness',str(witness),'--output',str(a.rebuilt_structures)],check=True)
for key in list(b.groups):
    if key[0] in {'overpass_bottom','overpass_shoulder','parapet_top','overpass_side','overpass_riser','parapet_side'}:
        b.groups[key]=[];b.shading_flags.pop(key,None)
product=None
if a.rebuilt_structures:
    if a.wait_log:
        deadline=time.monotonic()+3600
        while True:
            log=a.wait_log.read_text() if a.wait_log.exists() else ''
            if 'FULL STRUCTURES VERIFIED ' in log:break
            if 'Traceback (most recent call last)' in log:raise RuntimeError('Structural producer failed; canonical update was not applied')
            if time.monotonic()>deadline:raise TimeoutError('Structural producer did not finish in one hour')
            time.sleep(5)
    with a.rebuilt_structures.open('rb') as f:product=pickle.load(f)
    recipe=hashlib.sha256()
    for name in ('overpasses.py','overpass_sheets.py','transitions.py','structure_clearance.py'):recipe.update((Path(b.__file__).parent/name).read_bytes())
    if product['recipeSha256']!=recipe.hexdigest() or product['sourceReceiptSha256']!=hashlib.sha256((b.SOURCE/'sources.json').read_bytes()).hexdigest():
        raise ValueError('Rebuilt structures do not match the current rule/source capture')
    if witness and product.get('witnessSha256')!=hashlib.file_digest(witness.open('rb'),'sha256').hexdigest():
        raise ValueError('Rebuilt structures do not match the refreshed topology/floor witness')
    b.overpass_profiles=product['profiles'];b.deck_count=product['count'];b.groups.update(product['groups'])
else:b.overpass_profiles,b.deck_count=b.build_overpasses(b.surfaces,b.dem,b.demtree,b.groups,b.EXTENT,b.GRID,b.triangulate,b.z_at,b.plane,b.grade_connections)
failed=[{k:v for k,v in r.items() if 'Geometry' not in k and k not in ('extensionHeightCells','sourceParents')} for r in b.overpass_profiles if not r['passed']]
if failed:
    with (b.SOURCE/'failed-overpass-rebuild.pkl').open('wb') as f:pickle.dump(dict(profiles=b.overpass_profiles,connections=b.grade_connections,dem=b.dem,extent=b.EXTENT,surfaces=[r for r in b.surfaces if r['kind']=='roadbed_overpass']),f)
    raise ValueError(('Structural profiles failed',failed))
print('STRUCTURAL PROFILES VERIFIED',len(b.overpass_profiles),flush=True)
new_cut=b.terrain_cut(b.overpass_profiles,b.surfaces,b.dem,b.demtree,b.grade_connections,b.LAND_RAISE,b.DEPTH,b.GRID)
removed=new_cut.difference(b.transition_cut);restored=b.transition_cut.difference(new_cut).difference(b.union([opening,road]))
print('GROUND PARTITION CHANGE','remove',removed.area,'restore',restored.area,flush=True)
b.transition_cut=new_cut
water_rows=[s for s in b.surfaces if s['kind']=='water' and s['poly'].intersects(removed)]
if water_rows:
    water_cut=SpatialMask(removed)
    for key in list(b.groups):
        if key[0]=='water':
            b.groups[key]=[p for t in b.groups[key] for p in clip_triangle(t,water_cut.near(sh.Polygon(t[:,:2])),b.triangulate,b.plane)]
            b.shading_flags[key]=[False]*len(b.groups[key])
    for s in water_rows:
        s['poly']=s['poly'].difference(removed)
    b.surfaces[:]=[s for s in b.surfaces if not s['poly'].is_empty]
# Restore only the exact ground region released by the corrected deck solids,
# using the same source priorities and shared heights as a complete build.
piers=b.union([r['poly'] for r in candidates if r['layer']=='Pier_quarter'])
water=b.union([r['poly'].intersection(restored) for r in candidates if r['kind']=='water']).difference(piers)
b.lift(water,np.zeros(3),'source:water-union',13,'water',[0])
remaining=restored.difference(water)
for r in sorted([r for r in candidates if r['kind']=='land'],key=lambda r:(-r['rank'],r['poly'].area,r['id'])):
    if not r['poly'].intersects(remaining):continue
    piece=r['poly'].intersection(remaining)
    b.lift(piece,np.array([0,0,b.LAND_RAISE]),r['id'],r['material'],'land',[0]);remaining=remaining.difference(piece)
    if remaining.is_empty:break
if not remaining.is_empty:b.lift(remaining,np.array([0,0,b.LAND_RAISE]),'inferred:unclassified-land',8,'land',[0])
road=refine(b,opening,road,candidates,extra_ground_cut=removed)
del candidates;gc.collect()
if a.refresh_topology:
    from prepare_landscape import WALLS
    for key in list(b.groups):
        if key[0] in WALLS:b.groups[key]=[];b.shading_flags.pop(key,None)
    b.walls(opening,road)
    if not b.wall_report['passed']:raise ValueError('Refreshed retaining walls failed')
save(b,a.output_checkpoint,(opening,road,checks,total,bound))
finish(b,opening,road,checks,total,bound,time.time(),fresh_source=True)
