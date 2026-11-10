"""Resume an unpublished landscape after a retaining-construction rule fix.

Rebuild all guards from source floors and the exact DEM. Reuse the landscape
only if the changed exclusion mask cannot change any of its source coverage.
No positions or object IDs select a repair; a completed release is immutable.
"""
from pathlib import Path
from collections import defaultdict
import argparse,gc,gzip,hashlib,json,pickle
import numpy as np
import shapely as sh
from build import triangulate,z_at,plane
from canonical_store import load_canonical,save_canonical,copy_asset
from terrain_store import read_terrain
from prepare_landscape import WALLS
from tunnel_walls import build
from passage_space import walking_reserve
from transitions import union
from green_insets import protected_ground
from guard_landscape_delta import guard_reserve_envelope
from object_geometry import pack
from portal_validation import verify_headers
from prepare_transport import prepare as prepare_transport


def exclusion(city,walls,*,connected):
    walking=walking_reserve(city['gradeConnections']) if connected else union([
        sh.geometry.shape(c['landingGeometry']) for c in city['gradeConnections']
        if c.get('atGround') and c.get('peerKind')=='pedestrian_ground' and c.get('landingGeometry')],1e-5)
    return protected_ground(dict(city,tunnelWalls=walls),walking=walking)


def guard_cache_key(root):
    h=hashlib.sha256()
    files=[root/'canonical/urban-model.json.gz',root/'canonical/terrain.npz']
    files+=sorted(Path(__file__).resolve().parents[1].glob('*.py'))
    for path in files:
        h.update(path.name.encode())
        with path.open('rb') as stream:
            for block in iter(lambda:stream.read(4*1024*1024),b''):h.update(block)
    return h.hexdigest()


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True)
    ap.add_argument('--backup',type=Path,required=True);args=ap.parse_args()
    root=args.root;folder=root/'canonical/full'
    if (root/'validation.json').exists():raise ValueError('Do not mutate an audited release; use a separate revision')
    print('GUARD REFRESH LOAD',flush=True)
    city=load_canonical(root/'canonical/urban-model.json');gc.freeze()
    assert city['geometryRevision']['type']=='landscape'
    scene=json.loads((folder/'scene.json').read_text())
    report=json.loads((root/'canonical/validation.json').read_text())
    assert report['passed']
    rows=[dict(s,poly=sh.geometry.shape(s['geometry']),plane=np.asarray(s['heightPlane']))
          for s in city['surfaces'] if s['kind'].startswith('roadbed')]
    dem=read_terrain(root/'canonical/terrain.npz');tree=sh.STRtree([p for p,c in dem])
    terrain=([p for p,c in dem],np.asarray([c for p,c in dem]),tree)
    product=args.backup.with_name(args.backup.name+'-product');product.mkdir(parents=True,exist_ok=True)
    cache=product/'guard-layout.pkl.gz';key=guard_cache_key(root)
    cached=None
    if cache.exists():
        with gzip.open(cache,'rb') as stream:cached=pickle.load(stream)
    if cached is not None and cached['key']==key:
        groups,walls=cached['groups'],cached['walls']
        print('REUSE EXACT GUARD BUILD',key,flush=True)
    else:
        groups=defaultdict(list)
        print('REBUILD ALL GUARDS',len(rows),'source floors',flush=True)
        _,walls=build(rows,city['features'],dem,tree,groups,sh.box(*city['boundsMSK']),1e-5,
            city['gradeConnections'],city['sourceStyle'],triangulate,z_at,plane)
        temporary=cache.with_suffix('.tmp')
        with gzip.open(temporary,'wb',compresslevel=1) as stream:
            pickle.dump(dict(key=key,groups=groups,walls=walls),stream,protocol=5)
        temporary.replace(cache)
        print('GUARD BUILD CACHED',cache.stat().st_size,flush=True)
    assert walls['passed']
    changed_exclusion,change_proof=guard_reserve_envelope(city,walls)
    overlaps={k:sh.geometry.shape(city['landscape'][k]).intersection(changed_exclusion).area
              for k in ('raisedGeometry','convertedGeometry','discardedNumericGeometry')}
    (product/'exclusion-difference.json').write_text(json.dumps(dict(
        method='Conservative operand differences minus shared protection',proof=change_proof,
        changed=sh.geometry.mapping(changed_exclusion),overlaps=overlaps,
        overlapGeometry={k:sh.geometry.mapping(sh.geometry.shape(city['landscape'][k]).intersection(changed_exclusion)) for k in overlaps})))
    assert all(v<1e-9 for v in overlaps.values()),('Changed guard needs landscape repartition',overlaps)
    print('LANDSCAPE EXCLUSION UNCHANGED',changed_exclusion.area,overlaps,flush=True)
    # Stage and test generated solids before replacing any existing geometry.
    product_folder=product/'canonical/full'
    product_folder.mkdir(parents=True,exist_ok=True)
    terrain_target=product/'canonical/terrain.npz'
    if not terrain_target.exists():copy_asset(root/'canonical/terrain.npz',terrain_target)
    proposed=json.loads(json.dumps(scene));changed=[];origin=np.asarray(city['originMSK'])
    for name in sorted(WALLS):
        chunks=[c for c in proposed['chunks'] if c['name']==name];faces=groups[(name,6)]
        assert chunks or not faces,('New guard category needs normal landscape build',name)
        for c,part in zip(chunks,np.array_split(np.asarray(faces),len(chunks)) if chunks else []):
            xyz=(part-origin)[:,:,[0,2,1]]*[1,1,-1]
            n=np.cross(xyz[:,1]-xyz[:,0],xyz[:,2]-xyz[:,0]);n/=np.maximum(np.linalg.norm(n,axis=1,keepdims=True),1e-20)
            attrs=np.concatenate([xyz,np.repeat(n[:,None,:],3,axis=1),xyz[:,:,[0,2]]],axis=2)
            target=product_folder/Path(c['file']).name
            meta=pack(attrs,np.full(len(attrs),6,dtype=np.uint32),target)
            assert meta,('Empty rebuilt guard',name)
            c.update(meta)
            before=gzip.decompress((folder/Path(c['file']).name).read_bytes())
            after=gzip.decompress(target.read_bytes())
            if before!=after:changed.append(c['id'])
    header_city=dict(originMSK=city['originMSK'],tunnelWalls=walls,geometryRevision=city['geometryRevision'])
    header_check=verify_headers(product,header_city,proposed,terrain=terrain)
    print('ALL PORTAL HEADERS PASSED',header_check,flush=True)
    # Snapshot this incomplete build; its validated parent is never changed.
    args.backup.mkdir(parents=True,exist_ok=True)
    for relative in ['canonical/urban-model.json.gz','canonical/validation.json','canonical/full/scene.json',
                     'tileset.json','objects.json.gz']+[str(Path('canonical/full')/Path(scene['chunks'][i]['file']).name) for i in changed]:
        source=root/relative;target=args.backup/relative
        target.parent.mkdir(parents=True,exist_ok=True)
        if not target.exists():copy_asset(source,target)
    for i in changed:
        name=Path(proposed['chunks'][i]['file']).name
        copy_asset(product_folder/name,folder/name)
    scene=proposed
    scene['stats'].update(uniqueTriangles=sum(c['triangles'] for c in scene['chunks']),
        expandedTriangles=sum(scene['chunks'][i['mesh']]['triangles'] for i in scene['instances']))
    report['export'].update(triangles=scene['stats']['uniqueTriangles'],expandedTriangles=scene['stats']['expandedTriangles'],
        downloadBytes=sum((folder/Path(c['file']).name).stat().st_size for c in scene['chunks']))
    city['tunnelWalls']=walls;report['tunnelWalls']=walls;city['rules']['tunnelWalls']=walls['policy']
    (folder/'scene.json').write_text(json.dumps(scene,ensure_ascii=False,separators=(',',':')))
    save_canonical(root/'canonical/urban-model.json',city)
    (root/'canonical/validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    prepare_transport(root,city=city,manifest=scene,report=report)
    proof=dict(passed=True,changedChunks=changed,geometryRevision=city['geometryRevision'],
        headerCheck=header_check,changedExclusionAreaM2=changed_exclusion.area,landscapeOverlapM2=overlaps,
        exclusionProof=change_proof,
        terrainAndLandscapeMeshesUnchanged=True,requiresTransportRepack=True,requiresFullAudit=True)
    (root/'guard-refresh-patch.json').write_text(json.dumps(proof,separators=(',',':')))
    print('GUARD REFRESH SAVED',changed,flush=True)


if __name__=='__main__':main()
