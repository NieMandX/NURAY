"""Append adaptive foundations to an immutable, validated city release."""
import argparse, gzip, hashlib, json, shutil, gc
from pathlib import Path
import numpy as np
import shapely as sh
from adaptive_foundations import install, collect, base_edges, eligible, POLICY, MIN_GAP, BURIAL, panel_triangles
from street_placement import SurfaceSampler, GROUND_NAMES
from object_geometry import export_glb, decode_normals
from canonical_store import load_canonical, save_canonical, copy_asset
from canonical_parent import load_parent


def digest(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def save(p, v): p.write_text(json.dumps(v, ensure_ascii=False, separators=(',', ':')))


def covers_base_probe(panel_tree, position):
    """Measure the existing 0.15 mm coverage tolerance on the actual edges.

    Buffering a union of nearly collinear edges can lose whole line branches
    in GEOS at kilometre coordinates. A spatial-index distance query avoids
    that polygon construction and preserves every original panel segment.
    """
    point=sh.Point(np.asarray(position)[[0,2]])
    return len(panel_tree.query(point,predicate='dwithin',distance=.00015))>0


def rounded_ground_contact(ground, xz, bound, reference=None):
    """Keep the inclusive upper envelope within a proven arithmetic radius.

    Evaluate height ON the actual triangle boundary, never on an extrapolated
    plane. The radius is supplied by the construction of the query point; it
    is unrelated to the geometric coverage tolerance or contact search band.
    """
    hit=ground.ground(*xz)
    if reference and hit and (hit['chunk'],hit['triangle'])==reference:return hit
    point=sh.Point(xz)
    for i in ground.tree.query(point,predicate='dwithin',distance=bound):
        if reference and tuple(ground.refs[i])!=reference:continue
        # Containing triangles already participated in the strict maximum.
        # Only a just-outside boundary can add a previously missed support.
        if hit and sh.covers(ground.polys[i],point):continue
        triangle=ground.tris[i];nearest=None
        for a,b in zip(triangle,np.roll(triangle,-1,axis=0)):
            d=(b-a)[[0,2]];length2=d@d
            t=float(np.clip((xz-a[[0,2]])@d/length2,0,1)) if length2 else 0.
            contact=a+t*(b-a);distance=float(np.linalg.norm(xz-contact[[0,2]]))
            if nearest is None or distance<nearest[0]:nearest=(distance,contact)
        # An inclusive boundary may carry a higher curb above another floor.
        # Decimal rounding can move the probe onto that lower floor, so the
        # strict hit alone is not sufficient. Retain the upper-envelope rule.
        if nearest[0]<=bound and (not hit or nearest[1][1]>hit['height']):
            hit=dict(height=float(nearest[1][1]),chunk=ground.refs[i][0],triangle=ground.refs[i][1],
                     boundaryRoundingM=nearest[0],boundaryRoundingBoundM=float(bound))
    return hit


def foundation_contact(ground, panel, station):
    """Allow only ten-decimal endpoint rounding plus sixteen Float64 ulps.

    Only the panel's declared source face may resolve an ambiguous boundary.
    A genuine void or a different supporting face is never extrapolated.
    """
    bottom=np.asarray(panel['bottom']);offset=np.asarray(panel['groundOffsetM'])
    q=bottom[0]+station*(bottom[1]-bottom[0]);xz=q[[0,2]]+offset
    scale=max(1.,float(np.max(np.abs(bottom[:,[0,2]]))),float(np.max(np.abs(xz))))
    bound=np.sqrt(2.)*(.5e-10+16*np.spacing(scale))
    return rounded_ground_contact(ground,xz,bound,tuple(panel['ground']))


def base_probe_ground(ground, a, b, station):
    """Independent facade probes have Float64 arithmetic error, no grid snap."""
    q=a+(b-a)*station
    scale=max(1.,float(np.max(np.abs(np.array([a,b])[:,[0,2]]))))
    return rounded_ground_contact(ground,q[[0,2]],np.sqrt(2.)*16*np.spacing(scale))


def build(base, out):
    assert base.resolve() != out.resolve() and not out.exists()
    assert json.loads((base/'validation.json').read_text())['passed']
    city = load_canonical(base/'canonical/urban-model.json')
    gc.freeze()
    scene = json.loads((base/'canonical/full/scene.json').read_text())
    report = json.loads((base/'canonical/validation.json').read_text())
    out.mkdir()
    for name in ['canonical', 'textures', 'library']:
        if (base/name).exists(): shutil.copytree(base/name, out/name,copy_function=copy_asset)
    if (base/'street-objects.json').exists(): copy_asset(base/'street-objects.json', out/'street-objects.json')
    layer = install(out, city, scene)
    revision = dict(version=1, type='building-foundations', parent=base.name,
                    parentValidationSha256=digest(base/'validation.json'),
                    previousRevision=city.get('geometryRevision'), newChunks=layer['chunks'])
    city['geometryRevision'] = revision; report['geometryRevision'] = revision
    city['limitations'] = [x for x in city['limitations'] if 'Buildings are rigidly seated' not in x]
    city['limitations'].append('Buildings retain rigid source placement. Adaptive concrete plinths extend only confirmed base-level facade edges to the finished ground; no terrain regrading or inferred walls below elevated arches/canopies.')
    refresh_stats(scene, report, out)
    save(out/'canonical/full/scene.json', scene)
    export_glb(scene, out/'canonical/full')
    report['export']['glbBytes'] = (out/'canonical/full/model.glb').stat().st_size
    report['foundations'] = dict(passed=True, **layer['stats'])
    save_canonical(out/'canonical/urban-model.json',city); save(out/'canonical/validation.json', report)
    print('FOUNDATIONS', json.dumps(layer['stats']), flush=True)


def refresh_stats(scene, report, root):
    scene['stats'].update(uniqueTriangles=sum(c['triangles'] for c in scene['chunks']),
        expandedTriangles=sum(scene['chunks'][i['mesh']]['triangles'] for i in scene['instances']))
    report['export'].update(triangles=scene['stats']['uniqueTriangles'], expandedTriangles=scene['stats']['expandedTriangles'],
        chunks=len(scene['chunks']),downloadBytes=sum((root/'canonical/full'/Path(c['file']).name).stat().st_size for c in scene['chunks']))


def verify_revision(root, city, scene):
    rev = city['geometryRevision']; parent = root.parent/rev['parent']
    assert digest(parent/'validation.json') == rev['parentValidationSha256']
    assert json.loads((parent/'validation.json').read_text())['passed']
    before = load_parent(parent/'canonical/urban-model.json', city,
                         changed_keys=('geometryRevision', 'limitations', 'objectLayer'))
    old = json.loads((parent/'canonical/full/scene.json').read_text())
    assert before['geometryRevision'] == rev['previousRevision']
    def unchanged(c):
        return {**{k:v for k,v in c.items() if k not in {'geometryRevision','limitations'}},
                'objectLayer':{k:v for k,v in c['objectLayer'].items() if k != 'foundations'}}
    assert unchanged(city) == unchanged(before), 'Existing city data changed'
    assert scene['chunks'][:len(old['chunks'])] == old['chunks']
    assert scene['instances'][:len(old['instances'])] == old['instances']
    assert {k:v for k,v in scene.items() if k not in {'chunks','instances','stats'}} == {k:v for k,v in old.items() if k not in {'chunks','instances','stats'}}
    for c in old['chunks']:
        assert (root/'canonical/full'/Path(c['file']).name).read_bytes() == (parent/'canonical/full'/Path(c['file']).name).read_bytes()
    for name in old['textures']:
        assert (root/'textures'/name).read_bytes() == (parent/'textures'/name).read_bytes()
    assert (root/'canonical/terrain.npz').read_bytes() == (parent/'canonical/terrain.npz').read_bytes()
    assert rev['newChunks'] == list(range(len(old['chunks']), len(scene['chunks'])))
    result = verify_foundations(root, city, scene)
    return dict(passed=True,type=rev['type'],buildingsAndTerrainUnchanged=True,**result)


def verify_foundations(root, city, scene):
    layer = city['objectLayer']['foundations']; assert layer['policy'] == POLICY
    ground = SurfaceSampler(root, scene, GROUND_NAMES)
    rows, objects = collect(root, city, scene)
    records = {r['id']:r for r in layer['buildings']}
    max_ground_error = 0.; checks = 0; coverage_checks = 0
    rounded_contacts=0;max_contact_rounding=0.;rounded_base_probes=0
    for index,(oid, ts) in enumerate(objects.items()):
        if index%250==0:print('VERIFY FOUNDATION BUILDINGS',index,'/',len(objects),flush=True)
        base = rows[oid]['placement']['targetBaseM'] - city['originMSK'][2]
        edges = base_edges(np.concatenate(ts), base)
        edge_lines=[sh.LineString([a[[0,2]],b[[0,2]]]) for a,b in edges]
        edge_tree=sh.STRtree(edge_lines)
        panels = records.get(oid, {}).get('panels', [])
        lines = [sh.LineString(np.array(p['top'])[:, [0,2]]) for p in panels]
        coverage = sh.STRtree(lines)
        # Independent dense support probes (not the exporter's breakpoints).
        for a,b in edges:
            length = np.linalg.norm((b-a)[[0,2]])
            for s in np.linspace(0,1,max(3,int(length/.5)+1))[1:-1]:
                p = a+(b-a)*s; hit = base_probe_ground(ground,a,b,s)
                if hit and 'boundaryRoundingM' in hit:rounded_base_probes+=1
                if hit and p[1]-hit['height'] > MIN_GAP+.0001:
                    assert covers_base_probe(coverage,p), ('Unfilled base edge',oid,p)
                    coverage_checks += 1
        for p in panels:
            top, bottom = np.array(p['top']), np.array(p['bottom'])
            assert np.array_equal(top[:,[0,2]],bottom[:,[0,2]])
            # Every upper seam belongs to a true base edge, never an arch or roof.
            found = False
            candidates=edge_tree.query(sh.LineString(top[:,[0,2]]).buffer(.0001))
            for ei in candidates:
                a,b=edges[ei];line=edge_lines[ei]
                if any(line.distance(sh.Point(q[[0,2]]))>.0001 for q in top): continue
                d=b-a; s=((top-a)@d)/(d@d)
                if np.max(np.linalg.norm(a+s[:,None]*d-top,axis=1))<.0001: found=True;break
            assert found, ('Foundation outside source base',oid,top)
            for s in [.1,.5,.9]:
                q=bottom[0]+s*(bottom[1]-bottom[0]);offset=np.array(p['groundOffsetM'])
                assert np.linalg.norm(offset)<=POLICY['contactBandM']+1e-10
                hit=foundation_contact(ground,p,s)
                assert hit, ('Foundation crosses a ground void',oid,q)
                if 'boundaryRoundingM' in hit:
                    rounded_contacts+=1
                    max_contact_rounding=max(max_contact_rounding,hit['boundaryRoundingM'])
                error=abs(q[1]+BURIAL-hit['height']);max_ground_error=max(max_ground_error,error)
                assert error<.0002, ('Foundation misses finished ground',oid,error)
                checks+=1
    # Check the serialized triangles and material, not only the generator log.
    for cid in layer['chunks']:
        chunk=scene['chunks'][cid];assert chunk['category']=='foundation'
        raw=gzip.decompress((root/'canonical/full'/chunk['file']).read_bytes())
        words=np.frombuffer(raw[:chunk['vertexBytes']],'<u4').reshape(-1,8)
        ix=np.frombuffer(raw[chunk['vertexBytes']:],'<u4').reshape(-1,3)
        assert np.all((words[:,6]&0x7fffffff)==POLICY['material'])
        for r in chunk['sourceObjectRanges']:
            row=records[r['id']];assert eligible(rows[r['id']])
            expected=np.concatenate([panel_triangles(p) for p in row['panels']])[:,:,:3].astype('<f4')
            actual=words.view('<f4')[ix[r['first']:r['first']+r['count']],:3]
            assert np.array_equal(expected,actual), ('Serialized foundation differs',r['id'])
        normals=decode_normals(words[:,3])[ix]
        points=words.view('<f4')[ix,:3].astype(float)
        geometric=np.cross(points[:,1]-points[:,0],points[:,2]-points[:,0])
        geometric/=np.linalg.norm(geometric,axis=1,keepdims=True)
        # Very narrow float32 panels may perturb the plane slightly, but
        # normal direction must always agree with the visible face winding.
        assert np.all(np.sum(normals[:,0]*geometric,axis=1)>0)
    assert bool(checks)==bool(layer['stats']['triangles'])
    assert len(records)==layer['stats']['supportedObjects']
    return dict(**layer['stats'],groundProfileChecks=checks,independentCoverageChecks=coverage_checks,
                maxGroundProfileErrorM=max_ground_error,sourceBaseEdgesOnly=True,
                roundedBoundaryContacts=rounded_contacts,maxBoundaryRoundingM=max_contact_rounding,
                roundedBaseProbes=rounded_base_probes)


if __name__ == '__main__':
    p=argparse.ArgumentParser();p.add_argument('--base',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();build(a.base,a.output)
