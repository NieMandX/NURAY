"""Repair source-tier paint and continuous bridge profiles in an immutable release."""
import argparse,gzip,hashlib,json,pickle,subprocess,sys,gc,copy
from pathlib import Path
from collections import defaultdict
import numpy as np
import shapely as sh
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from build import triangulate,z_at,plane,MARKING_RULES
from paint_binding import bind,SOURCE_FLOOR
from paint_domain import accepts,Domain,GAP,polygons,paint_projection_mask
from railway_surfaces import confirmed_owners,RAIL_COLOR
from streaming_json import Document
from prepare_road_paint import read,world,write,actual_domain,audit
from object_geometry import pack,export_glb
from prepare_foundations import save,digest,refresh_stats

STRUCTURES={'overpass_bottom','overpass_shoulder','overpass_riser','overpass_side','parapet_top','parapet_side'}
POLICY='Build a common outer bridge contour from height-continuous source floors across drawing tiers; keep physically stacked floors separate.'

def incremental_paint_audit(base,out,old,scene,origin,new_chunks,parent):
    """Inherit containment only when both paint and its actual asphalt agree."""
    assert parent['passed']
    for a in old['chunks']:
        b=scene['chunks'][a['id']]
        if a['name'] not in {'paint','unbound-paint'} and not a['name'].startswith('roadbed'):continue
        pa=base/'canonical/full'/Path(a['file']).name
        pb=out/'canonical/full'/Path(b['file']).name
        if a==b and digest(pa)==digest(pb):continue
        assert a['name'].startswith('roadbed') and a['name']==b['name'],'Previously validated paint changed'
        aw=read(base,a);bw=read(out,b)
        aa=aw[(aw[:,0,6]&0x7fffffff)==0];bb=bw[(bw[:,0,6]&0x7fffffff)==0]
        assert np.array_equal(aa,bb),'Previously validated asphalt changed'
    current=audit(out,{'originMSK':origin},scene,set(new_chunks))
    assert current['passed'],current
    current.update(trianglesChecked=parent['trianglesChecked']+current['trianglesChecked'],
        unsupportedAreaM2=parent['unsupportedAreaM2']+current['unsupportedAreaM2'],
        worstTriangleM2=max(parent['worstTriangleM2'],current['worstTriangleM2']),
        inheritedTriangles=parent['trianglesChecked'],
        inheritedParent=base.name,
        inheritanceEvidence='Parent validation, byte-identical paint and actual asphalt vertex attributes.')
    current['passed']=current['passed'] and current['unsupportedAreaM2']<1e-4
    return current

def attrs(faces,origin):
    t=(np.asarray(faces)-origin)[:,:,[0,2,1]]*[1,1,-1]
    n=np.cross(t[:,1]-t[:,0],t[:,2]-t[:,0]);n/=np.maximum(np.linalg.norm(n,axis=1,keepdims=True),1e-20)
    return np.concatenate([t,np.repeat(n[:,None,:],3,axis=1),t[:,:,[0,2]]],axis=2)

def cells(words,origin):
    result=[]
    for t in world(words,origin):
        p=sh.Polygon(t[:,:2])
        if p.area>1e-10:result.append(dict(poly=p,plane=plane(t)-[0,0,GAP]))
    return result

def restore_paint(base,scene,origin,rows,source):
    source_manifest=json.loads((source/'corrected/manifest.json').read_text())
    support=[s for s in rows if accepts(s) and s['kind']!='roadbed_flat']
    tree=sh.STRtree([s['poly'] for s in support]);physical=actual_domain(base,scene,origin)
    previous=defaultdict(list)
    for c in scene['chunks']:
        if c['name']!='paint':continue
        words=read(base,c)
        for mid in np.unique(words[:,0,6]&0x7fffffff):
            selected=words[(words[:,0,6]&0x7fffffff)==mid]
            previous[int(mid)].extend(cells(selected,origin))
    previous={mid:Domain(cs) for mid,cs in previous.items()}
    result=defaultdict(list);relationships=[];proof=dict(sourceTriangles=0,restoredAreaM2=0.,triangles=0,ambiguousOrUnsupportedAreaM2=0.)
    print('PAINT SUPPORT',len(support),'existing',sum(len(d.cells) for d in previous.values()),flush=True)
    for row in source_manifest['objects']:
        assert row['heightBinding']==SOURCE_FLOOR
        if row['name'] in MARKING_RULES:continue
        mid={'white':3,'yellow':4,'blue':5}[row['materials'][0]]
        data=np.load(source/'corrected'/row['file']);tri=data['triangles'];tier_rows=data['source_tiers']
        for ix,t in enumerate(tri):
            p=sh.Polygon(t[:,:2])
            if p.area<1e-10 or not len(tree.query(p)):continue
            tiers=[int(v) for v in tier_rows[ix] if v!=-32768]
            bindings,unbound=bind(p,plane(t),tiers,support,tree,source_floor=True)
            if not bindings:continue
            proof['sourceTriangles']+=1;proof['ambiguousOrUnsupportedAreaM2']+=unbound.area
            for i,piece in bindings:
                s=support[i];target=s['plane']+np.array([0,0,GAP]);added=0.
                for face in triangulate(piece,target):
                    available=physical.supported(face)
                    if mid in previous:
                        # 0.2 mm prevents duplicate edge slivers from one prior
                        # float32 serialization, without masking real paint.
                        available=available.difference(previous[mid].supported(face).buffer(.0002))
                    for part in polygons(available):
                        if part.area<1e-8 or part.buffer(-.00015).is_empty:continue
                        output=triangulate(part,target);result[mid].extend(output);added+=part.area
                if added:
                    proof['restoredAreaM2']+=added
                    relationships.append(dict(type='paint-on-surface',
                        child=f"legacy:{row['name']}:{int(data['polygon_indices'][ix])}",
                        parent=s['id'],sourceObject=s['owner'],areaM2=added,heightBinding=SOURCE_FLOOR))
        print('PAINT RESTORED',row['name'],round(proof['restoredAreaM2'],3),flush=True)
    proof['triangles']=sum(map(len,result.values()))
    return result,relationships,proof

def main():
    ap=argparse.ArgumentParser()
    for key in ['base','output','source','structures']:ap.add_argument('--'+key,type=Path,required=True)
    ap.add_argument('--resume',action='store_true')
    a=ap.parse_args();assert a.base.parent==a.output.parent
    assert (a.output.exists() and not (a.output/'validation.json').exists()) if a.resume else not a.output.exists()
    assert json.loads((a.base/'validation.json').read_text())['passed']
    doc=Document(a.base/'canonical/urban-model.json');origin=np.asarray(doc.read('originMSK'))
    scene=json.loads((a.base/'canonical/full/scene.json').read_text())
    base_scene=copy.deepcopy(scene)
    report=json.loads((a.base/'canonical/validation.json').read_text())
    folder=a.output/'canonical/full';changes=[];new_chunks=[]
    rail_material=next(i for i,m in enumerate(scene['materials']) if m['color']==RAIL_COLOR)
    def changed(c,reason):
        changes.append(dict(id=c['id'],name=c['name'],reason=reason,beforeSha256=digest(a.base/'canonical/full'/Path(c['file']).name)))
    if a.resume:
        work=json.loads((a.output/'transport-surface-work.json').read_text())
        scene=json.loads((folder/'scene.json').read_text())
        changes=work['changedChunks'];new_chunks=work['newChunks'];rail_faces=work['railFaces']
        restyled=set(work['restyledSurfaceIds']);paint_proof=work['paint'];relationships=work['relationships'];rail_proof=work['railProof']
    else:
        features=[f for f in doc.items('features') if f['layer'] in {'Transport_Roadbed','Railroad_line','Railroad_tunnel_line'}]
        rail_proof=confirmed_owners(features);owners={r['source'] for r in rail_proof}
        rows=[]
        for s in doc.items('surfaces'):
            if not s['kind'].startswith('roadbed'):continue
            rows.append({**s,'poly':sh.geometry.shape(s['geometry']),'plane':np.array(s['heightPlane'])})
        restyled={s['id'] for s in rows if s['owner'] in owners and s['material']==12}
        print('SOURCE FLOORS',len(rows),'RAIL RESTYLE',len(restyled),flush=True)
        a.output.mkdir()
        for name in ['canonical','textures','library','fence-library']:
            if (a.base/name).exists():subprocess.run(['/bin/cp','-cR',str(a.base/name),str(a.output/name)],check=True)
        if (a.base/'street-objects.json').exists():subprocess.run(['/bin/cp','-c',str(a.base/'street-objects.json'),str(a.output/'street-objects.json')],check=True)
        rail_rows=[s for s in rows if s['id'] in restyled];rail_tree=sh.STRtree([s['poly'] for s in rail_rows]);rail_faces=0
        for c in scene['chunks']:
            if not c['name'].startswith('roadbed'):continue
            words=read(a.base,c);mask=np.zeros(len(words),bool)
            for j in np.flatnonzero((words[:,0,6]&0x7fffffff)==12):
                t=world(words[j:j+1],origin)[0];xy=t[:,:2].mean(0)
                for i in rail_tree.query(sh.Point(xy),predicate='covered_by'):
                    s=rail_rows[int(i)]
                    if s['kind']==c['name'] and abs(z_at(s['plane'],xy)-t[:,2].mean())<.003:mask[j]=True;break
            if mask.any():
                changed(c,'rail-material');words[mask,:,6]=np.uint32(0x80000000|rail_material)
                c.update(write(folder/Path(c['file']).name,words));rail_faces+=int(mask.sum())
        save(a.output/'canonical/full/scene.json',scene)
        paint,relationships,paint_proof=restore_paint(a.base,base_scene,origin,rows,a.source)
        identity=[1,0,0,0,0,1,0,0,0,0,1,0]
        for mid,faces in sorted(paint.items()):
            if not faces:continue
            idx=len(scene['chunks']);file=f'mesh-{idx:03d}.bin.gz'
            meta=pack(attrs(faces,origin),np.full(len(faces),mid),folder/file)
            scene['chunks'].append(dict(id=idx,name='paint',category='paint',file=f'/prototype/assets/full/{file}',**meta))
            scene['instances'].append(dict(mesh=idx,matrix=identity));new_chunks.append(idx)
        save(folder/'scene.json',scene)
        save(a.output/'transport-surface-work.json',dict(changedChunks=changes,newChunks=new_chunks,railFaces=rail_faces,restyledSurfaceIds=sorted(restyled),paint=paint_proof,relationships=relationships,railProof=rail_proof))
    removed_collapses=0
    for idx in new_chunks:
        c=scene['chunks'][idx];assert c['name']=='paint'
        packed=read(a.output,c);keep=paint_projection_mask(packed.view('<f4')[:,:,:3])
        if not keep.all():
            removed_collapses+=int((~keep).sum())
            c.update(write(folder/Path(c['file']).name,packed[keep]))
    if removed_collapses:
        paint_proof['collapsedProjectionTriangles']=paint_proof.get('collapsedProjectionTriangles',0)+removed_collapses
        save(folder/'scene.json',scene)
        work=json.loads((a.output/'transport-surface-work.json').read_text())
        work['paint']=paint_proof;save(a.output/'transport-surface-work.json',work)
    # Preserve a reviewable draft before the independent structural rebuild is
    # consumed. Publication happens only after its validation and tile checks.
    if not a.structures.exists():raise FileNotFoundError('Structural producer is still running; draft assets retained for resume')
    with a.structures.open('rb') as f:product=pickle.load(f)
    assert all(p['passed'] for p in product['profiles'])
    by_name=defaultdict(list)
    for (name,mid),faces in product['groups'].items():
        if faces:by_name[name].append((mid,np.asarray(faces)))
    for name,groups in by_name.items():
        targets=[c for c in scene['chunks'] if c['name']==name];assert targets and name in STRUCTURES
        ts=np.concatenate([ts for mid,ts in groups]);mids=np.concatenate([np.full(len(ts),mid) for mid,ts in groups])
        for c,ix in zip(targets,np.array_split(np.arange(len(ts)),len(targets))):
            changed(c,'continuous-bridge-profile');meta=pack(attrs(ts[ix],origin),mids[ix],folder/Path(c['file']).name)
            assert meta;c.update(meta)
    save(folder/'scene.json',scene)
    from transport_ground import plan as ground_plan,apply as apply_ground
    ground_cut,ground_edits,ground_deleted,ground_restored,ground_proof=ground_plan(a.base,product['profiles'],doc,a.output/'transport-ground-scan.json')
    changes.extend(apply_ground(a.base,a.output,scene,base_scene,origin,ground_cut,ground_restored))
    save(folder/'scene.json',scene)
    rail_layer=doc.read('railwayLayer')
    rail_layer['baseRestyle']=dict(applied=True,material=rail_material,color=RAIL_COLOR,confirmedSurfaces=rail_proof,
        policy='Same-tier rail axes confirm a slab component connected through shared edges at the same physical height.')
    from railway_transitions import source_candidates,discover
    from transitions import interface_coverage
    features=[f for f in doc.items('features') if f['layer'] in {'Transport_Roadbed','Railroad_line','Railroad_tunnel_line'}]
    extent=sh.box(*doc.read('boundsMSK'))
    rail_connections,rail_interfaces=discover(source_candidates(features,extent),features,extent,1e-5,z_at)
    connections=[r for r in doc.read('gradeConnections') if r.get('peerKind')!='railway_ground']+rail_connections
    interfaces=[r for r in doc.read('roadInterfaces') if not any(e['kind']=='railway_ground' for e in r['ends'])]+rail_interfaces
    coverage=interface_coverage(interfaces,connections,1e-5);assert coverage['passed']
    from transport_planting import plan as planting_plan,apply as apply_planting
    from prepare_railway_entries import load_terrain
    dem,demtree=load_terrain(a.base)
    landscape,planting_proof,planting_sides=planting_plan(doc,interfaces,dem,demtree)
    planting_changes=apply_planting(a.base,a.output,scene,base_scene,planting_proof,planting_sides,landscape,origin)
    assert not ({c['id'] for c in planting_changes}&{c['id'] for c in changes})
    changes.extend(planting_changes)
    planting_removed=set(planting_proof['removedSurfaceIds'])
    assert not planting_removed.intersection(ground_edits)
    rules=doc.read('rules');rules.update(paintHeightBinding=SOURCE_FLOOR,physicalBridgeSheets=POLICY)
    revision=dict(version=1,type='transport-surfaces',parent=a.base.name,parentValidationSha256=digest(a.base/'validation.json'),
        previousRevision=doc.read('geometryRevision'),changedChunks=changes,newChunks=new_chunks,
        railMaterial=rail_material,restyledSurfaceIds=sorted(restyled),paint=paint_proof,
        sourcePaintManifestSha256=digest(a.source/'corrected/manifest.json'),
        sourcePaintFolder=str(a.source.resolve()),structureProduct=str(a.structures.resolve()),
        structureProductSha256=digest(a.structures),structureRecipeSha256=product['recipeSha256'],
        groundPartition=ground_proof,plantingRepartition=planting_proof)
    validation=incremental_paint_audit(a.base,a.output,base_scene,scene,origin,new_chunks,doc.read('roadPaint')['validation'])
    assert validation['passed'],validation
    road_paint=doc.read('roadPaint');road_paint['validation']=validation;road_paint['tierRestoration']=paint_proof
    report.update(geometryRevision=revision,roadPaint=road_paint,landscape=landscape)
    report['gradeConnections']['interfaceCoverage']=coverage
    report['bridgeGroundPartition']=ground_proof
    if report.get('curbs'):
        report['curbs']['topAreaM2']-=ground_proof['removedCurbTopAreaM2']
        report['curbs']['incrementalGroundClipping']=ground_proof['removedCurbTopAreaM2']
    report['overpassProfiles']=[{k:v for k,v in p.items() if 'Geometry' not in k and k!='extensionHeightCells'} for p in product['profiles']]
    def surface_rows():
        for s in doc.items('surfaces'):
            if s['id'] in ground_deleted or s['id'] in planting_removed:continue
            s=ground_edits.get(s['id'],s)
            if s['id'] in restyled:s.update(material=rail_material,purpose='railway',surfaceType='dark-concrete')
            yield s
        yield from ground_restored
        yield from planting_proof['newSurfaces']
    def relation_rows():
        for r in doc.items('relationships'):
            if any(r.get(key) in ground_deleted for key in ('parent','a','b')):continue
            if r.get('type')=='grade-connection' and r.get('owner','').startswith('railway-connection:'):continue
            yield r
        for c in rail_connections:
            yield dict(type='grade-connection',owner=c['id'],parents=c['sourceParents']+c['peerParents'],evidence=c['evidence'],connectorAreaM2=0.)
        yield from relationships
        for s in ground_restored:
            yield dict(type='exposed-ground-restoration',parent=s['id'],sourceObject=s['owner'],
                       evidence='source-cover-priority-and-retained-terrain')
    doc.rewrite(a.output/'canonical/urban-model.json',dict(geometryRevision=revision,overpassProfiles=product['profiles'],
        railwayLayer=rail_layer,rules=rules,roadPaint=road_paint,gradeConnections=connections,roadInterfaces=interfaces,
        landscape=landscape),
        dict(surfaces=surface_rows,relationships=relation_rows))
    refresh_stats(scene,report,a.output);save(folder/'scene.json',scene)
    export_glb(scene,folder);report['export']['glbBytes']=(folder/'model.glb').stat().st_size
    save(a.output/'canonical/validation.json',report)
    print('TRANSPORT SURFACES PREPARED',a.output,paint_proof,'rail triangles',rail_faces,flush=True)

if __name__=='__main__':main()
