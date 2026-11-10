"""Rebuild structural solids before the first successful transport audit.

The fitted terrain, source floors, paint, buildings and instances are retained.
This is an initial-build recovery, not an update to a published/validated city.
The output still requires pack_tiles and the complete independent tile audit.
"""
import argparse,copy,gc,gzip,json,pickle,shutil
from collections import defaultdict
from pathlib import Path
import numpy as np
import shapely as sh
from canonical_store import load_canonical,save_canonical,copy_asset,canonical_digest
from prepare_railway_entries import load_terrain,meshes
from prepare_foundations import digest,refresh_stats,save
from prepare_landscape import WALLS
from prepare_transport_surfaces import STRUCTURES,attrs
from object_geometry import pack
from overpasses import build as build_decks
from tunnel_walls import build as build_walls
from build import triangulate,z_at,plane
from transport_ground import plan as ground_plan,apply as apply_ground,initial_curb_faces
from interface_validation import passage_volumes,check_interfaces
from walking_structure_refresh import refresh_connections,connection_digest


class MemoryDocument:
    def __init__(self,city,path):self.city=city;self.path=path
    def read(self,key):return self.city[key]
    def items(self,key):return iter(self.city[key])


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--base',type=Path,required=True)
    ap.add_argument('--output',type=Path,required=True)
    ap.add_argument('--resume-generated',action='store_true')
    a=ap.parse_args();base=a.base.resolve();out=a.output.resolve()
    if base==out or base.parent!=out.parent:raise ValueError('Use a separate sibling build artifact')
    if (base/'validation.json').exists() and json.loads((base/'validation.json').read_text()).get('passed'):
        raise ValueError('Use the immutable release refinement workflow for a validated parent')
    if out.exists() and not a.resume_generated:raise ValueError('Output already exists; retain it and inspect before resuming')
    report=json.loads((base/'canonical/validation.json').read_text());assert report['passed']
    scene=json.loads((base/'canonical/full/scene.json').read_text());old_scene=copy.deepcopy(scene)
    print('STRUCTURE REPAIR LOADING INITIAL CITY',flush=True)
    city=load_canonical(base/'canonical/urban-model.json');gc.freeze()
    print('STRUCTURE REPAIR CITY LOADED',len(city['surfaces']),flush=True)
    assert not city.get('geometryRevision') and not city.get('landscape'), 'Repair before release refinements'
    # A retained surface checkpoint may predate a source-topology correction.
    # Refresh its mouths before any overpass/wall is reconstructed, not only
    # during the later landscape audit (which would leave transverse caps).
    _,_,coverage=refresh_connections(city)
    connections_sha=connection_digest(city['gradeConnections'])
    out.mkdir(exist_ok=a.resume_generated)
    if not a.resume_generated:
        for name in ('canonical','textures','library','fence-library'):
            if (base/name).exists():shutil.copytree(base/name,out/name,copy_function=copy_asset)
    terrain=load_terrain(base);dem,tree=terrain
    print('STRUCTURE REPAIR TERRAIN LOADED',len(dem),flush=True)
    product_path=out/'initial-structure-product.pkl'
    if a.resume_generated:
        with product_path.open('rb') as f:product=pickle.load(f)
        assert product['parentCanonicalSha256']==canonical_digest(base/'canonical/urban-model.json')
        assert product.get('connectionsSha256')==connections_sha,'Generated structures use an obsolete walking-mouth inventory; regenerate the product'
        groups,profiles,walls,count=product['groups'],product['profiles'],product['walls'],product['wallCount']
    else:
        rows=[dict(s,poly=sh.geometry.shape(s['geometry']),plane=np.asarray(s['heightPlane']))
              for s in city['surfaces'] if s['kind'].startswith('roadbed')]
        groups=defaultdict(list);extent=sh.box(*city['boundsMSK'])
        print('STRUCTURE REPAIR FLOORS',len(rows),flush=True)
        profiles,_=build_decks(rows,dem,tree,groups,extent,1e-5,triangulate,z_at,plane,city['gradeConnections'])
        assert all(p['passed'] for p in profiles),[(p['sourceParents'],p) for p in profiles if not p['passed']]
        print('STRUCTURE REPAIR DECKS VALIDATED',len(profiles),flush=True)
        count,walls=build_walls(rows,city['features'],dem,tree,groups,extent,1e-5,
                              city['gradeConnections'],city['sourceStyle'],triangulate,z_at,plane)
        assert walls['passed'],walls
        print('STRUCTURE REPAIR WALLS VALIDATED',count,flush=True)
        del rows
        product=dict(parentCanonicalSha256=canonical_digest(base/'canonical/urban-model.json'),
                     connectionsSha256=connections_sha,
                     groups=groups,profiles=profiles,walls=walls,wallCount=count)
        with product_path.open('wb') as f:pickle.dump(product,f,protocol=5)
    print('STRUCTURE REPAIR GENERATED',len(profiles),count,flush=True)
    source_json=base/'canonical/urban-model.json'
    if not source_json.exists():source_json=Path(str(source_json)+'.gz')
    cut,edits,deleted,restored,ground=ground_plan(base,profiles,MemoryDocument(city,source_json),out/'initial-ground-scan.json',
        terrain=terrain,old_profiles=city['overpassProfiles'],allow_unrefined_green=True,allow_initial_curbs=True)
    save(out/'initial-structure-ground.json',ground)
    print('STRUCTURE REPAIR GROUND VALIDATED',ground['restoredGroundM2'],flush=True)
    origin=np.asarray(city['originMSK']);folder=out/'canonical/full';changes=[]
    allowed=STRUCTURES|WALLS
    by_group=defaultdict(list)
    for c in scene['chunks']:
        if c['name'] not in allowed:continue
        raw=gzip.decompress((base/'canonical/full'/Path(c['file']).name).read_bytes())
        words=np.frombuffer(raw[:c['vertexBytes']],'<u4').reshape(-1,8)
        materials=np.unique(words[:,6]&0x7fffffff)
        assert len(materials)==1,('Mixed initial structural chunk',c['id'])
        by_group[(c['name'],int(materials[0]))].append(c)
    assert set(k for k,v in groups.items() if len(v))<=set(by_group), 'New structural category needs explicit chunk allocation'
    for key,chunks in by_group.items():
        faces=np.asarray(groups[key]);assert len(faces)>=len(chunks),(key,'Empty structural batch')
        for c,ts in zip(chunks,np.array_split(faces,len(chunks))):
            changes.append(dict(id=c['id'],name=c['name'],beforeSha256=digest(base/'canonical/full'/Path(c['file']).name)))
            meta=pack(attrs(ts,origin),np.full(len(ts),key[1]),folder/Path(c['file']).name)
            assert meta;c.update(meta)
    curb_faces,curb_side_region=initial_curb_faces(ground,restored,sh.geometry.shape(city['groundRoadGeometry']),dem,tree,sh.box(*city['boundsMSK']))
    changes.extend(apply_ground(base,out,scene,old_scene,origin,cut,restored,
                               curb_faces=curb_faces,curb_side_region=curb_side_region))
    changed={c['id'] for c in changes}
    # Hash every retained canonical asset; source geometry, instancing and
    # attributes may not change as a side effect of structural reconstruction.
    for old,new in zip(old_scene['chunks'],scene['chunks']):
        if old['id'] in changed:continue
        assert old==new
        assert digest(base/'canonical/full'/Path(old['file']).name)==digest(folder/Path(new['file']).name)
    assert old_scene['instances']==scene['instances'] and old_scene['materials']==scene['materials']
    assert digest(base/'canonical/terrain.npz')==digest(out/'canonical/terrain.npz')
    city['surfaces']=[edits.get(s['id'],s) for s in city['surfaces'] if s['id'] not in deleted]+restored
    city['overpassProfiles']=profiles;city['tunnelWalls']=walls
    added_curb=sh.union_all([sh.geometry.shape(s['geometry']) for s in restored if s['kind']=='curb_top'])
    if 'curbBandGeometry' in city:
        band=sh.geometry.shape(city['curbBandGeometry']).difference(cut).union(added_curb)
        city['curbBandGeometry']=sh.geometry.mapping(band)
    for target in (city,report):
        if 'curbs' not in target:continue
        data=target['curbs']
        data['topAreaM2']+=added_curb.area-ground['removedCurbTopAreaM2']
        if 'sideSegments' in data:data['sideSegmentsBeforeInitialRepair']=data.pop('sideSegments')
        data['serializedSideTriangles']=sum(c['triangles'] for c in scene['chunks'] if c['name'] in ('curb_front','curb_back'))
        data['initialRepair']=ground['curbRepair']
    if 'transitionTerrainCutGeometry' in city:
        previous_cut=sh.geometry.shape(city['transitionTerrainCutGeometry'])
        removed_cut=sh.geometry.shape(ground['delta']['removed']['groundContactGeometry'])
        city['transitionTerrainCutGeometry']=sh.geometry.mapping(previous_cut.difference(removed_cut).union(cut))
    proof=dict(version=1,parent=base.name,parentCanonicalSha256=product['parentCanonicalSha256'],
        changedChunks=changes,terrainSha256=digest(out/'canonical/terrain.npz'),
        sourceFloorsPaintObjectsInstancesMaterialsUnchanged=True,ground=ground,
        policy='All confirmed ground approaches participate in height-aware neighbouring structural clearance; original source floors retained.')
    city['initialStructureRepair']=proof;city['rules']['neighbourStructureClearance']=proof['policy']
    save(folder/'scene.json',scene)
    print('STRUCTURE REPAIR CHECKING ALL CANONICAL INTERFACES',flush=True)
    actual=check_interfaces(passage_volumes(city),meshes(out,scene))
    save(out/'initial-structure-interface-audit.json',actual)
    assert actual['passed'],[r for r in actual['checks'] if not r['passed']]
    proof['canonicalInterfaces']=actual;proof['passed']=True
    report['initialStructureRepair']=proof;report['tunnelWalls']=walls
    report['gradeConnections']['interfaceCoverage']=coverage
    report['overpassProfiles']=[{k:v for k,v in p.items() if 'Geometry' not in k and k!='extensionHeightCells'} for p in profiles]
    refresh_stats(scene,report,out);save(folder/'scene.json',scene)
    save_canonical(out/'canonical/urban-model.json',city);save(out/'canonical/validation.json',report)
    save(out/'initial-structure-repair.json',proof)
    print('INITIAL STRUCTURES REPAIRED; FULL PACKED AUDIT STILL REQUIRED',len(changed),flush=True)


if __name__=='__main__':main()
