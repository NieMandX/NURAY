"""Check serialized planting coverage, elevation and unchanged city assets."""
import gzip,hashlib,json,sys
from pathlib import Path
import numpy as np
import shapely as sh
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from green_insets import strip_polygon,protected_ground
from landscape import ground_path,PATH_WIDTHS
from semantics import GREEN
from canonical_store import load_canonical
from street_placement import SurfaceSampler,GROUND_NAMES

def verify_revision(root,city,manifest):
    rev=city['geometryRevision'];parent=root.parent/rev['parent']
    proof=(parent/'validation.json').read_bytes()
    assert hashlib.sha256(proof).hexdigest()==rev['parentValidationSha256'] and json.loads(proof)['passed']
    old=json.loads((parent/'canonical/full/scene.json').read_text());before=load_canonical(parent/'canonical/urban-model.json')
    assert rev['previousRevision']==before['geometryRevision']
    assert old['materials']==manifest['materials'] and old['textures']==manifest['textures']
    assert len(old['chunks'])==len(manifest['chunks'])
    for tex in old['textures']:assert (parent/'textures'/tex).read_bytes()==(root/'textures'/tex).read_bytes()
    assert (parent/'canonical/terrain.npz').read_bytes()==(root/'canonical/terrain.npz').read_bytes()
    changes={r['id']:r for r in rev['changedChunks']};green_mats=set(city['landscape']['materials'].values())
    raised=[];green_vertices=[];walk=[];origin=np.asarray(city['originMSK'])
    for a,b in zip(old['chunks'],manifest['chunks']):
        pa=parent/'canonical/full'/Path(a['file']).name;pb=root/'canonical/full'/Path(b['file']).name
        if a['id'] not in changes:assert a==b and pa.read_bytes()==pb.read_bytes();continue
        change=changes[a['id']];assert hashlib.sha256(pa.read_bytes()).hexdigest()==change['beforeSha256']
        assert a['name']==b['name'] in {'land','pedestrian_path','railway_apron','green_curb_top','green_curb_side'}
        raw=gzip.decompress(pb.read_bytes());u=np.frombuffer(raw[:b['vertexBytes']],'<u4').reshape(-1,8);v=u.view('<f4');ix=np.frombuffer(raw[b['vertexBytes']:],'<u4').reshape(-1,3)
        mids=u[ix[:,0],6]&0x7fffffff;world=v[ix,:3].astype(float)[:,:,[0,2,1]]*[1,-1,1]+origin
        if b['name']=='land' and set(mids)<=green_mats or b['name']=='green_curb_top':
            raised.extend(sh.polygons(world[:,:,:2]));green_vertices.extend(world.reshape(-1,3))
        elif b['name'] in {'land','pedestrian_path','railway_apron'}:
            assert set(mids)=={city['landscape']['railApronMaterial'] if b['name']=='railway_apron' else 7};walk.extend(sh.polygons(world[:,:,:2]))
    assert raised and walk
    actual=sh.union_all(raised);paved=sh.union_all(walk);expected=sh.geometry.shape(city['landscape']['raisedGeometry'])
    missing=expected.difference(actual.buffer(.0001)).area;excess=actual.difference(expected.buffer(.0001)).area
    assert missing<.01 and excess<.01,('Serialized planting footprint',missing,excess)
    overlap=paved.intersection(actual.buffer(-.0001)).area;assert overlap<.01,('Paving overlaps green',overlap)
    owners={f['id']:f for f in before['features']}
    eligible=sh.union_all([sh.geometry.shape(r['geometry']) for r in before['surfaces']
        if r['kind']=='land' and not r.get('landscapeRole') and owners.get(r['owner'],{}).get('layer')=='Pedestrian_quarter'],grid_size=1e-5)
    source=sh.union_all([strip_polygon(owners[i]['coordinates']) for i in rev['recovery']['sourceOwners']],grid_size=1e-5)
    restored=sh.geometry.shape(rev['recovery']['recoveredGeometry'])
    assert all(owners[i]['layer'] in GREEN for i in rev['recovery']['sourceOwners'])
    assert restored.difference(eligible.buffer(.00005)).area<.01
    assert restored.difference(source.buffer(.00005)).area<.01
    assert restored.difference(sh.union_all([actual,paved]).buffer(.0001)).area<.01,'Restored source area has holes'
    previous_green=sh.geometry.shape(before['landscape']['raisedGeometry'])
    assert previous_green.difference(sh.union_all([actual,paved]).buffer(.0001)).area<.01
    corridors=sh.union_all([protected_ground(city)]+[
        sh.LineString(np.asarray(f['coordinates'])[:,:2]).buffer(PATH_WIDTHS[f['layer']]/2,quad_segs=4)
        for f in city['features'] if ground_path(f) and len(f['coordinates'])>1])
    required=restored.difference(corridors)
    erased=required.difference(actual.buffer(.0001)).area
    assert erased<.01,('Explicit source planting still erased',erased)
    assert previous_green.difference(actual.buffer(.0001)).difference(corridors.buffer(.0001)).area<.01
    # Every raised vertex must be 20 cm above the same terrain: 10 cm sidewalk
    # plus 10 cm planting. Nearest-cell fallback is limited to float32 rounding.
    terrain=np.load(root/'canonical/terrain.npz');polys=sh.from_wkb(terrain['polygons']);planes=terrain['planes'];tree=sh.STRtree(polys)
    verts=np.unique(np.asarray(green_vertices),axis=0);pts=sh.points(verts[:,:2]);pairs=tree.query(pts,predicate='covered_by');chosen=np.full(len(verts),-1,dtype=int);chosen[pairs[0]]=pairs[1]
    absent=np.flatnonzero(chosen<0)
    if len(absent):
        near=tree.nearest(pts[absent]);assert np.max(sh.distance(polys[near],pts[absent]))<.0002;chosen[absent]=near
    heights=(np.c_[verts[:,:2],np.ones(len(verts))]*planes[chosen]).sum(1)+.2
    height_error=float(np.max(np.abs(verts[:,2]-heights)));assert height_error<.001,('Green elevation',height_error)
    assert before['objectLayer']['buildings']==city['objectLayer']['buildings']
    for k in before:
        if k not in {'features','surfaces','landscape','geometryRevision','rules','objectLayer','streetLayer'}:assert before[k]==city[k],k
    assert len(before['features'])==len(city['features'])
    for a,b in zip(before['features'],city['features']):
        if a['layer']=='Pedestrian_quarter':
            assert {k:v for k,v in a.items() if k!='semantics'}=={k:v for k,v in b.items() if k!='semantics'}
            assert b['semantics']['rank']==30
        else:assert a==b
    imap={r['id']:r for r in rev['instanceChanges']};assert len(old['instances'])==len(manifest['instances'])
    for a,b in zip(old['instances'],manifest['instances']):
        if a.get('id') not in imap:assert a==b;continue
        r=imap[a['id']];assert a['matrix']==r['before'] and b['matrix']==r['after']
        assert {k:v for k,v in a.items() if k!='matrix'}=={k:v for k,v in b.items() if k!='matrix'}
        delta=np.array(b['matrix'])-a['matrix'];assert np.max(np.abs(np.delete(delta,7)))==0
        assert -.101<=delta[7]<=.101,('Unexpected object lift',a['id'],delta[7])
    ground=SurfaceSampler(root,manifest,GROUND_NAMES)
    for obj in city.get('streetLayer',{}).get('objects',[]):
        if not obj.get('renderInstances'):continue
        x,y,_=obj['sourcePoint'];hit=ground.ground(x-origin[0],origin[1]-y);assert hit==obj['placement']['surface']
        for i in obj['renderInstances']:assert abs(i['matrix'][7]-hit['height'])<1e-8
    return dict(type='green-insets',passed=True,recoveredAreaM2=restored.area,sourceFeatures=rev['recovery']['sourceFeatures'],
        raisedAreaM2=expected.area,newRaisedAreaM2=rev['recovery']['newRaisedAreaM2'],changedChunks=len(changes),
        maxHeightErrorM=height_error,missingGreenM2=missing,erasedSourcePlantingM2=erased,excessGreenM2=excess,pavingOverlapM2=overlap,
        instanceHeightChanges=len(imap),roadsBuildingsModelsAndTexturesUnchanged=True)
