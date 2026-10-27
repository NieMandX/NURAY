"""Add retained buildings and instanced vegetation to a validated region.

The surface build is reused byte-for-byte; no roads, curbs or tile cuts are
reconstructed here. Object placement is solved once before transport packing.
"""
from pathlib import Path
from collections import defaultdict
import argparse, json, shutil, hashlib, gzip, sys
import numpy as np
import shapely as sh
from shapely.strtree import STRtree
from object_geometry import AXES,clip_triangles,pack,export_glb
from vegetation_variation import apply as apply_variation
from custom_vegetation import install as install_vegetation
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from source_objects import partition, receipt
from canonical_store import load_canonical, save_canonical

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--base',type=Path,required=True);ap.add_argument('--extraction',type=Path,required=True);ap.add_argument('--output',type=Path,required=True);args=ap.parse_args()
    if args.base.resolve()==args.output.resolve():raise ValueError('Write a separate version')
    output=args.output;folder=output/'canonical/full';folder.mkdir(parents=True,exist_ok=True)
    for file in (args.base/'canonical/full').iterdir():shutil.copy2(file,folder/file.name)
    if (args.base/'canonical/terrain.npz').exists():shutil.copy2(args.base/'canonical/terrain.npz',args.output/'canonical/terrain.npz')
    city=load_canonical(args.base/'canonical/urban-model.json');report=json.loads((args.base/'canonical/validation.json').read_text());assert report['passed']
    manifest=json.loads((folder/'scene.json').read_text());extraction=json.loads((args.extraction/'extraction.json').read_text())
    extraction['objects'],excluded_objects=partition(extraction['objects'])
    source_path=Path(extraction['pbrSource']);source=json.loads(source_path.read_text())
    origin=np.asarray(city['originMSK']);x0,y0,x1,y1=city['boundsMSK'];clip=[x0-origin[0],origin[1]-y1,x1-origin[0],origin[1]-y0]
    # Use the very same raised ground cells as the road prototype. A tree root
    # samples a surface once; a building's complete source hierarchy moves rigidly.
    land=[s for s in city['surfaces'] if s['kind'] in {'land','curb_top','roadbed_flat','water'}];polys=np.asarray([sh.geometry.shape(s['geometry']) for s in land],dtype=object)
    tree=STRtree(polys);planes=np.asarray([s['heightPlane'] for s in land]);fallback=[];datum_bindings=[];terrain_index=None
    def ground(xy,owner):
        nonlocal terrain_index
        point=sh.Point(*xy);hits=tree.query(point,predicate='covered_by')
        if len(hits):return float(np.max(planes[hits]@np.r_[xy,1]))
        # A source model's anchor can be over a tunnel cutout or in an open
        # courtyard inside a compound model. Its vertical reference is still
        # the shared terrain datum, not an arbitrarily distant pavement plane.
        # Only building hierarchies may use this reference; foliage needs a
        # real finished ground surface at its source position.
        if owner.startswith('building:'):
            if terrain_index is None:
                cache=np.load(args.base/'canonical/terrain.npz');terrain_polys=sh.from_wkb(cache['polygons'])
                terrain_index=(STRtree(terrain_polys),cache['planes'])
            terrain_tree,terrain_planes=terrain_index;ids=terrain_tree.query(point,predicate='covered_by')
            if len(ids):
                value=float(terrain_planes[int(ids[0])]@np.r_[xy,1])+.1
                datum_bindings.append(dict(owner=owner,point=list(map(float,xy)),heightM=value,method='shared-terrain-datum-under-source-building-anchor'))
                return value
        raise ValueError(('No confirmed surface at source object anchor',owner,xy))
    # Combine provider triangle strips into a footprint; use the complete source
    # footprint, not the transport tile containing one fragment of the building.
    footprints=defaultdict(list)
    for f in city['features']:
        if f['semantics']['purpose']!='building' or f['geometryType']!='polygon' or '_roof' in f['layer']:continue
        key=str(f['properties'].get('id',''));xy=np.asarray(f['coordinates'])[:,:2]
        for k in range(len(xy)-2):
            p=sh.Polygon(xy[k:k+3])
            if p.area>1e-8:footprints[key].append(p)
    footprints={key:sh.union_all(parts) for key,parts in footprints.items()}
    anchors={};groups=defaultdict(list);object_rows=[];id_map={};used_textures={}
    for row in extraction['objects']:groups[row.get('sourceBuildingId') or row['id']].append(row)
    for bid,rows in groups.items():
        footprint=footprints.get(bid)
        if footprint is not None and not footprint.is_empty:p=footprint.representative_point();xy=[p.x,p.y]
        else:
            lo=np.min([r['bounds']['min'] for r in rows],axis=0);hi=np.max([r['bounds']['max'] for r in rows],axis=0);xy=((lo[:2]+hi[:2])/2).tolist()
        detailed=[r['sourceTerrainBaseM'] for r in rows if 'sourceTerrainBaseM' in r]
        body=[r['bounds']['min'][2] for r in rows if r['category']=='building' and '_roof_' not in r.get('sourceLayer','')]
        baseline=min(detailed) if detailed else min(body) if body else None
        inside=x0<=xy[0]<=x1 and y0<=xy[1]<=y1
        if not inside and any(r.get('heightReference')=='source-relative' for r in rows):
            # Fresh source GLBs have no absolute ground elevation to preserve.
            # A building crossing the extraction boundary still needs one rigid
            # terrain anchor, selected from its visible footprint inside the AOI.
            visible=footprint.intersection(sh.box(x0,y0,x1,y1)) if footprint is not None else None
            if visible is not None and not visible.is_empty:
                point=visible.representative_point();xy=[point.x,point.y]
            else:xy=np.clip(xy,[x0,y0],[x1,y1]).tolist()
            inside=True
        target=ground(xy,'building:'+bid) if inside else (baseline+.1 if baseline is not None else None)
        # A roof fragment without its base is never lowered to the ground.
        delta=target-baseline if baseline is not None else .1
        anchors[bid]=dict(positionMSK=xy,sourceBaseM=baseline,targetBaseM=target,shiftM=delta,method=('rigid-source-building-group' if inside else 'outside-anchor-preserve-source-height') if baseline is not None else 'roof-only-preserve-source-height')
    def material(old):
        old=int(old)
        if old not in id_map:
            m=dict(source['materials'][old]);m['sourcePbrIndex']=old
            assert max(m['color'])<=.65001,('Paint must remain brightest',m)
            if m.get('texture'):
                name=Path(m['texture']).name;raw=(source_path.parent/name).read_bytes();(folder/name).write_bytes(raw)
                m['texture']=f'textures/{name}';used_textures[name]=dict(sha256=hashlib.sha256(raw).hexdigest(),bytes=len(raw))
            id_map[old]=len(manifest['materials']);manifest['materials'].append(m)
        return id_map[old]
    def add_chunk(tris,mats,name,category,**extra):
        idx=len(manifest['chunks']);file=f'mesh-{idx:03d}.bin.gz';meta=pack(tris,np.asarray([material(m) for m in mats],dtype=np.uint32),folder/file)
        if meta is None:return None
        manifest['chunks'].append(dict(id=idx,name=name,category=category,file=file,**meta,**extra));return idx
    # Keep a compact source object inventory and its exact primitive range.
    batches=defaultdict(list)
    for row in extraction['objects']:
        data=np.load(args.extraction/row['file']);t=data['triangles'].copy();m=data['materials'];bid=row.get('sourceBuildingId') or row['id'];anchor=anchors[bid]
        t[:,:,2]+=anchor['shiftM'];t[:,:,:3]=(t[:,:,:3]-origin)@AXES.T;t[:,:,3:6]=t[:,:,3:6]@AXES.T
        t,m=clip_triangles(t,m,clip)
        if not len(t):continue
        batches[row['category']].append((t,m,row));object_rows.append({**row,'placement':anchor,'retainedTriangles':len(t)})
    for category,parts in batches.items():
        # Category batches bound GPU allocations; source object IDs remain in
        # each chunk. Packed triangles additionally retain canonical lineage.
        ts=[];ms=[];owners=[]
        for t,m,row in parts:ts.append(t);ms.append(m);owners.extend([row['id']]*len(t))
        ts=np.concatenate(ts);ms=np.concatenate(ms)
        for start in range(0,len(ts),90000):
            end=min(start+90000,len(ts));index=add_chunk(ts[start:end],ms[start:end],category,category,objectGeometry=True,sourceObjectIds=sorted(set(owners[start:end])))
            if index is None:continue
            pp=ts[start:end,:,:3].astype('<f4')
            valid=np.linalg.norm(np.cross(pp[:,1]-pp[:,0],pp[:,2]-pp[:,0]),axis=1)>1e-9
            packed_owners=np.asarray(owners[start:end])[valid]
            ranges=[]
            for owner in packed_owners:
                if ranges and ranges[-1]['id']==owner:ranges[-1]['count']+=1
                else:ranges.append(dict(id=str(owner),first=sum(r['count'] for r in ranges),count=1))
            assert len(packed_owners)==manifest['chunks'][index]['triangles']
            manifest['chunks'][index]['sourceObjectRanges']=ranges
            manifest['instances'].append(dict(mesh=index,matrix=[1,0,0,0,0,1,0,0,0,0,1,0]))
            # Canonical packed primitives can drop truly collapsed faces. The
            # object inventory retains originals; packed lineage uses its chunk.
    template_map={}
    for row in extraction['templates']:
        data=np.load(args.extraction/row['file']);t=data['triangles'].copy();t[:,:,:3]=t[:,:,:3]@AXES.T;t[:,:,3:6]=t[:,:,3:6]@AXES.T
        idx=add_chunk(t,data['materials'],row['id'],'vegetation',instanced=True,objectGeometry=True)
        assert idx is not None;template_map[row['id']]=idx
    vegetation=[]
    for row in extraction['instances']:
        p=np.asarray(row['position'],dtype=float);old_z=float(p[2]);p[2]=ground(p[:2],row['id'])
        linear=AXES@np.asarray(row['linear'])@AXES.T;translation=AXES@(p-origin);matrix=np.column_stack((linear,translation)).ravel().tolist()
        # A half-open ownership rule keeps a boundary tree whole, present once.
        east=int((p[0]-x0)//250);north=int((p[1]-y0)//250);tile_id=f'{east}-{north}'
        assert np.linalg.det(linear)>1e-9
        entries=[]
        for name in row['templates']:
            entry=dict(id=row['id']+':'+name,objectId=row['id'],mesh=template_map[name],matrix=matrix,tileId=tile_id);manifest['instances'].append(entry);entries.append(entry)
        vegetation.append({**row,'sourceHeightM':old_z,'groundHeightM':float(p[2]),'tileId':tile_id,'renderInstances':entries})
    layer=dict(version=1,sourceBlend=extraction['sourceBlend'],sourcePbrSha256=hashlib.sha256(source_path.read_bytes()).hexdigest(),
        buildings=object_rows,vegetation=vegetation,templates=template_map,textures=used_textures,groundFallbacks=fallback,terrainDatumBindings=datum_bindings,sourceGeometry=receipt(excluded_objects),
        policy=dict(buildings='one rigid translation per source building ID before clipping; retain child-node offsets, normals and atlas UVs; no terrain drape per vertex or sign',
          vegetation='source XY, rotation and scale; root on canonical raised ground; half-open owner tile by root; full crown and shared mesh/BVH',materials='retain established NURAY PBR conversion and source atlases; non-paint reflectance at most 0.65; do not invent solid glass interiors'))
    from flat_roofs import install as install_flat_roofs
    roofs=install_flat_roofs(object_rows,manifest,folder,city['boundsMSK'])
    layer['roofs']={k:roofs[k] for k in ('policy','stats','records')}
    from pitched_roofs import install as install_pitched_roofs
    pitched=install_pitched_roofs(object_rows,manifest,folder)
    layer['pitchedRoofs']={k:pitched[k] for k in ('policy','material','stats')}
    from facade_bands import install as install_facades
    facades=install_facades(object_rows,manifest,folder)
    layer['facades']={k:facades[k] for k in ('policy','material','stats')}
    install_vegetation(layer,manifest,folder)
    from preview_vegetation import render as render_vegetation_library
    render_vegetation_library(output/'library')
    stats=dict(buildingObjects=len(object_rows),ordinaryBuildingObjects=sum(r['category']=='building' for r in object_rows),detailedModelGroups=sum(r['category']=='landmark' for r in object_rows),vegetationInstances=len(vegetation),treeTemplates=len(layer['templates']),
        uniqueObjectTriangles=sum(c['triangles'] for c in manifest['chunks'] if c.get('objectGeometry')),expandedObjectTriangles=sum(manifest['chunks'][i['mesh']]['triangles'] for i in manifest['instances'] if manifest['chunks'][i['mesh']].get('objectGeometry')),
        materials=len(manifest['materials']),textures=len(used_textures),textureBytes=sum(x['bytes'] for x in used_textures.values()),groundFallbacks=len(fallback),terrainDatumBindings=len(datum_bindings),maxNearestGroundDistanceM=max((r['distanceM'] for r in fallback),default=0),roofOnlyAnchors=sum(a['sourceBaseM'] is None for a in anchors.values()))
    apply_variation(layer,manifest)
    layer['stats']=stats;layer['baseVersion']=args.base.name;city['objectLayer']=layer;city['limitations']=[s for s in city['limitations'] if 'buildings and vegetation' not in s]
    city['limitations']+=['Building atlases contain source baked lighting: PBR is an appearance approximation, not measured material data.', 'Vegetation retains source display class and base transform with deterministic ±8% uniform size variation and vertical yaw; crowns crossing the region border are not sliced.', 'Buildings are rigidly seated at one ground anchor; terrain around foundations is not regraded.']
    report['objectLayer']=dict(passed=True,**stats);report['export']['objectLayer']=stats
    manifest['extentMetres']=max(x1-x0,y1-y0);manifest['textures']={**manifest.get('textures',{}),**used_textures}
    manifest['stats'].update(uniqueTriangles=sum(c['triangles'] for c in manifest['chunks']),expandedTriangles=sum(manifest['chunks'][i['mesh']]['triangles'] for i in manifest['instances']),streetInstances=len(vegetation))
    report['export'].update(triangles=manifest['stats']['uniqueTriangles'],expandedTriangles=manifest['stats']['expandedTriangles'],chunks=len(manifest['chunks']),downloadBytes=sum((folder/Path(c['file']).name).stat().st_size for c in manifest['chunks']),textureBytes=stats['textureBytes'])
    (folder/'scene.json').write_text(json.dumps(manifest,ensure_ascii=False,separators=(',',':')))
    export_glb(manifest,folder);report['export']['glbBytes']=(folder/'model.glb').stat().st_size
    save_canonical(output/'canonical/urban-model.json',city)
    (output/'canonical/validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    (output/'textures').mkdir(exist_ok=True)
    for name in manifest['textures']:shutil.copy2(folder/name,output/'textures'/name)
    print('OBJECT LAYER',json.dumps(stats),flush=True)

if __name__=='__main__':main()
