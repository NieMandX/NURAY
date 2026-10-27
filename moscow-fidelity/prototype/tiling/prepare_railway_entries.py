"""Rebuild bridge profiles from source-confirmed railway continuations."""
import argparse,gzip,json,shutil,sys
from collections import defaultdict
from pathlib import Path
import numpy as np
import shapely as sh
from shapely.ops import substring
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from build import triangulate,z_at,plane
from overpasses import build as decks,CONCRETE,OVERHANG
from railway_transitions import discover,source_candidates,POLICY,TRACK_OFFSET
from transitions import interface_coverage
from object_geometry import pack,export_glb
from prepare_foundations import save,digest,refresh_stats
from interface_validation import check_interfaces,BARRIERS

STRUCTURES={'overpass_bottom','overpass_riser','overpass_shoulder','overpass_side','parapet_side','parapet_top'}


def load_terrain(root):
    c=np.load(root/'canonical/terrain.npz');dem=list(zip(sh.from_wkb(c['polygons']),c['planes']))
    return dem,sh.STRtree([p for p,c in dem])


def passages(city,interfaces,dem,tree):
    """Audit source-shaped ramps and the full-width outward ground approach.

    A constant-width rectangle includes legitimate shoulders where a railway
    curves or narrows. Its inside also needs the actual ramp height, not the
    terrain height. Source slabs define the corridor independently of concrete;
    canonical floor planes only supply its elevation.
    """
    from passage_space import ground_approach
    from railway_tunnel_validation import volume_cells
    from transitions import union
    features={f['id']:f for f in city['features']}
    wanted={p for r in interfaces for e in r['ends'] if e['kind']!='railway_ground' for p in e['parents']}
    floors=defaultdict(list)
    for s in city['surfaces']:
        if s.get('owner') in wanted and s['kind'].startswith('roadbed'):
            floors[s['owner']].append((s,sh.geometry.shape(s['geometry'])))
    result=[]
    for interface in interfaces:
        line=sh.geometry.shape(interface['mouthGeometry']);inner=substring(line,.05,line.length-.05)
        end=next(e for e in interface['ends'] if e['kind']!='railway_ground')
        patches=[]
        for owner in end['parents']:
            xyz=np.asarray(features[owner]['coordinates'])
            for i in range(len(xyz)-2):
                p=sh.Polygon(xyz[i:i+3,:2])
                if p.area>1e-8:patches.append(p)
        source=union(patches,1e-5)
        assert not source.is_empty,('Missing source railway slab',interface['id'])
        approach=ground_approach(line,source)
        gate=inner.buffer(OVERHANG+.05,cap_style='flat').intersection(source.union(approach).buffer(-.05))
        cells=[];covered=[]
        for owner in end['parents']:
            for s,p in floors[owner]:
                if s['kind']!=end['kind'] or s['tiers']!=end['level']:continue
                piece=gate.intersection(source).intersection(p)
                cells.extend(volume_cells(piece,s['heightPlane'],city['originMSK']))
                covered.append(piece)
        outside=gate.difference(source)
        for i in tree.query(outside,predicate='intersects'):
            p,c=dem[int(i)];piece=outside.intersection(p)
            cells.extend(volume_cells(piece,c,city['originMSK']));covered.append(piece)
        missing=gate.difference(sh.union_all(covered).buffer(.00005)).area
        assert cells and missing<.001,('Missing railway entry floor witness',interface['id'],missing)
        result.append((interface,cells))
    return result


def near_passages(meshes,volumes):
    bounds=[sh.union_all([g for g,p in cells]).bounds for i,cells in volumes]
    tree=sh.STRtree([sh.box(*b) for b in bounds])
    for name,ts in meshes:
        lo=ts[:,:,[0,2]].min(1);hi=ts[:,:,[0,2]].max(1)
        keep=np.zeros(len(ts),bool)
        # STRtree's envelope query is the same inclusive AABB broadphase as
        # the original per-gate loop. No geometric predicate: vertical faces
        # can have zero-area XZ envelopes and must remain candidates.
        pairs=tree.query(sh.box(lo[:,0],lo[:,1],hi[:,0],hi[:,1]))
        if pairs.shape[1]:keep[np.unique(pairs[0])]=True
        if keep.any():yield name,ts[keep]


def meshes(root,scene):
    for c in scene['chunks']:
        if c['name'] not in BARRIERS:continue
        raw=gzip.decompress((root/'canonical/full'/Path(c['file']).name).read_bytes())
        v=np.frombuffer(raw[:c['vertexBytes']],'<f4').reshape(-1,8)
        ix=np.frombuffer(raw[c['vertexBytes']:],'<u4').reshape(-1,3)
        yield c['name'],v[ix,:3].astype(float)


def audit(root,scene,city,interfaces,dem,tree):
    volumes=passages(city,interfaces,dem,tree)
    result=check_interfaces(volumes,near_passages(meshes(root,scene),volumes))
    result.update(halfWidthM=OVERHANG+.05,heightRangeAboveFloorM=[round(TRACK_OFFSET+.02,8),round(TRACK_OFFSET+.75,8)],
        scope='serialized faces across the source-shaped railway ramp and full-width outward ground approach; actual floor datum')
    result.pop('heightRangeAboveRoadM',None)
    return result


def build(base,out):
    assert not out.exists() and base.parent==out.parent
    assert json.loads((base/'validation.json').read_text())['passed']
    city=json.loads((base/'canonical/urban-model.json').read_text());scene=json.loads((base/'canonical/full/scene.json').read_text())
    report=json.loads((base/'canonical/validation.json').read_text());extent=sh.box(*city['boundsMSK'])
    cs,ifs=discover(source_candidates(city['features'],extent),city['features'],extent,1e-5,z_at)
    known={c.get('interfaceId') for c in city['gradeConnections']};assert not any(c['interfaceId'] in known for c in cs)
    assert cs,'No source-confirmed railway entries'
    dem,tree=load_terrain(base)
    print('SOURCE RAILWAY MOUTHS',len(cs),flush=True)
    before=audit(base,scene,city,ifs,dem,tree)
    print('BEFORE PASSAGES',json.dumps(before),flush=True)
    city['gradeConnections'].extend(cs);city['roadInterfaces'].extend(ifs)
    rows=[{**s,'poly':sh.geometry.shape(s['geometry']),'plane':np.asarray(s['heightPlane'])}
          for s in city['surfaces'] if s['kind']=='roadbed_overpass' and s.get('transport','vehicle')=='vehicle']
    groups=defaultdict(list)
    profiles,_=decks(rows,dem,tree,groups,extent,1e-5,triangulate,z_at,plane,city['gradeConnections'])
    assert all(p['passed'] for p in profiles),[(p['level'],p['passed']) for p in profiles]
    city['overpassProfiles']=[p for p in city['overpassProfiles'] if p['transport']!='vehicle']+profiles
    out.mkdir()
    for name in ['canonical','textures','library','fence-library']:
        if (base/name).exists():shutil.copytree(base/name,out/name)
    if (base/'street-objects.json').exists():shutil.copy2(base/'street-objects.json',out/'street-objects.json')
    changed=[];origin=np.array(city['originMSK'])
    for name in sorted(STRUCTURES):
        selected=[]
        for c in scene['chunks']:
            if c['name']!=name:continue
            data=gzip.decompress((base/'canonical/full'/Path(c['file']).name).read_bytes())
            u=np.frombuffer(data[:c['vertexBytes']],'<u4').reshape(-1,8)
            if np.all((u[:,6]&0x7fffffff)==CONCRETE):selected.append(c)
        assert selected
        for c,faces in zip(selected,np.array_split(np.asarray(groups[(name,CONCRETE)]),len(selected))):
            xyz=(faces-origin)[:,:,[0,2,1]]*[1,1,-1]
            n=np.cross(xyz[:,1]-xyz[:,0],xyz[:,2]-xyz[:,0]);size=np.linalg.norm(n,axis=1);keep=size>1e-9
            xyz=xyz[keep];n=n[keep]/size[keep,None]
            t=np.concatenate([xyz,np.repeat(n[:,None,:],3,axis=1),xyz[:,:,[0,2]]],axis=2)
            meta=pack(t,np.full(len(t),CONCRETE),out/'canonical/full'/Path(c['file']).name);assert meta
            c.update(meta);changed.append(c['id'])
    coverage=interface_coverage(city['roadInterfaces'],city['gradeConnections'],1e-5);assert coverage['passed']
    after=audit(out,scene,city,ifs,dem,tree)
    print('AFTER PASSAGES',json.dumps(after),flush=True);assert after['passed']
    city['rules']['railwayEntries']=POLICY
    for c in cs:city['relationships'].append(dict(type='grade-connection',owner=c['id'],parents=c['sourceParents']+c['peerParents'],evidence=c['evidence'],connectorAreaM2=0.))
    revision=dict(version=1,type='railway-entries',parent=base.name,parentValidationSha256=digest(base/'validation.json'),
        previousRevision=city['geometryRevision'],changedChunks=changed,interfaces=ifs,connections=cs,
        beforePassages=before,afterPassages=after)
    city['geometryRevision']=revision;report['geometryRevision']=revision
    report['overpassProfiles']=[{k:v for k,v in p.items() if 'Geometry' not in k and k!='extensionHeightCells'} for p in city['overpassProfiles']]
    report['gradeConnections']['interfaceCoverage']=coverage
    report['railwayEntries']=dict(passed=True,sourceMouths=len(cs),freePassages=after,policy=POLICY)
    refresh_stats(scene,report,out);save(out/'canonical/full/scene.json',scene)
    export_glb(scene,out/'canonical/full');report['export']['glbBytes']=(out/'canonical/full/model.glb').stat().st_size
    save(out/'canonical/urban-model.json',city);save(out/'canonical/validation.json',report)
    print('RAIL ENTRY VERSION',out,flush=True)


def verify_revision(root,city,scene):
    rev=city['geometryRevision'];base=root.parent/rev['parent'];proof=json.loads((base/'validation.json').read_text())
    assert proof['passed'] and digest(base/'validation.json')==rev['parentValidationSha256']
    old=json.loads((base/'canonical/full/scene.json').read_text());before=json.loads((base/'canonical/urban-model.json').read_text())
    assert rev['previousRevision']==before['geometryRevision']
    scope={'geometryRevision','overpassProfiles','gradeConnections','roadInterfaces','relationships','rules'}
    assert {k:v for k,v in city.items() if k not in scope}=={k:v for k,v in before.items() if k not in scope}
    assert {k:v for k,v in scene.items() if k not in {'chunks','stats'}}=={k:v for k,v in old.items() if k not in {'chunks','stats'}}
    assert len(scene['chunks'])==len(old['chunks'])
    for a,b in zip(old['chunks'],scene['chunks']):
        if a['id'] in rev['changedChunks']:
            assert a['name']==b['name'] and a['name'] in STRUCTURES
        else:
            assert a==b
            assert (base/'canonical/full'/Path(a['file']).name).read_bytes()==(root/'canonical/full'/Path(b['file']).name).read_bytes()
    assert digest(base/'canonical/terrain.npz')==digest(root/'canonical/terrain.npz')
    for n in old['textures']:assert digest(base/'textures'/n)==digest(root/'textures'/n)
    extent=sh.box(*city['boundsMSK']);cs,ifs=discover(source_candidates(city['features'],extent),city['features'],extent,1e-5,z_at)
    assert cs==rev['connections'] and ifs==rev['interfaces']
    assert city['gradeConnections']==before['gradeConnections']+cs
    assert city['roadInterfaces']==before['roadInterfaces']+ifs
    assert city['rules']==dict(before['rules'],railwayEntries=POLICY)
    coverage=interface_coverage(city['roadInterfaces'],city['gradeConnections'],1e-5);assert coverage['passed']
    # Profiles outside the affected mouths retain their physical boundaries.
    # Re-noding a long precision-grid contour can leave micrometre-wide slivers
    # whose accumulated area exceeds a fixed area epsilon. Bound their width
    # instead; this also permits removed, degenerate old contour fragments.
    zone=sh.union_all([sh.geometry.shape(i['mouthGeometry']).buffer(OVERHANG*3) for i in ifs])
    contour_noise=0.;contour_tolerance=.00005
    for a in before['overpassProfiles']:
        b=next(p for p in city['overpassProfiles'] if p['level']==a['level'] and p['transport']==a['transport'])
        assert b['passed']
        for key in ['asphaltGeometry','deckGeometry','parapetGeometry','shoulderGeometry']:
            x=sh.geometry.shape(a[key]);y=sh.geometry.shape(b[key])
            delta=x.symmetric_difference(y).difference(zone)
            assert delta.buffer(-contour_tolerance).is_empty,(key,a['level'],delta.area)
            contour_noise+=delta.area
    dem,tree=load_terrain(root);actual=audit(root,scene,city,ifs,dem,tree)
    assert actual['passed'],actual
    assert rev['afterPassages']==actual
    return dict(passed=True,type=rev['type'],sourceMouths=len(ifs),fullWidthPassages=actual,
        roadRailUvTerrainObjectsUnchanged=True,changedStructuralChunks=len(rev['changedChunks']),
        contourRoundingAreaM2=contour_noise,contourRoundingHalfWidthToleranceM=contour_tolerance,
        inherited=proof['geometryRevision'])


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--base',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();build(a.base,a.output)
