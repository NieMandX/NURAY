"""Immutable final paint clipping; source features remain available for auditing."""
import argparse,gzip,json,shutil,sys
from pathlib import Path
import numpy as np
import shapely as sh
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from paint_domain import Domain,polygons,accepts,POLICY,GAP,HEIGHT_TOLERANCE,paint_projection_mask
from object_geometry import decode_normals,export_glb
from prepare_foundations import save,digest,refresh_stats
from canonical_store import load_canonical, save_canonical, canonical_digest, copy_asset
from canonical_parent import load_parent
import gc

NAMES={'paint','unbound-paint'}


def read(root,c):
    raw=gzip.decompress((root/'canonical/full'/Path(c['file']).name).read_bytes())
    u=np.frombuffer(raw[:c['vertexBytes']],'<u4').reshape(-1,8)
    ix=np.frombuffer(raw[c['vertexBytes']:],'<u4').reshape(-1,3)
    return u[ix]


def world(words,origin):
    return words.view('<f4')[:,:,:3].astype(float)[:,:,[0,2,1]]*[1,-1,1]+origin


def interpolate(words,xy,origin):
    t=world(words[None],origin)[0];weights=np.column_stack([xy-t[0,:2],np.ones(3)])@np.linalg.inv(np.column_stack([t[:,:2]-t[0,:2],np.ones(3)]))
    result=np.zeros((3,8),dtype='<u4');v=result.view('<f4');old=words.view('<f4')
    v[:,:3]=weights@old[:,:3];v[:,4:6]=weights@old[:,4:6];v[:,7]=weights@old[:,7]
    n=weights@decode_normals(words[:,3]);n/=np.maximum(abs(n).sum(1,keepdims=True),1e-20)
    octxy=n[:,:2].copy();mask=n[:,2]<0;octxy[mask]=(1-abs(octxy[mask,::-1]))*np.where(octxy[mask]>=0,1,-1)
    result[:,3]=np.round(np.clip(octxy,-1,1)*32767).astype('<i2').copy().view('<u4').ravel()
    assert np.all(words[:,6]==words[0,6]);result[:,6]=words[0,6]
    return result


def write(path,triangles):
    verts,ix=np.unique(np.asarray(triangles).reshape(-1,8),axis=0,return_inverse=True);ix=ix.reshape(-1,3).astype('<u4')
    pts=verts.view('<f4')[ix,:3]
    keep=np.linalg.norm(np.cross(pts[:,1]-pts[:,0],pts[:,2]-pts[:,0]),axis=1)>1e-9;ix=ix[keep];assert len(ix)
    with gzip.GzipFile(filename=str(path),mode='wb',mtime=0) as f:f.write(verts.tobytes());f.write(ix.tobytes())
    return dict(vertexBytes=verts.nbytes,vertexCount=len(verts),triangles=len(ix),bounds=dict(min=pts[keep].min((0,1)).tolist(),max=pts[keep].max((0,1)).tolist()))


def clip(root,city,scene):
    ids={c['id'] for c in scene['chunks'] if c['name'] in NAMES}
    identity=[1,0,0,0,0,1,0,0,0,0,1,0]
    assert all(i['matrix']==identity for i in scene['instances'] if i['mesh'] in ids), 'Paint must be in canonical world coordinates'
    origin=np.asarray(city['originMSK']);domain=actual_domain(root,scene,origin);result=[];examples=[]
    assert all(s.get('purpose') in (None,'motor-traffic') for s in city['surfaces'] if s['kind'].startswith('roadbed') and s['material']==0)
    stats=dict(inputTriangles=0,unchangedTriangles=0,clippedTriangles=0,removedTriangles=0,inputAreaM2=0.,removedAreaM2=0.)
    for c in scene['chunks']:
        if c['name'] not in NAMES:continue
        words=read(root,c);xyz=world(words,origin)
        full=domain.fully_supported(xyz)
        for t,w,contained in zip(xyz,words,full):
            p=sh.Polygon(t[:,:2]);stats['inputTriangles']+=1;stats['inputAreaM2']+=p.area
            if stats['inputTriangles']%100000==0:
                print('PAINT CLIP PROGRESS',stats['inputTriangles'],'triangles',flush=True)
            supported=p if contained else domain.supported(t)
            lost=p.difference(supported);area=lost.area
            if area<=1e-10:
                result.append(w);stats['unchangedTriangles']+=1;continue
            stats['removedAreaM2']+=area
            if area>.02:
                center=lost.representative_point();examples.append(dict(areaM2=area,x=center.x,y=center.y,z=float(t[:,2].mean()),chunk=c['id']))
            if supported.area<1e-10:stats['removedTriangles']+=1;continue
            stats['clippedTriangles']+=1
            for poly in polygons(supported):
                for part in sh.get_parts(sh.constrained_delaunay_triangles(poly)):
                    xy=np.asarray(part.exterior.coords)[:3,:2]
                    if np.linalg.det(np.column_stack([xy,np.ones(3)]))<0:xy=xy[::-1]
                    result.append(interpolate(w,xy,origin))
        print('PAINT',c['id'],stats,flush=True)
    stats['outputTriangles']=len(result)
    result=np.asarray(result)
    keep=paint_projection_mask(result.view('<f4')[:,:,:3])
    stats['collapsedProjectionTriangles']=int((~keep).sum())
    result=result[keep];stats['outputTriangles']=len(result)
    return result,dict(**stats,examples=sorted(examples,key=lambda e:-e['areaM2'])[:30])


def actual_domain(root,scene,origin):
    # The final physical floor wins over metadata contours. Both the clipping
    # pass and serialized verification load the actual asphalt mesh.
    cells=[]
    for c in scene['chunks']:
        if not c['name'].startswith('roadbed'):continue
        words=read(root,c);words=words[(words[:,0,6]&0x7fffffff)==0]
        for t in world(words,origin):
            p=sh.Polygon(t[:,:2])
            if p.area<1e-10:continue
            cells.append(dict(poly=p,plane=np.linalg.solve(np.column_stack([t[:,:2],np.ones(3)]),t[:,2])))
    return Domain(cells)


def serialization_xy_tolerance(scene):
    # Clipped paint is rounded once when packed to Float32; its asphalt
    # reference already consists of decoded Float32 vertices. At a 2.5 km
    # offset the XY rounding disk is larger than the old fixed 0.1 mm margin.
    limits=np.zeros(2,dtype=np.float32)
    for c in scene['chunks']:
        if c['name'] not in NAMES:continue
        bounds=c['bounds']
        limits=np.maximum(limits,np.abs(np.asarray([bounds['min'],bounds['max']],dtype=np.float32)[:,[0,2]]).max(0))
    half_ulp=np.abs(np.spacing(limits)).astype(float)/2
    tolerance=max(.0001,float(np.linalg.norm(half_ulp))+1e-8)
    assert np.isfinite(tolerance) and tolerance<=.001, 'Paint coordinate precision exceeds 1 mm; rebase the export'
    return tolerance


def audit(root,city,scene,chunk_ids=None):
    origin=np.asarray(city['originMSK']);domain=actual_domain(root,scene,origin);count=0;area=0.;worst=0.;bad=[]
    # Measured Float32 XY uncertainty, never centimetres that could cover a
    # curb. The 2 mm binding threshold gets a separate 10 micrometre allowance
    # for float32 serialization (observed rounding at cut vertices: <2 um).
    xy_tolerance=serialization_xy_tolerance(scene)
    domain=Domain([dict(c,poly=c['poly'].buffer(xy_tolerance)) for c in domain.cells])
    for c in scene['chunks']:
        if c['name'] not in NAMES:continue
        if chunk_ids is not None and c['id'] not in chunk_ids:continue
        xyz=world(read(root,c),origin)
        full=domain.fully_supported(xyz,tolerance=HEIGHT_TOLERANCE+.00001)
        for t,contained in zip(xyz,full):
            missing=0. if contained else sh.Polygon(t[:,:2]).difference(domain.supported(t,tolerance=HEIGHT_TOLERANCE+.00001)).area
            count+=1;area+=missing;worst=max(worst,missing)
            if missing>1e-7:bad.append(dict(chunk=c['id'],missingM2=missing))
            if count%100000==0:
                print('PAINT AUDIT PROGRESS',count,'triangles; failures',len(bad),flush=True)
        print('PAINT AUDIT',c['id'],count,area,len(bad),flush=True)
    return dict(passed=not bad and area<1e-4,trianglesChecked=count,unsupportedAreaM2=area,
                worstTriangleM2=worst,paintGapM=GAP,heightToleranceM=HEIGHT_TOLERANCE,serializationHeightToleranceM=.00001,
                xyToleranceM=xy_tolerance,maxAllowedXYToleranceM=.001,
                xyPrecisionPolicy='One Float32 rounding disk from actual local paint bounds; 0.1 mm minimum, reject precision worse than 1 mm.',failures=bad[:20])


def supported_bindings(city):
    parents={s['id'] for s in city['surfaces'] if accepts(s)}
    return [r for r in city['relationships'] if r['type']!='paint-on-surface' or r['parent'] in parents]


def finish_metadata(city,report):
    relations=supported_bindings(city)
    city['roadPaint']['excludedBindings']=city['roadPaint'].get('excludedBindings',0)+len(city['relationships'])-len(relations)
    city['relationships']=relations
    report['roadPaint']=city['roadPaint']


def build(base,out):
    assert not out.exists() and base.parent==out.parent
    proof=json.loads((base/'validation.json').read_text());assert proof['passed']
    city=load_canonical(base/'canonical/urban-model.json');scene=json.loads((base/'canonical/full/scene.json').read_text())
    gc.freeze()
    report=json.loads((base/'canonical/validation.json').read_text());faces,diagnostic=clip(base,city,scene)
    out.mkdir()
    for name in ('canonical','textures','library','fence-library'):
        if (base/name).exists():shutil.copytree(base/name,out/name,copy_function=copy_asset)
    if (base/'street-objects.json').exists():copy_asset(base/'street-objects.json',out/'street-objects.json')
    targets=[c for c in scene['chunks'] if c['name'] in NAMES];assert len(faces)>=len(targets);changes=[]
    # Keep chunk IDs and every instance reference stable, including when an old
    # unbound-paint chunk becomes completely empty. Repartition only valid paint.
    for c,ix in zip(targets,np.array_split(np.arange(len(faces)),len(targets))):
        p=out/'canonical/full'/Path(c['file']).name
        changes.append(dict(id=c['id'],name=c['name'],beforeSha256=digest(p)))
        c.update(write(p,faces[ix]));c['name']='paint'
    save(out/'canonical/full/scene.json',scene)
    save(out/'paint-clipping.json',diagnostic)
    finalize(base,out,city,scene,report,diagnostic,changes)


def finalize(base,out,city,scene,report,diagnostic,changes):
    city['rules']['paint']=POLICY
    rev=dict(version=1,type='road-paint',parent=base.name,parentValidationSha256=digest(base/'validation.json'),
             previousRevision=city['geometryRevision'],changedChunks=changes,clipping=diagnostic)
    city['geometryRevision']=rev;report['geometryRevision']=rev
    actual=audit(out,city,scene);assert actual['passed'],actual
    city['roadPaint']=dict(policy=POLICY,clipping=diagnostic,validation=actual)
    finish_metadata(city,report);save(out/'paint-diagnostic.json',city['roadPaint'])
    refresh_stats(scene,report,out);save(out/'canonical/full/scene.json',scene)
    export_glb(scene,out/'canonical/full');report['export']['glbBytes']=(out/'canonical/full/model.glb').stat().st_size
    save_canonical(out/'canonical/urban-model.json',city);save(out/'canonical/validation.json',report)
    print('ROAD PAINT',actual,flush=True)


def resume(base,out):
    # Resume only a prepared, unpublished draft. The ordinary immutable build
    # and final verifier still enforce parent identity and every untouched mesh.
    assert not (out/'validation.json').exists() and base.parent==out.parent
    assert json.loads((base/'validation.json').read_text())['passed']
    assert canonical_digest(out/'canonical/urban-model.json')==canonical_digest(base/'canonical/urban-model.json')
    city=load_canonical(base/'canonical/urban-model.json')
    report=json.loads((base/'canonical/validation.json').read_text())
    old=json.loads((base/'canonical/full/scene.json').read_text())
    scene=json.loads((out/'canonical/full/scene.json').read_text())
    diagnostic=json.loads((out/'paint-clipping.json').read_text())
    changes=[dict(id=c['id'],name=c['name'],beforeSha256=digest(base/'canonical/full'/Path(c['file']).name))
             for c in old['chunks'] if c['name'] in NAMES]
    finalize(base,out,city,scene,report,diagnostic,changes)


def verify_revision(root,city,scene):
    rev=city['geometryRevision'];base=root.parent/rev['parent'];proof=json.loads((base/'validation.json').read_text())
    assert proof['passed'] and digest(base/'validation.json')==rev['parentValidationSha256']
    before=load_parent(base/'canonical/urban-model.json',city,changed_keys=('geometryRevision','roadPaint','rules','relationships'));old=json.loads((base/'canonical/full/scene.json').read_text())
    assert before['geometryRevision']==rev['previousRevision']
    omit={'geometryRevision','roadPaint','rules','relationships'}
    assert {k:v for k,v in city.items() if k not in omit}=={k:v for k,v in before.items() if k not in omit}
    assert city['rules']==dict(before['rules'],paint=POLICY)
    assert city['relationships']==supported_bindings(before)
    assert {k:v for k,v in scene.items() if k not in {'chunks','stats'}}=={k:v for k,v in old.items() if k not in {'chunks','stats'}}
    changes={r['id']:r for r in rev['changedChunks']};assert len(scene['chunks'])==len(old['chunks'])
    for a,b in zip(old['chunks'],scene['chunks']):
        pa=base/'canonical/full'/Path(a['file']).name;pb=root/'canonical/full'/Path(b['file']).name
        if a['id'] in changes:
            assert a['name'] in NAMES and b['name']=='paint' and a['id']==b['id'] and digest(pa)==changes[a['id']]['beforeSha256']
        else:assert a==b and pa.read_bytes()==pb.read_bytes()
    assert digest(base/'canonical/terrain.npz')==digest(root/'canonical/terrain.npz')
    for name in old['textures']:assert digest(base/'textures'/name)==digest(root/'textures'/name)
    # Reproduce from the validated input: catches lost legitimate stripes,
    # altered UV/normals/colors and added marks, in addition to containment.
    expected,stats=clip(base,before,old);assert stats==rev['clipping']
    actual=np.concatenate([read(root,c) for c in scene['chunks'] if c['id'] in changes])
    def sorted_faces(a):
        # pack() can remove sub-float32 degenerates; compare nondegenerate faces.
        p=a.view('<f4')[:,:,:3];a=a[np.linalg.norm(np.cross(p[:,1]-p[:,0],p[:,2]-p[:,0]),axis=1)>1e-9]
        return np.sort(a.reshape(len(a),-1).copy().view(np.dtype((np.void,96))).ravel())
    assert np.array_equal(sorted_faces(expected),sorted_faces(actual))
    validation=audit(root,city,scene);saved=city['roadPaint']['validation']
    assert validation['passed'] and saved['passed'] and validation['trianglesChecked']==saved['trianglesChecked'],validation
    assert abs(validation['unsupportedAreaM2']-saved['unsupportedAreaM2'])<1e-8
    return dict(passed=True,type=rev['type'],clipping=stats,containment=validation,
                roadsBoundariesBuildingsInstancesUnchanged=True,inherited=proof['geometryRevision'])


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--base',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--resume',action='store_true',help='Validate and finish an already prepared unpublished draft')
    a=p.parse_args();(resume if a.resume else build)(a.base,a.output)
