"""Append a replaceable street library to an immutable canonical city release."""
import argparse, collections, gzip, hashlib, json, math, shutil
from pathlib import Path
import numpy as np
import shapely as sh
from street_library import model, Mesh, MATERIALS
from street_placement import model_rule,evaluate,transform,owner,SurfaceSampler,GROUND_NAMES
from object_geometry import pack,export_glb,clip_triangles
from fence_geometry import build as build_fences, EXTRA_MATERIALS, POLICY as FENCE_POLICY
from canonical_store import load_canonical, save_canonical, copy_asset

def write(path,value):path.write_text(json.dumps(value,ensure_ascii=False,separators=(',',':')))
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
IDENTITY=[1,0,0,0,0,1,0,0,0,0,1,0]

def build(base,output,evidence,inventory):
    assert base.parent==output.parent and not output.exists()
    city=load_canonical(base/'canonical/urban-model.json');manifest=json.loads((base/'canonical/full/scene.json').read_text())
    report=json.loads((base/'canonical/validation.json').read_text());assert report['passed'] and json.loads((base/'validation.json').read_text())['passed']
    source=json.loads(gzip.decompress(evidence.read_bytes()));catalog=json.loads(inventory.read_text())
    records=source['records'];assert not any(r['layer']=='Traffic_light' for r in records)
    ox,oy,oz=city['originMSK'];bounds=city['boundsMSK'];size=city.get('transportTileSizeM',250)
    ground=SurfaceSampler(base,manifest,GROUND_NAMES);deck=SurfaceSampler(base,manifest,{'overpass_bottom'})
    output.mkdir()
    for name in ['canonical','textures','library']:
        if (base/name).exists():shutil.copytree(base/name,output/name,copy_function=copy_asset)
    folder=output/'canonical/full';matbase=len(manifest['materials']);manifest['materials'].extend(MATERIALS+EXTRA_MATERIALS)
    library={};objects=[];deferred=[];instances=[];account=[];dedup={};supports=Mesh()
    reference_models={str(x.get('sourceBuildingId')) for x in city['objectLayer']['buildings'] if x['category']=='landmark'}
    vegetation_layers={x['layer'] for x in city['objectLayer']['vegetation']}
    def local(p):return [p[0]-ox,oy-p[1]]
    def defer(r,reason):deferred.append(dict(sourceRecordId=r['sourceRecordId'],layer=r['layer'],reason=reason));account.append(dict(sourceRecordId=r['sourceRecordId'],status='deferred',reason=reason))
    def append_mesh(name,mesh,instanced):
        tris,mats=mesh.arrays()
        if not instanced:tris,mats=clip_triangles(tris,mats,[bounds[0]-ox,oy-bounds[3],bounds[2]-ox,oy-bounds[1]])
        idx=len(manifest['chunks']);filename=f'mesh-{idx:03d}.bin.gz';meta=pack(tris,mats+matbase,folder/filename)
        assert meta
        chunk=dict(id=idx,name=name,category='street',file=filename,streetGeometry=True,objectGeometry=True,**meta)
        if instanced:chunk['instanced']=True
        manifest['chunks'].append(chunk)
        if not instanced:manifest['instances'].append(dict(mesh=idx,matrix=IDENTITY))
        return idx
    def template(name):
        if name not in library:
            idx=append_mesh('street-'+name,model(name),True);c=manifest['chunks'][idx]
            from street_library import TEMPLATE_YAW
            library[name]=dict(mesh=idx,displayBounds=c['bounds'],triangles=c['triangles'],dimensions='NURAY display defaults in metres; not surveyed dimensions',templateYawDegrees=TEMPLATE_YAW.get(name,0))
        return library[name]['mesh']
    for r in records:
        layer=r['layer'];p=r['properties'];rid=r['sourceRecordId']
        if layer.startswith('Model_tree_'):
            if layer in vegetation_layers:
                account.append(dict(sourceRecordId=rid,status='existing-vegetation'))
            else:
                defer(r,'source vegetation class has no approved library mapping; retained in source archive')
            continue
        if layer in ('Fence','Road_support_column','Road_support_crossbar'):continue
        rule=model_rule(r,catalog['sourceRulesByLayer'].get(layer,[]))
        if not rule:
            defer(r,'no supported physical model rule in retained source (icons are not geometry)');continue
        if str(r['source'].get('providerObjectId')) in reference_models:
            account.append(dict(sourceRecordId=rid,status='existing-detailed-model'));continue
        s=rule['style'];name=s['modelSrc'];rotation=evaluate(s.get('rotation',['literal',[0,0,0]]),p);scale=evaluate(s.get('scale',['literal',[1,1,1]]),p)
        emitted=0;missing=[]
        for point_index,point in enumerate(r['coordinatesMSK']):
            x,z=local(point);tile=owner(point[0],point[1],bounds,size)
            if tile is None:missing.append('outside region');continue
            hit=ground.ground(x,z)
            if hit is None:missing.append('no containing ground surface');continue
            key=(name,round(point[0],2),round(point[1],2),round(rotation[2]%360,2))
            if key in dedup:missing.append('duplicate source placement');continue
            identity=f'street:{rid}:{point_index}';dedup[key]=identity
            matrix=transform(rotation,scale,[x,hit['height'],z]);idx=template(name)
            inst=dict(id=identity,mesh=idx,matrix=matrix,tileId=tile);instances.append(inst);manifest['instances'].append(inst)
            objects.append(dict(id=identity,sourceRecordId=rid,source=r['source'],layer=layer,model=name,styleId=rule['id'],sourcePoint=point,
                rotationDegrees=rotation,sourceScale=scale,orientation='source' if r['orientation']['sourceFields'] else 'source-style-default',
                placement=dict(surface=hit,sourceXYUnchanged=True,heightRule='final-ground-mesh'),renderInstances=[inst]));emitted+=1
        if emitted:account.append(dict(sourceRecordId=rid,status='placed',count=emitted))
        else:defer(r,'; '.join(sorted(set(missing))))
    print('POINTS',len(instances),flush=True)
    fences,fence_objects,fence_account,fence_views,fence_stats=build_fences(records,city,ground,catalog['sourceRulesByLayer']['Fence'])
    objects.extend(fence_objects);account.extend(fence_account)
    deferred.extend(a for a in fence_account if a['status']=='deferred')
    if fences.faces:append_mesh('street-fences',fences,False)
    print('FENCES',fence_stats,flush=True)
    # Crossbars and columns bind to a real underside. A height field alone never
    # justifies adding a floating support where no deck exists in this release.
    crossbars=[]
    for r in (q for q in records if q['layer']=='Road_support_crossbar'):
        p=r['properties'];point=r['coordinatesMSK'][0];x,z=local(point);g=ground.ground(x,z);hits=deck.hits(x,z)
        if not g or not hits:defer(r,'no deck underside above source crossbar');continue
        candidates=[h for h in hits if h['height']>g['height']+.8]
        if not candidates:defer(r,'insufficient ground/deck clearance');continue
        hit=min(candidates,key=lambda h:abs(h['height']-g['height']-point[2]));width=p.get('db_width_m',0)
        if width<=0:defer(r,'missing physical width');continue
        angle=math.radians(p['db_rotation_angle']);axis=np.array([math.cos(angle),-math.sin(angle)]);a=np.array([x,z])-axis*width/2;b=np.array([x,z])+axis*width/2
        # Follow the underside along the whole cap, including sloping ramps.
        # Horizontal caps fitted only at their centre leave visible end gaps.
        normal=np.array([-axis[1],axis[0]])*.325;sections=[];samples=[]
        for t in np.linspace(0,1,max(2,math.ceil(width)+1)):
            middle=a+(b-a)*t;section=[]
            for q in [middle-normal,middle+normal]:
                dh=deck.deck_profile(*q,hit);samples.append(dict(x=float(q[0]),z=float(q[1]),surface=dh))
                section.extend([[q[0],dh['height']-.5,q[1]],[q[0],dh['height'],q[1]]])
            sections.append(section)
        for k,(one,two) in enumerate(zip(sections,sections[1:])):
            v=np.array(one+two)
            for ids in [(1,5,4,0),(6,7,3,2),(3,7,5,1),(4,6,2,0)]:supports.quad(v[list(ids)],2)
            if k==0:supports.quad(v[[2,3,1,0]],2)
            if k==len(sections)-2:supports.quad(v[[5,7,6,4]],2)
        crossbars.append(dict(a=a,b=b,anchor=hit,rotation=p['db_rotation_angle'],sourceRecordId=r['sourceRecordId']))
        objects.append(dict(id='street:'+r['sourceRecordId'],sourceRecordId=r['sourceRecordId'],source=r['source'],layer=r['layer'],sourcePoint=point,sourceWidthM=width,
            rotationDegrees=p['db_rotation_angle'],placement=dict(surface=hit,ground=g,heightRule='deck-underside-profile',profile=samples,defaultThicknessM=.5)))
        account.append(dict(sourceRecordId=r['sourceRecordId'],status='placed',count=1))
    for r in (q for q in records if q['layer']=='Road_support_column'):
        p=r['properties'];point=r['coordinatesMSK'][0];x,z=local(point);g=ground.ground(x,z);hits=deck.hits(x,z)
        if not g:defer(r,'no ground at source column');continue
        candidates=[h for h in hits if h['height']>g['height']+.5]
        if not candidates:defer(r,'no deck underside above source column');continue
        hit=min(candidates,key=lambda h:abs(h['height']-g['height']-p['db_height_m']));top=hit['height'];cap=None
        for cb in crossbars:
            if sh.LineString([cb['a'],cb['b']]).distance(sh.Point(x,z))<.4 and abs(cb['anchor']['height']-top)<2:
                cap_top=deck.deck_profile(x,z,cb['anchor'])['height'];top=min(top,cap_top-.5);cap=cb['sourceRecordId']
        if top<=g['height']+.3:defer(r,'insufficient column clearance');continue
        supports.beam([x,g['height'],z],[x,top,z],.45,2,sides=12)
        objects.append(dict(id='street:'+r['sourceRecordId'],sourceRecordId=r['sourceRecordId'],source=r['source'],layer=r['layer'],sourcePoint=point,sourceHeightM=p['db_height_m'],
            placement=dict(surface=hit,ground=g,top=top,heightRule='ground-to-deck-or-cap',cap=cap,defaultRadiusM=.45)))
        account.append(dict(sourceRecordId=r['sourceRecordId'],status='placed',count=1))
    if supports.faces:append_mesh('street-supports',supports,False)
    assert len(account)==len(records)==len({r['sourceRecordId'] for r in account})
    counts=dict(collections.Counter(o['layer'] for o in objects));stats=dict(objects=len(objects),pointInstances=len(instances),templates=len(library),byLayer=counts,
        sourceRecords=len(records),deferredRecords=len(deferred),existingVegetationRecords=sum(a['status']=='existing-vegetation' for a in account),
        uniqueTriangles=sum(c['triangles'] for c in manifest['chunks'] if c.get('streetGeometry')))
    witness=list(fence_views)
    for names,label,distance in [(['busstation'],'Остановочные павильоны',32),(['bench1','bench2'],'Скамейки и фонари',25),(['slide2'],'Детские площадки',32),(['workout','gyms'],'Спортивные площадки',25)]:
        candidates=[o for o in objects if o.get('model') in names]
        if candidates:
            o=min(candidates,key=lambda o:np.linalg.norm(np.array(o['sourcePoint'][:2])-np.array([ox,oy])))
            m=np.array(o['renderInstances'][0]['matrix']).reshape(3,4);witness.append(dict(label=label,key='street:'+o['model'],camera=dict(yaw=.6,pitch=.65,distance=distance,target=(m[:,3]+[0,1,0]).tolist())))
    layer=dict(version=1,policy=dict(excludedSourceLayers=['Traffic_light'],models='NURAY replaceable PBR display library',placement='source XY and source style rotation; ground from final canonical triangles',
        missingDirection='source-style default, explicitly marked',fences='source lines and source component station phase before transport clipping',supports='source XY/width, fit height to real ground and deck underside',
        icons='no geometry synthesized from map icon anchors'),stats=stats,materials=list(range(matbase,len(manifest['materials']))),library=library,objects=objects,instances=instances,accounting=account,deferred=deferred,witnessViews=witness,
        sourceEvidenceSha256=sha(evidence),sourceInventorySha256=sha(inventory))
    layer['fences']=dict(policy=FENCE_POLICY,stats=fence_stats)
    city['streetLayer']=layer
    revision=dict(version=1,type='street-objects',parent=base.name,previousRevision=city.get('geometryRevision'),parentValidationSha256=sha(base/'validation.json'),changedChunks=[],addedChunks=[c['id'] for c in manifest['chunks'] if c.get('streetGeometry')])
    city['geometryRevision']=revision;report['geometryRevision']=revision;report['streetLayer']=dict(passed=True,**stats)
    manifest['stats'].update(uniqueTriangles=sum(c['triangles'] for c in manifest['chunks']),expandedTriangles=sum(manifest['chunks'][i['mesh']]['triangles'] for i in manifest['instances']))
    report['export'].update(triangles=manifest['stats']['uniqueTriangles'],expandedTriangles=manifest['stats']['expandedTriangles'])
    write(folder/'scene.json',manifest);export_glb(manifest,folder);report['export']['glbBytes']=(folder/'model.glb').stat().st_size
    save_canonical(output/'canonical/urban-model.json',city);write(output/'canonical/validation.json',report);write(output/'street-objects.json',layer)
    shutil.copyfile(evidence,output/'canonical/street-source-evidence.json.gz')
    write(output/'canonical/fence-source-rules.json',dict(rules=catalog['sourceRulesByLayer']['Fence'],sourceInventorySha256=sha(inventory),sourceStyleSha256=catalog['provenance']['stylesSha256']))
    from preview_fences import main as preview_fences
    preview_fences(output)
    print(json.dumps(stats,ensure_ascii=False),flush=True)

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--base',type=Path,required=True);ap.add_argument('--output',type=Path,required=True);ap.add_argument('--evidence',type=Path,required=True);ap.add_argument('--inventory',type=Path,required=True);a=ap.parse_args()
    build(a.base,a.output,a.evidence,a.inventory)
