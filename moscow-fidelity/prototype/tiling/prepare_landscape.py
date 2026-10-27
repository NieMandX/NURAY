"""General canonical refinement: ground paths, green curbs, railway bases, guards.

Run after source surface, object and railway stages, before pack_tiles.mjs.
An immutable parent version and an exact terrain cache are required. Every
unrelated mesh/texture is retained byte for byte; a revision lists the changes.
"""
from pathlib import Path
from collections import defaultdict
import argparse,gzip,hashlib,json,shutil,sys,gc
import numpy as np
import shapely as sh
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from build import triangulate,z_at,plane
from landscape import plan,split_cell,sides,parts,GREEN_VARIANTS,GREEN_RAISE
from railway_surfaces import confirmed_owners,RAIL_COLOR
from tunnel_walls import build as build_walls
from green_insets import protected_ground
from railway_landscape import railway_reserve
from spatial_mask import SpatialMask
from pedestrian_materials import is_paving
from object_geometry import pack,export_glb,decode_normals
from canonical_store import load_canonical, save_canonical, copy_asset

WALLS={'tunnel_wall_top','tunnel_wall_bottom','tunnel_wall_side','inferred-walls',
       'portal_guard_top','portal_guard_bottom','portal_guard_side'}

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--base',type=Path,required=True);ap.add_argument('--output',type=Path,required=True)
    ap.add_argument("--reuse",type=Path,help="Validated same-parent landscape partition cache; final geometry is fully rechecked")
    args=ap.parse_args()
    if args.base.resolve()==args.output.resolve():raise ValueError('Write a separate immutable version')
    city=load_canonical(args.base/'canonical/urban-model.json')
    gc.freeze()  # Long-lived acyclic input; keep reference-counted disposal.
    if city.get('landscape'):raise ValueError('Rebuild from the unrefined parent; do not apply the green step twice')
    report=json.loads((args.base/'canonical/validation.json').read_text());assert report['passed']
    folder=args.output/'canonical/full';folder.mkdir(parents=True,exist_ok=True)
    for f in (args.base/'canonical/full').iterdir():copy_asset(f,folder/f.name)
    from support_assets import copy_support_assets
    copy_support_assets(args.base,args.output)
    terrain=args.base/'canonical/terrain.npz'
    manifest=json.loads((folder/'scene.json').read_text());old_count=len(manifest['chunks']);origin=np.asarray(city['originMSK'])
    cache=np.load(terrain);assert np.array_equal(cache['bounds'],city['boundsMSK'])
    dem=list(zip(sh.from_wkb(cache['polygons']),cache['planes']));tree=sh.STRtree([p for p,c in dem]);extent=sh.box(*city['boundsMSK'])
    rows=[{**s,'poly':sh.geometry.shape(s['geometry']),'plane':np.asarray(s['heightPlane'])} for s in city['surfaces']]
    green_rows=[r for r in rows if r['kind']=='land' and r.get('purpose')=='vegetation-cover']
    owners={f['id']:f for f in city['features']};green_ids={r['id'] for r in green_rows}
    print('LANDSCAPE INPUT',len(green_rows),'green terrain cells',flush=True)
    green=sh.union_all([r['poly'] for r in green_rows],grid_size=1e-5)
    walk=sh.union_all([r['poly'] for r in rows if is_paving(r)],grid_size=1e-5)
    groups=defaultdict(list)
    _,walls=build_walls(rows,city['features'],dem,tree,groups,extent,1e-5,city['gradeConnections'],city['sourceStyle'],triangulate,z_at,plane)
    assert walls['passed'];print('GUARDS REBUILT',walls['ruleVersion'],flush=True)
    reserve=protected_ground(dict(city,tunnelWalls=walls))
    layout,landscape=plan(city['features'],green,walk,extent,reserve,rail_apron=railway_reserve(city))
    print('NUMERIC GREEN CLEANUP',landscape['numericCleanup'],flush=True)
    # Fill the sub-grid repairs on the same terrain, with source ownership and
    # the neighbouring green class retained. This is not a floating overlay.
    green_tree=sh.STRtree([r['poly'] for r in green_rows]);original_green=list(green_rows)
    filled_mask=SpatialMask(layout['filled'])
    for i in tree.query(layout['filled'],predicate='intersects'):
        for p in parts(filled_mask.near(dem[i][0]).intersection(dem[i][0])):
            if p.area<1e-9:continue
            parent=original_green[int(green_tree.nearest(p.representative_point()))]
            green_rows.append(dict(parent,id=f"numeric-green:{len(green_rows)}",poly=p,plane=dem[i][1]+[0,0,.1],
                geometryRepair='sub-0.1-mm-source-green-crack'))
    print('NUMERIC GREEN REPAIRS',len(green_rows)-len(original_green),landscape['numericClosure'],flush=True)
    material_map={'Internal_lawn':2}
    def material(name,color,family,roughness):
        idx=len(manifest['materials']);manifest['materials'].append(dict(name=name,family=family,color=color,
            roughness=roughness,metallic=0,ior=1.5,kind=1,texture=None,alphaCutoff=0));return idx
    for layer,(name,color) in GREEN_VARIANTS.items():
        if layer not in material_map:material_map[layer]=material(name,color,'green-cover',.96)
    rail_material=material('Железнодорожное основание · тёмный бетон',RAIL_COLOR,'rail-concrete',.92)
    landscape['materials']=material_map;landscape['railApronMaterial']=rail_material
    reuse_mask=None;reuse_cache={};reuse_proof=None
    if args.reuse:
        from landscape_reuse import prepare
        reuse_mask,reuse_cache,reuse_proof=prepare(args.reuse,args.base,city,layout)
        print('PARTITION CACHE',len(reuse_cache),'cells; changed mask',reuse_mask.area,flush=True)
    new_rows=[];green_faces=[];green_mats=[];new_groups=defaultdict(list)
    for index,r in enumerate(green_rows):
        mid=material_map[owners[r['owner']]['layer']]
        cached=reuse_cache.pop(r['id'],None)
        reusable=cached is not None and not reuse_mask.intersects(r['poly'])
        if reuse_proof:reuse_proof['reusedCells' if reusable else 'recomputedCells']+=1
        for category,g,c in cached if reusable else split_cell(r['poly'],r['plane'],layout):
            for p in parts(g):
                if p.area<1e-9:continue
                m=mid if category=='green' else 9 if category=='curb' else rail_material if category=='railway_apron' else 7
                name='land' if category=='green' else 'green_curb_top' if category=='curb' else 'railway_apron' if category=='railway_apron' else 'pedestrian_path'
                row={k:v for k,v in r.items() if k not in ('poly','plane','geometry','heightPlane')}
                row.update(id=f"{r['id']}:landscape:{category}:{len(new_rows)}",poly=p,plane=c,material=m,
                           kind='green_curb_top' if category=='curb' else 'land',landscapeRole=category)
                if category=='path':row.update(purpose='pedestrian',surfaceType='pedestrian-paving',replacedGreenOwner=r['owner'])
                if category=='curb':row.update(purpose='green-border',surfaceType='concrete')
                if category=='railway_apron':row.update(purpose='railway',surfaceType='dark-concrete',replacedGreenOwner=r['owner'])
                new_rows.append(row);faces=triangulate(p,c)
                if category=='green':green_faces.extend(faces);green_mats.extend([m]*len(faces))
                else:new_groups[(name,m)].extend(faces)
        if index and index%20000==0:print('GREEN CELLS',index,flush=True)
    if reuse_proof:landscape['partitionReuse']=reuse_proof;print('PARTITION REUSE',reuse_proof,flush=True)
    print('BUILD GREEN BORDER SIDES',flush=True)
    new_groups[('green_curb_side',9)]=sides(layout,dem,tree,extent,triangulate,z_at)
    print('PACK REFINED GEOMETRY',flush=True)
    changed=[];preserved=[];added=[]
    def raw(c):return gzip.decompress((folder/Path(c['file']).name).read_bytes())
    def record(c,reason,**extra):changed.append(dict(id=c['id'],name=c['name'],reason=reason,beforeSha256=hashlib.sha256(raw(c)).hexdigest(),**extra))
    def write(c,faces,mats):
        xyz=(np.asarray(faces)-origin)[:,:,[0,2,1]]*[1,1,-1]
        n=np.cross(xyz[:,1]-xyz[:,0],xyz[:,2]-xyz[:,0]);n/=np.maximum(np.linalg.norm(n,axis=1,keepdims=True),1e-20)
        t=np.concatenate([xyz,np.repeat(n[:,None,:],3,axis=1),xyz[:,:,[0,2]]],axis=2)
        meta=pack(t,np.broadcast_to(mats,len(t)),folder/Path(c['file']).name)
        if not meta:raise ValueError(('Empty generated chunk',c['name']))
        c.update(meta)
    def append(name,faces,mats):
        idx=len(manifest['chunks']);c=dict(id=idx,name=name,category=name,file=f'mesh-{idx:03d}.bin.gz')
        write(c,faces,mats);manifest['chunks'].append(c)
        manifest['instances'].append(dict(mesh=idx,matrix=[1,0,0,0,0,1,0,0,0,0,1,0]));added.append(idx)
    for name in sorted(WALLS):
        chunks=[c for c in manifest['chunks'] if c['name']==name];faces=groups[(name,6)]
        if not chunks and faces:append(name,faces,6);continue
        for c,part in zip(chunks,np.array_split(np.asarray(faces),len(chunks)) if chunks else []):
            record(c,'retaining-guard');write(c,part,6)
    lawn_chunks=[]
    for c in manifest['chunks'][:old_count]:
        if c['name']!='land':continue
        data=raw(c);words=np.frombuffer(data[:c['vertexBytes']],'<u4').reshape(-1,8)
        if np.all((words[:,6]&0x7fffffff)==2):lawn_chunks.append(c)
    assert lawn_chunks,'Expected the source vegetation-cover mesh'
    for c,idx in zip(lawn_chunks,np.array_split(np.arange(len(green_faces)),len(lawn_chunks))):
        record(c,'green-partition');write(c,np.asarray(green_faces)[idx],np.asarray(green_mats,dtype=np.uint32)[idx])
    for (name,mat),faces in sorted(new_groups.items()):
        if faces:append(name,faces,mat)
    rail_proof=confirmed_owners(city['features']);rail_owners={r['source'] for r in rail_proof}
    transport_rows=[r for r in rows if r['material']==12]
    restyled=[r for r in transport_rows if r['owner'] in rail_owners]
    # Attribute-preserving remap. Mixed future slabs are matched triangle by
    # triangle to the actual canonical surface/height, not by global proximity.
    for c in manifest['chunks'][:old_count]:
        if c['name'] not in {'roadbed_overpass','roadbed_tunnel','roadbed_tunnel_descent'}:continue
        data=raw(c);u=np.frombuffer(data[:c['vertexBytes']],'<u4').reshape(-1,8).copy();v=u.view('<f4')
        ix=np.frombuffer(data[c['vertexBytes']:],'<u4').reshape(-1,3);mids=u[ix[:,0],6]&0x7fffffff
        if not np.any(mids==12):continue
        relevant=[r for r in transport_rows if r['kind']==c['name']]
        if relevant and all(r['owner'] in rail_owners for r in relevant):
            record(c,'rail-material',fromMaterial=12,toMaterial=rail_material)
            u[(u[:,6]&0x7fffffff)==12,6]=np.uint32(0x80000000|rail_material)
            with gzip.GzipFile(filename=str(folder/Path(c['file']).name),mode='wb',mtime=0) as f:f.write(u.tobytes()+data[c['vertexBytes']:])
        else:
            polys=[r['poly'] for r in relevant];rtree=sh.STRtree(polys);centres=v[ix,:3].mean(1)[:,[0,2,1]]*[1,-1,1]+origin
            selection=np.zeros(len(ix),bool)
            for j in np.flatnonzero(mids==12):
                for ri in rtree.query(sh.Point(centres[j,:2]),predicate='covered_by'):
                    r=relevant[int(ri)]
                    if r['owner'] in rail_owners and abs(z_at(r['plane'],centres[j,:2])-centres[j,2])<.003:selection[j]=True
            if selection.any():
                record(c,'rail-material-mixed',fromMaterial=12,toMaterial=rail_material)
                mats=mids.copy();mats[selection]=rail_material
                attrs=np.concatenate([v[:,:3],decode_normals(u[:,3]),v[:,4:6]],axis=1)
                c.update(pack(attrs[ix],mats,folder/Path(c['file']).name))
    for r in restyled:r.update(material=rail_material,purpose='railway',surfaceType='dark-concrete')
    instance_changes=[];by_id={i['id']:i for i in manifest['instances'] if i.get('id')}
    for obj in city.get('objectLayer',{}).get('vegetation',[]):
        if not layout['raised'].covers(sh.Point(obj['position'][:2])):continue
        obj['groundHeightM']+=GREEN_RAISE;obj['landscapeShiftM']=GREEN_RAISE
        for inst in obj['renderInstances']:
            before=list(inst['matrix']);inst['matrix'][7]+=GREEN_RAISE;by_id[inst['id']]['matrix']=list(inst['matrix'])
            instance_changes.append(dict(id=inst['id'],before=before,after=inst['matrix']))
    changed_ids={r['id'] for r in changed}
    for c in manifest['chunks'][:old_count]:
        if c['id'] not in changed_ids:preserved.append(dict(id=c['id'],sha256=hashlib.sha256(raw(c)).hexdigest()))
    rows=[r for r in rows if r['id'] not in green_ids]+new_rows
    city['surfaces']=[{**{k:v for k,v in s.items() if k not in ('poly','plane','geometry','heightPlane')},
                      'geometry':sh.geometry.mapping(s['poly']),'heightPlane':s['plane'].tolist()} for s in rows]
    landscape.update(raisedGeometry=sh.geometry.mapping(layout['raised']),curbGeometry=sh.geometry.mapping(layout['band']),
        discardedNumericGeometry=sh.geometry.mapping(layout['discarded']),
        convertedGeometry=sh.geometry.mapping(sh.union_all([green,layout['filled']]).difference(layout['raised']).difference(layout['discarded'])),
        activePaths=sum(r['convertedGreenAreaM2']>.01 for r in landscape['sourcePaths']),
        shiftedTreeInstances=len(instance_changes),passed=True)
    city['landscape']=landscape;report['landscape']=landscape
    city['tunnelWalls']=walls;report['tunnelWalls']=walls;city['rules']['tunnelWalls']=walls['policy'];city['rules']['landscape']=landscape['policy']
    if city.get('railwayLayer'):
        city['railwayLayer']['baseRestyle']=dict(applied=True,material=rail_material,color=RAIL_COLOR,confirmedSurfaces=rail_proof,
            policy='Explicit Transport_Roadbed, same-tier source rail axis through the slab; no XY proximity-only classification. Ground ribbons and their UVs are unchanged.')
    revision=dict(version=2,type='landscape',parent=args.base.name,previousRevision=city.get('geometryRevision'),
        changedChunks=changed,preservedChunks=preserved,newChunks=added,instanceChanges=instance_changes,
        railMaterial=rail_material,railProof=rail_proof,originalMaterials=len(manifest['materials'])-5,
        terrainSha256=hashlib.sha256(terrain.read_bytes()).hexdigest())
    city['geometryRevision']=revision;report['geometryRevision']=revision
    city['limitations'] += ['Ground path widths (2 m ordinary/stairs, 3 m park path, 1.2 m footpath), green edging and green albedos are project reconstruction defaults, not surveyed dimensions or source textures. Ground stair lines produce ramps, not detailed treads.']
    manifest['stats'].update(uniqueTriangles=sum(c['triangles'] for c in manifest['chunks']),expandedTriangles=sum(manifest['chunks'][i['mesh']]['triangles'] for i in manifest['instances']))
    report['export'].update(triangles=manifest['stats']['uniqueTriangles'],expandedTriangles=manifest['stats']['expandedTriangles'],chunks=len(manifest['chunks']),downloadBytes=sum((folder/Path(c['file']).name).stat().st_size for c in manifest['chunks']))
    (folder/'scene.json').write_text(json.dumps(manifest,ensure_ascii=False,separators=(',',':')));export_glb(manifest,folder)
    report['export']['glbBytes']=(folder/'model.glb').stat().st_size
    save_canonical(args.output/'canonical/urban-model.json',city)
    (args.output/'canonical/validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    # Catch planting/guard intrusions before spending time on transport tile
    # packing. The final verifier still repeats this on the serialized tiles.
    from interface_validation import passage_volumes,check_interfaces
    from prepare_railway_entries import meshes
    print('CHECK LANDSCAPE STRUCTURE ENTRIES',flush=True)
    entry_check=check_interfaces(passage_volumes(city),meshes(args.output,manifest))
    (args.output/'landscape-entry-preflight.json').write_text(json.dumps(entry_check,indent=2))
    assert entry_check['passed'],[r for r in entry_check['checks'] if not r['passed']]
    print('LANDSCAPE VERSION',args.output,'paths',landscape['activePaths'],'path area',landscape['newPathAreaM2'],
          'raised area',landscape['raisedAreaM2'],'rail slabs',len(rail_proof),'shifted trees',len(instance_changes),flush=True)

if __name__=='__main__':main()
