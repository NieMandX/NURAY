"""Migrate a validated city to the pedestrian-district/planting priority rule."""
import argparse,gzip,hashlib,json,shutil,sys
from collections import defaultdict
from pathlib import Path
import numpy as np
import shapely as sh
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from build import triangulate,z_at
from landscape import plan,split_cell,sides,parts,GREEN_RAISE
from railway_landscape import railway_reserve
from green_insets import recover,protected_ground,areal
from semantics import classify
from pedestrian_materials import is_paving,paving_material_ids
from object_geometry import pack,export_glb
from street_placement import SurfaceSampler,GROUND_NAMES

def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(p,v):p.write_text(json.dumps(v,ensure_ascii=False,separators=(',',':')))

def build(base,out):
    assert base!=out and not out.exists()
    proof=json.loads((base/'validation.json').read_text());assert proof['passed']
    city=json.loads((base/'canonical/urban-model.json').read_text())
    manifest=json.loads((base/'canonical/full/scene.json').read_text())
    report=json.loads((base/'canonical/validation.json').read_text())
    rows=[dict(r,poly=sh.geometry.shape(r['geometry']),plane=np.asarray(r['heightPlane'])) for r in city['surfaces']]
    original_surfaces=len(rows)
    rows,green_rows,recovery=recover(rows,city['features'])
    print('RECOVERY', {k:v for k,v in recovery.items() if k not in {'recoveredGeometry','sourceOwners'}},flush=True)
    extent=sh.box(*city['boundsMSK']);owners={f['id']:f for f in city['features']}
    green=sh.union_all([r['poly'] for r in green_rows],grid_size=1e-5)
    walk_rows=[r for r in rows if is_paving(r) and not r.get('landscapeRole')]
    walk=sh.union_all([r['poly'] for r in walk_rows],grid_size=1e-5)
    layout,landscape=plan(city['features'],green,walk,extent,protected_ground(city),rail_apron=railway_reserve(city) if city['landscape'].get('railApronMaterial') is not None else None)
    old_raised=areal(sh.geometry.shape(city['landscape']['raisedGeometry']))
    added=sh.difference(layout['raised'],old_raised,grid_size=1e-5)
    removed=sh.difference(old_raised,layout['raised'],grid_size=1e-5)
    recovery.update(newRaisedAreaM2=added.area,previousRaisedLossM2=removed.area)
    # Newly exposed source paths may continue across the old planting edge.
    # Only those real path/protected corridors may convert previous green.
    assert removed.difference(layout['cut'].buffer(.00005)).area<.01,('Green lost outside path corridors',removed.area)
    print('RAISED',added.area,'previous loss',removed.area,flush=True)
    cache=np.load(base/'canonical/terrain.npz');dem=list(zip(sh.from_wkb(cache['polygons']),cache['planes']));tree=sh.STRtree([p for p,c in dem])
    # Retain the same precision repairs as the normal landscape build.
    gt=sh.STRtree([r['poly'] for r in green_rows]);original_green=list(green_rows)
    for i in tree.query(layout['filled'],predicate='intersects'):
        for p in parts(layout['filled'].intersection(dem[i][0])):
            if p.area<1e-9:continue
            parent=original_green[int(gt.nearest(p.representative_point()))]
            green_rows.append(dict(parent,poly=p,plane=dem[i][1]+[0,0,.1]))
    groups=defaultdict(list);mats=defaultdict(list);new_rows=[]
    material_map=city['landscape']['materials']
    def emit(r,p,c,material,name,role=None):
        if p.area<1e-9:return
        row={k:v for k,v in r.items() if k not in {'poly','plane','geometry','heightPlane','landscapeRole'}}
        row.update(id=f'green-priority:{len(new_rows)}',geometry=sh.geometry.mapping(p),heightPlane=c.tolist(),material=material,
                   kind='green_curb_top' if role=='curb' else 'land')
        if role:
            row['landscapeRole']=role
            row['purpose']='green-border' if role=='curb' else 'pedestrian' if role=='path' else 'railway' if role=='railway_apron' else 'vegetation-cover'
            row['surfaceType']='concrete' if role=='curb' else 'pedestrian-paving' if role=='path' else 'dark-concrete' if role=='railway_apron' else 'vegetation'
            if role=='path':row['replacedGreenOwner']=r['owner']
        new_rows.append(row);faces=triangulate(p,c);groups[name].extend(faces);mats[name].extend([material]*len(faces))
    for r in walk_rows:emit(r,r['poly'],r['plane'],r['material'],'walk')
    for n,r in enumerate(green_rows):
        for role,g,c in split_cell(r['poly'],r['plane'],layout):
            material=material_map[owners[r['owner']]['layer']] if role=='green' else 9 if role=='curb' else city['landscape']['railApronMaterial'] if role=='railway_apron' else 7
            name='green' if role=='green' else 'green_curb_top' if role=='curb' else 'railway_apron' if role=='railway_apron' else 'pedestrian_path'
            for p in parts(g):emit(r,p,c,material,name,role)
        if n and n%30000==0:print('GREEN CELLS',n,flush=True)
    groups['green_curb_side']=sides(layout,dem,tree,extent,triangulate,z_at)
    mats['green_curb_side']=[9]*len(groups['green_curb_side'])
    print('MESHES', {k:len(v) for k,v in groups.items()},flush=True)
    out.mkdir()
    for name in ['canonical','textures','library']:
        if (base/name).exists():shutil.copytree(base/name,out/name)
    folder=out/'canonical/full';origin=np.asarray(city['originMSK']);changed=[];targets=defaultdict(list)
    for c in manifest['chunks']:
        name=c['name']
        if name in {'green_curb_top','green_curb_side','pedestrian_path','railway_apron'}:targets[name].append(c)
        elif name=='land':
            raw=gzip.decompress((folder/Path(c['file']).name).read_bytes());u=np.frombuffer(raw[:c['vertexBytes']],'<u4').reshape(-1,8)
            ids=set((u[:,6]&0x7fffffff).tolist())
            if ids<=paving_material_ids(manifest):targets['walk'].append(c)
            elif ids<=set(material_map.values()):targets['green'].append(c)
    assert set(targets)==set(groups)
    for name,chunks in targets.items():
        faces=np.asarray(groups[name]);materials=np.asarray(mats[name],dtype=np.uint32)
        for c,indices in zip(chunks,np.array_split(np.arange(len(faces)),len(chunks))):
            path=folder/Path(c['file']).name;changed.append(dict(id=c['id'],name=c['name'],beforeSha256=digest(path),reason='green-inset-partition'))
            xyz=(faces[indices]-origin)[:,:,[0,2,1]]*[1,1,-1]
            normals=np.cross(xyz[:,1]-xyz[:,0],xyz[:,2]-xyz[:,0]);normals/=np.maximum(np.linalg.norm(normals,axis=1,keepdims=True),1e-20)
            attrs=np.concatenate([xyz,np.repeat(normals[:,None,:],3,axis=1),xyz[:,:,[0,2]]],axis=2)
            meta=pack(attrs,materials[indices],path);assert meta;c.update(meta)
    keep=[r for r in rows if not r.get('landscapeRole') and not is_paving(r)]
    city['surfaces']=[{k:v for k,v in r.items() if k not in {'poly','plane'}} for r in keep]+new_rows
    for f in city['features']:
        if f['layer']=='Pedestrian_quarter':f['semantics']=classify(f['layer'],f['properties'],f['geometryType'])
    by_id={i.get('id'):i for i in manifest['instances']};instance_changes=[]
    for obj in city.get('objectLayer',{}).get('vegetation',[]):
        point=sh.Point(obj['position'][:2]);delta=GREEN_RAISE if added.covers(point) else -GREEN_RAISE if removed.covers(point) else 0
        if not delta:continue
        obj['groundHeightM']+=delta;obj['landscapeShiftM']=GREEN_RAISE if delta>0 else 0
        for inst in obj['renderInstances']:
            before=list(inst['matrix']);inst['matrix'][7]+=delta;by_id[inst['id']]['matrix']=list(inst['matrix'])
            instance_changes.append(dict(id=inst['id'],before=before,after=list(inst['matrix'])))
    ground=SurfaceSampler(out,manifest,GROUND_NAMES)
    street_instances={i['id']:i for i in city.get('streetLayer',{}).get('instances',[])}
    for obj in city.get('streetLayer',{}).get('objects',[]):
        if not obj.get('renderInstances'):continue
        x,y,_=obj['sourcePoint'];hit=ground.ground(x-origin[0],origin[1]-y);assert hit
        obj['placement']['surface']=hit
        for inst in obj['renderInstances']:
            before=list(inst['matrix']);inst['matrix'][7]=hit['height'];by_id[inst['id']]['matrix']=list(inst['matrix']);street_instances[inst['id']]['matrix']=list(inst['matrix'])
            if before!=inst['matrix']:instance_changes.append(dict(id=inst['id'],before=before,after=list(inst['matrix'])))
    landscape.update(materials=material_map,railApronMaterial=city['landscape'].get('railApronMaterial'),raisedGeometry=sh.geometry.mapping(layout['raised']),curbGeometry=sh.geometry.mapping(layout['band']),
        convertedGeometry=sh.geometry.mapping(sh.union_all([green,layout['filled']]).difference(layout['raised'])),
        activePaths=sum(p['convertedGreenAreaM2']>.01 for p in landscape['sourcePaths']),
        shiftedTreeInstances=sum(bool(o.get('landscapeShiftM')) for o in city['objectLayer']['vegetation']),passed=True,insetRecovery=recovery)
    city['landscape']=landscape;report['landscape']=landscape
    revision=dict(type='green-insets',parent=base.name,parentValidationSha256=digest(base/'validation.json'),previousRevision=city['geometryRevision'],
        changedChunks=changed,instanceChanges=instance_changes,sourceSurfaceCount=original_surfaces,recovery=recovery,
        rule='Detailed paving > explicit planting > generic pedestrian quarter. Rebuild the unified planting perimeter before transport tiling.')
    city['geometryRevision']=revision;report['geometryRevision']=revision;city['rules']['greenInsets']=revision['rule']
    manifest['stats'].update(uniqueTriangles=sum(c['triangles'] for c in manifest['chunks']),expandedTriangles=sum(manifest['chunks'][i['mesh']]['triangles'] for i in manifest['instances']))
    report['export'].update(triangles=manifest['stats']['uniqueTriangles'],expandedTriangles=manifest['stats']['expandedTriangles'],chunks=len(manifest['chunks']),downloadBytes=sum((folder/Path(c['file']).name).stat().st_size for c in manifest['chunks']))
    save(folder/'scene.json',manifest);export_glb(manifest,folder);report['export']['glbBytes']=(folder/'model.glb').stat().st_size
    save(out/'canonical/urban-model.json',city);save(out/'canonical/validation.json',report)
    if city.get('streetLayer'):save(out/'street-objects.json',city['streetLayer'])
    print('SAVED',out,'instance changes',len(instance_changes),flush=True)

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--base',type=Path,required=True);ap.add_argument('--output',type=Path,required=True);args=ap.parse_args();build(args.base,args.output)
