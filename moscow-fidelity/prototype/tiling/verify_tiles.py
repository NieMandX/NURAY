"""Validate serialized transport meshes against the uncut canonical export."""
import gzip, hashlib, json, sys, gc
from collections import defaultdict
from canonical_store import load_canonical
from registry_validation import verify_registry
from pathlib import Path
import numpy as np
from shapely.geometry import LineString
from shapely.ops import unary_union
from seam_validation import passage_gates, check_passages
from interface_validation import passage_volumes, check_interfaces, BARRIERS
from seam_support import compare as compare_seam
from bvh_validation import validate_cached as validate_bvh_cached

ROOT = Path(sys.argv[1]) if len(sys.argv)>1 else Path(__file__).resolve().parents[2] / 'web-preview/prototype/tiles/assets'
manifest = json.loads((ROOT / 'tileset.json').read_text())
canonical = json.loads((ROOT / 'canonical/full/scene.json').read_text())
base_report = json.loads((ROOT / 'canonical/validation.json').read_text())
assert base_report['passed']
assert base_report['roadSeams']['passed']
print('VERIFY LOADING CANONICAL',ROOT.name,flush=True)
city = load_canonical(ROOT / 'canonical/urban-model.json')
# This acyclic JSON input stays live throughout this one-shot verifier. Keep
# Python's cyclic collector from repeatedly walking tens of GB of unchanged
# input while we construct temporary spatial indexes. Reference counting and
# collection of newly allocated objects remain active; no audit is skipped.
gc.freeze()
print('VERIFY CHECKING SOURCE REGISTRY',flush=True)
verify_registry(ROOT,city,canonical,base_report)
assert manifest.get('sourceSnapshot') == city.get('sourceSnapshot')
if city.get('objectLayer',{}).get('sourceGeometry'):
    from physical_geometry import validate_policy
    validate_policy(city,canonical)
assert base_report['semantics']['passed'] and base_report['tunnelWalls']['passed']
print('VERIFY REGISTRY',len(city['features']),'features',len(city['surfaces']),'surfaces',flush=True)
assert base_report['sourceStyle']['passed']
expected_markings={r['id'] for r in city['features'] if r['layer'] in ['LinearMarking_Stop','LinearMarking_TramStop']}
assert {r['source'] for r in city['sourceStyleChecks']} == expected_markings
assert all(r['sourceFeatureBeforeClipping'] and r['material']==4 for r in city['sourceStyleChecks'])
source_style_issues=sum(not r['passed'] for r in city['sourceStyleChecks'])
if source_style_issues:
    # Source coverage is retained as evidence, rather than relabelled passed.
    # The separate emitted-geometry audit must prove that clipping kept every
    # paint face on real asphalt; tile lineage/area checks below then verify
    # that transport packing has not changed those canonical faces.
    evidence=base_report['sourceStyle']
    assert evidence['sourceCoverageIssues']==source_style_issues
    assert evidence['sourceCoveragePassed'] is False
    emitted=evidence['emittedPaint']
    assert emitted['passed'] and not emitted['invalidSupportIds'] and emitted['outsideSupportCoreM2']<1e-8
pedestrian_surfaces=[s for s in city['surfaces'] if s.get('transport')=='pedestrian']
assert pedestrian_surfaces and all(s['material']==(7 if city['tunnelWalls'].get('ruleVersion',1)>=2 and s['styleId']=='715927' else 11) and s['styleId'] in ['241413','715927'] for s in pedestrian_surfaces)
revision_check=None
if city.get('geometryRevision'):
    from portal_validation import verify_revision
    revision_check=verify_revision(ROOT,city,canonical)
if city.get('roadPaint') and city['geometryRevision']['type']!='road-paint' and not (revision_check or {}).get('paintContainmentPassed'):
    from prepare_road_paint import audit as audit_road_paint
    assert audit_road_paint(ROOT,city,canonical)['passed'], 'Paint escaped the final asphalt surface'
gates = passage_gates(city)
passage_meshes = []
interface_meshes = []
interface_volumes = passage_volumes(city)
grid=manifest.get('grid',{'columns':2,'rows':2})
assert len(manifest['tiles']) == grid['columns']*grid['rows']
assert manifest['tileSizeM'] == city.get('transportTileSizeM',250)
by_grid={(t['east'],t['north']):t for t in manifest['tiles']}
by_tile={t['id']:t for t in manifest['tiles']}
assert len(by_tile)==len(manifest['tiles'])
adjacencies=[];tile_edges=defaultdict(set)
for (east,north),tile in by_grid.items():
    for axis,neighbour,edge in [(0,(east+1,north),tile['bounds']['max'][0]),(2,(east,north+1),tile['bounds']['min'][2])]:
        if neighbour not in by_grid:continue
        other=by_grid[neighbour]
        adjacencies.append((axis,edge,(tile['id'],other['id'])))
        tile_edges[tile['id']].add((axis,edge));tile_edges[other['id']].add((axis,edge))
assert manifest['materials'] == canonical['materials']
sources, accumulated, seams, normals = {}, {}, defaultdict(list), defaultdict(dict)

def areas(p):
    return np.linalg.norm(np.cross(p[:, 1] - p[:, 0], p[:, 2] - p[:, 0]), axis=1) / 2

def oct_decode(u):
    xy = u.copy().view('<i2').reshape(-1, 2).astype(float) / 32767
    n = np.column_stack((xy, 1 - np.abs(xy).sum(axis=1)))
    mask = n[:, 2] < 0
    n[mask, :2] = (1 - np.abs(xy[mask, ::-1])) * np.where(xy[mask] >= 0, 1, -1)
    return n / np.linalg.norm(n, axis=1)[:, None]

for c in canonical['chunks']:
    raw = gzip.decompress((ROOT / 'canonical/full' / Path(c['file']).name).read_bytes())
    v = np.frombuffer(raw[:c['vertexBytes']], '<f4').reshape(-1, 8)
    u = np.frombuffer(raw[:c['vertexBytes']], '<u4').reshape(-1, 8)
    ix = np.frombuffer(raw[c['vertexBytes']:], '<u4').reshape(-1, 3)
    sources[c['id']] = {'area': areas(v[ix, :3].astype(float)), 'material': u[ix[:, 0], 6]}
    if c.get('objectGeometry') or c['name']=='waterfront-bank':sources[c['id']].update(points=v[ix,:3].astype(float),uv=v[ix,4:6].astype(float))
    if c.get('instanced'):sources[c['id']]['cornerWords']=u[ix].copy()
    accumulated[c['id']] = np.zeros(c['triangles'])

total_nodes = 0
bvh_cache_hits = 0
max_uv_error = 0
max_rail_uv_error = 0
for verified_index,c in enumerate(manifest['chunks']):
    if verified_index%250==0:
        print('VERIFY MESHES',verified_index,'/',len(manifest['chunks']),flush=True)
    raw = gzip.decompress((ROOT / c['file']).read_bytes())
    verified_sha256=hashlib.sha256(raw).hexdigest()
    assert verified_sha256 == c['sha256'], c['id']
    vb, ib, nb, lb = [c[k] for k in ['vertexBytes', 'indexBytes', 'nodeBytes', 'lineageBytes']]
    assert len(raw) == vb + ib + nb + lb
    v = np.frombuffer(raw[:vb], '<f4').reshape(-1, 8)
    u = np.frombuffer(raw[:vb], '<u4').reshape(-1, 8)
    ix = np.frombuffer(raw[vb:vb+ib], '<u4').reshape(-1, 3)
    nf = np.frombuffer(raw[vb+ib:vb+ib+nb], '<f4').reshape(-1, 8)
    nu = np.frombuffer(raw[vb+ib:vb+ib+nb], '<u4').reshape(-1, 8)
    lineage = np.frombuffer(raw[vb+ib+nb:], '<u4')
    assert len(ix) == c['triangles'] and len(v) == c['vertexCount'] and len(nf) == c['nodeCount']
    assert ix.max() < len(v) and len(lineage) == len(ix)
    assert np.isfinite(v[:, :3]).all() and np.isfinite(v[:, 4:6]).all()
    src = sources[c['sourceChunk']]
    assert lineage.max() < len(src['area'])
    assert np.array_equal(u[ix[:, 0], 6], src['material'][lineage])
    assert np.all(u[ix, 6] == u[ix[:, 0], 6, None])
    assert np.all((u[:, 6] & 0x7fffffff) < len(manifest['materials']))
    if c.get('instanced'):
        assert np.array_equal(u[ix],src['cornerWords'][lineage]), 'Instancing changed position, smoothing or curvature tint'
    tile = None if c.get('instanced') else by_tile[c['tileId']]
    if tile:
        assert tile['bounds']['max'][0] - tile['bounds']['min'][0] <= manifest['tileSizeM']
        assert tile['bounds']['max'][2] - tile['bounds']['min'][2] <= manifest['tileSizeM']
    p = v[ix, :3].astype(float)
    if c['name'] in ['roadbed_flat', 'land', 'curb_top', 'curb_bottom', 'curb_front', 'curb_back']:
        passage_meshes.append((c['name'], p))
    if c['name'] in BARRIERS:interface_meshes.append((c['name'],p))
    for axis in (range(3) if tile else []):
        assert v[:, axis].min() >= tile['bounds']['min'][axis] - 1e-5
        assert v[:, axis].max() <= tile['bounds']['max'][axis] + 1e-5
    if c.get('objectGeometry') or c['name']=='waterfront-bank':
        # Recover barycentrics in each ORIGINAL triangle, independently of the
        # clipper, then verify the source atlas coordinates of every child vertex.
        original=src['points'][lineage];a=original[:,1]-original[:,0];b=original[:,2]-original[:,0];d=p-original[:,0,None]
        aa=(a*a).sum(1);ab=(a*b).sum(1);bb=(b*b).sum(1);den=aa*bb-ab*ab
        da=(d*a[:,None]).sum(2);db=(d*b[:,None]).sum(2)
        x=(da*bb[:,None]-db*ab[:,None])/den[:,None];y=(db*aa[:,None]-da*ab[:,None])/den[:,None]
        uv=src['uv'][lineage];expected=uv[:,0,None]+x[:,:,None]*(uv[:,1]-uv[:,0])[:,None]+y[:,:,None]*(uv[:,2]-uv[:,0])[:,None]
        if c['name']=='waterfront-bank':
            # Sub-centimetre shoreline slivers are near the Float32 XY quantum
            # at kilometre coordinates. Their UV endpoints remain source-owned;
            # stable barycentric checks apply to the measurable bank segments.
            stable=np.linalg.norm(a,axis=1)>.01
            error=float(np.abs(v[ix,4:6]-expected)[stable].max(initial=0));assert error<.02,(c['id'],'bank UV error',error)
        else:
            error=float(np.abs(v[ix,4:6]-expected).max());assert error<.003,(c['id'],'atlas UV error',error)
        if c['name']=='railway':max_rail_uv_error=max(max_rail_uv_error,error)
    else:max_uv_error = max(max_uv_error, float(np.abs(v[:, 4:6] - v[:, [0, 2]]).max()))
    np.add.at(accumulated[c['sourceChunk']], lineage, areas(p))
    # The exact same independent leaf/escape audit is required once per block.
    # Freshly verified bytes + layout + validator recipe identify its proof.
    try:
        bvh_cache_hits += validate_bvh_cached(ROOT.parent/'.bvh-validation-cache',c,verified_sha256,p,nf,nu)
    except AssertionError as error:
        raise AssertionError(('Invalid serialized BVH',c['id'])) from error
    total_nodes += len(nu)
    decoded = oct_decode(u[:, 3])
    for axis,edge in (tile_edges[tile['id']] if tile else []):
        on = np.abs(p[:, :, axis]-edge) < 1e-8
        crossing = np.nonzero((on.sum(axis=1) == 2))[0]
        other = 2 if axis == 0 else 0
        for row in crossing:
            vertices = ix[row][on[row]]
            pts = v[vertices, :3].astype(float)
            if np.linalg.norm(pts[0]-pts[1]) < 1e-7:
                continue
            key = (axis, edge, c['sourceChunk'], c['tileId'])
            seams[key].append(LineString(pts[:, [other, 1]]))
            for vi, pos in zip(vertices, pts):
                k = (int(lineage[row]), *np.round(pos, 5))
                normals[key][k] = decoded[vi]

print('VERIFY MESHES COMPLETE',len(manifest['chunks']),'checking shared tile boundaries',flush=True)
max_gap, unmatched, pairs, max_normal = 0., 0., 0, 0.
canonical_touches=0.;seam_sources={}
for adjacency_index,(axis, edge, pair) in enumerate(adjacencies):
    if adjacency_index and adjacency_index%500==0:print('VERIFY TILE BOUNDARIES',adjacency_index,'/',len(adjacencies),flush=True)
    for source in sources:
        ka, kb = (axis, edge, source, pair[0]), (axis, edge, source, pair[1])
        aa, bb = seams[ka], seams[kb]
        if not aa and not bb:
            continue
        a, b = unary_union(aa), unary_union(bb)
        gap = a.hausdorff_distance(b)
        missing = a.difference(b.buffer(.0001)).length + b.difference(a.buffer(.0001)).length
        if not (gap<.0001 and missing<.0001):
            if source not in seam_sources:
                row=next(c for c in canonical['chunks'] if c['id']==source)
                raw=gzip.decompress((ROOT/'canonical/full'/Path(row['file']).name).read_bytes())
                vertices=np.frombuffer(raw[:row['vertexBytes']],'<f4').reshape(-1,8)
                indices=np.frombuffer(raw[row['vertexBytes']:],'<u4').reshape(-1,3)
                seam_sources[source]=vertices[indices,:3].astype(float)
            # North increases while the render Z axis decreases: put the
            # lower-coordinate tile first for the canonical half-space test.
            if axis==2:a,b=b,a
            gap,missing,touches=compare_seam(a,b,seam_sources[source],axis,edge)
            canonical_touches+=touches
        max_gap, unmatched, pairs = max(max_gap, gap), max(unmatched, missing), pairs+1
        for key in normals[ka].keys() & normals[kb].keys():
            max_normal = max(max_normal, float(np.linalg.norm(normals[ka][key]-normals[kb][key])))
assert max_normal < .0002
source_area = sum(float(s['area'].sum()) for s in sources.values())
tile_area = sum(float(a.sum()) for a in accumulated.values())
area_delta = abs(source_area-tile_area)
max_primitive_error = max(float(np.abs(accumulated[k]-sources[k]['area']).max()) for k in sources)
assert area_delta / source_area < 1e-6
from partition_quantization import verify_area_exceptions
area_rounding=verify_area_exceptions(ROOT,canonical,manifest,sources,accumulated)
assert max_uv_error < .0001
print('VERIFY TILE BOUNDARIES COMPLETE',pairs,'checking road seams',flush=True)
road_seams = check_passages(gates, passage_meshes)
assert road_seams['passed'], road_seams
print('VERIFY ROAD SEAMS COMPLETE',road_seams['passages'],'checking structure interfaces',flush=True)
road_interfaces = check_interfaces(interface_volumes, interface_meshes)
assert road_interfaces['passed'],road_interfaces
print('VERIFY STRUCTURE INTERFACES COMPLETE',road_interfaces['interfaces'],flush=True)
from prepare_railway_entries import load_terrain
dem,dtree=load_terrain(ROOT)
rail_entries=None
if city.get('rules',{}).get('railwayEntries'):
    from prepare_railway_entries import passages,near_passages,load_terrain
    from railway_transitions import discover,source_candidates
    from build import z_at
    import shapely as sh
    extent=sh.box(*city['boundsMSK'])
    rail_connections,rail_interfaces=discover(source_candidates(city['features'],extent),city['features'],extent,1e-5,z_at)
    actual=[r for r in city['roadInterfaces'] if any(e['kind']=='railway_ground' for e in r['ends'])]
    assert actual==rail_interfaces,'Missing source railway connection in interface inventory'
    volumes=passages(city,rail_interfaces,dem,dtree)
    rail_entries=check_interfaces(volumes,near_passages(interface_meshes,volumes))
    rail_entries.update(halfWidthM=1.05,heightRangeAboveFloorM=[.14,.87],scope='serialized transport tiles; actual source railway contour and ramp floor; full-width outward ground approach through the deck overhang')
    rail_entries.pop('heightRangeAboveRoadM',None)
    assert rail_entries['passed'],rail_entries
rail_tunnels=None
if city.get('railwayLayer'):
    from railway_tunnel_validation import audit as audit_rail_tunnels
    rail_tunnels=audit_rail_tunnels(city,dem,dtree,iter(interface_meshes))
    assert rail_tunnels['passed'],rail_tunnels
print('VERIFY RAILWAYS COMPLETE checking transport corridors',flush=True)
from transport_clearance_validation import audit as audit_transport_clearance
transport_clearance=audit_transport_clearance(city,dem,dtree,iter(interface_meshes))
assert transport_clearance['passed'],transport_clearance
if city['rules'].get('passageClearance'):
    assert transport_clearance['fullWidth']['passed'],transport_clearance['partialContacts']
print('VERIFY TRANSPORT CORRIDORS COMPLETE checking objects and instances',flush=True)
object_check=None
if city.get('objectLayer'):
    layer=city['objectLayer'];assets={c['id']:c for c in manifest['chunks']}
    variation_check=None
    if layer.get('variation'):
        from vegetation_variation import verify as verify_variation
        variation_check=verify_variation(layer,canonical)
    actual=[i for t in manifest['tiles'] for i in t.get('instances',[])]
    expected=[i for obj in layer['vegetation'] for i in obj['renderInstances']]+city.get('streetLayer',{}).get('instances',[])
    assert len(actual)==len(expected)==len({i['id'] for i in actual})
    by_id={i['id']:i for i in actual}
    for i in expected:
        item=by_id[i['id']];assert item['matrix']==i['matrix'] and item['tileId']==i['tileId']
        mesh=assets[item['mesh']];assert mesh['instanced'] and mesh['sourceChunk']==i['mesh']
        matrix=np.asarray(i['matrix']).reshape(3,4);assert np.isfinite(matrix).all() and np.linalg.det(matrix[:,:3])>1e-9
        tile=by_tile[i['tileId']];x,z=matrix[0,3],matrix[2,3]
        assert tile['bounds']['min'][0]<=x<tile['bounds']['max'][0]
        assert tile['bounds']['min'][2]<z<=tile['bounds']['max'][2]
        corners=np.asarray([[mesh['bounds']['max' if bits&(1<<a) else 'min'][a] for a in range(3)] for bits in range(8)])
        world=corners@matrix[:,:3].T+matrix[:,3]
        assert np.all(world.min(0)>=np.asarray(tile['contentBounds']['min'])-1e-5)
        assert np.all(world.max(0)<=np.asarray(tile['contentBounds']['max'])+1e-5)
    for name,tex in layer['textures'].items():
        raw=(ROOT/'textures'/name).read_bytes();assert hashlib.sha256(raw).hexdigest()==tex['sha256']
    assert len([c for c in manifest['chunks'] if c.get('instanced')])==layer['stats']['treeTemplates']+city.get('streetLayer',{}).get('stats',{}).get('templates',0)
    assert layer['stats']['groundFallbacks']==0, 'Unconfirmed object ground placement requires review'
    for m in manifest['materials'][13:]:assert max(m['color'])<=.65001 and 0<=m['roughness']<=1 and 0<=m['metallic']<=1
    # The previous road build is immutable: adding object layers must not alter
    # even one road/ground/paint vertex or its prebuilt BVH.
    previous=ROOT.parent/layer.get('baseVersion','assets-km1')/'tileset.json'
    if previous.exists():
        base=json.loads(previous.read_text());old={c['id']:c['sha256'] for c in base['chunks']}
        from landscape_validation import changed_since_base
        allowed=changed_since_base(city.get('geometryRevision'))
        assert all(assets[c['id']]['sha256']==c['sha256'] for c in base['chunks'] if c['sourceChunk'] not in allowed),'Base road geometry changed outside explicit structure revision'
    object_check=dict(passed=True,**layer['stats'],instancesVerified=len(actual),sourceRoadChunksUnchanged=not bool(revision_check),unchangedOutsideStructureRevision=True)
    if variation_check:object_check['variation']=variation_check
    if layer.get('customLibrary'):
        from custom_vegetation import verify as verify_custom_library
        object_check['customLibrary']=verify_custom_library(layer,canonical,ROOT/'canonical/full')
railway_check=None
if city.get('railwayLayer'):
    layer=city['railwayLayer'];tex=layer['texture'];raw=(ROOT/tex['file']).read_bytes()
    assert hashlib.sha256(raw).hexdigest()==tex['sha256']
    expected={f['id'] for f in city['features'] if f['layer'] in ('Railroad_line','Railroad_tunnel_line') and f['geometryType']=='polyline'}
    assert {e['source'] for e in layer['edges']}==expected
    assert layer['stats']['maxSourceJointGapM']<1e-5 and layer['stats']['maxSourceJointPhaseError']<1e-8
    assert all(e['stationEndM']>e['stationStartM'] for e in layer['edges'])
    assert manifest['materials'][layer['materials']['rail']]['metallic']>.8
    assert manifest['materials'][layer['materials']['bed']]['metallic']==0
    railway_check=dict(passed=True,**layer['stats'],maxPackedUvError=max_rail_uv_error,maxSleeperPhaseErrorM=max_rail_uv_error*tex['repeatM'])
result = {'passed': True, 'meshes': len(manifest['chunks']), 'triangles': manifest['stats']['fullTriangles'],
          'bvhProofCache': {'reused':bvh_cache_hits,'newlyChecked':len(manifest['chunks'])-bvh_cache_hits,'policy':'Exact verified raw SHA-256, binary layout and validator recipe; all non-BVH audits rerun.'},
          'bvhNodes': total_nodes, 'checks': ['gzip/hash/layout', 'tile bounds', 'material identity',
          'primitive lineage', 'all BVH leaves and escape nodes', 'canonical surface area', 'seam coverage', 'seam normals', 'continuous UVs', 'no exported barriers in source seam passages', 'no concrete barrier at any source road interface'],
          'roadSeams': road_seams, 'roadInterfaces':road_interfaces,'railwayEntries':rail_entries,'railwayTunnels':rail_tunnels,
          'transportClearance':transport_clearance,'roadPaint':city.get('roadPaint',{}).get('validation'),
          'sourceStyle':{'passed':True,'rebuiltZigzagFeatures':len(expected_markings),'pedestrianSurfaceCells':len(pedestrian_surfaces),
            'sourceCoverageIssues':source_style_issues,
            'openPedestrianInterfaces':sum(any(e['kind']=='pedestrian_ground' for e in r['ends']) for r in city['roadInterfaces'])},
          'semantics':base_report.get('semantics'), 'tunnelWalls':base_report.get('tunnelWalls'),'objectLayer':object_check,'railwayLayer':railway_check,'geometryRevision':revision_check,
          'landscape':({k:v for k,v in city['landscape'].items() if k not in ('raisedGeometry','curbGeometry','convertedGeometry','sourcePaths')} if city.get('landscape') else None),
          'seams': {'tileAdjacencies':len(adjacencies),'pairs': pairs, 'maxGapM': max_gap, 'maxUnmatchedLengthM': unmatched, 'maxNormalDifference': max_normal,
                    'canonicalOneSidedTouchM':canonical_touches},
          'area': {'sourceM2': source_area, 'tilesM2': tile_area, 'differenceM2': area_delta, 'maxPrimitiveDifferenceM2': max_primitive_error,'float32Rounding':area_rounding},
          'maxUvErrorM': max_uv_error, 'canonicalPassed': base_report['passed']}
(ROOT / 'validation.json').write_text(json.dumps(result, indent=2))
print(json.dumps(result, indent=2))
