"""Connected-water excavation on complete source domains, before tile clipping.

Source Water_area strips determine connectivity; final surface ownership defines
the bank. Road cuts therefore do not turn river fragments into isolated ponds.
"""
import gzip, hashlib, json, gc
from pathlib import Path
import numpy as np
import shapely as sh
from shapely.geometry.polygon import orient
from object_geometry import pack

DEPTH=2.
GRID=1e-5
from waterfront_finish import TEXTURE,MATERIAL,POLICY as FINISH_POLICY
POLICY=dict(version=4,finish=FINISH_POLICY,depthM=DEPTH,plateWidthM=1.,plateHeightM=.5,rowOffsetM=.5,
 selection='all source Water_area fragments open at the acquisition boundary plus explicit Water_line connections before road/pier cuts; preserve closed inland water; a river may leave and re-enter the acquired area',
 geometry='restore source water below confirmed Bridge_area spans, excluding piers; union complete final water domains, lower selected water by exactly 2 m, then build banks before transport tile clipping; no walls at acquisition cuts',
 heights='retain the source water profile; close the existing bank lip up to the adjacent ground surface',
 uv=FINISH_POLICY['uv'])


def polygons(g):
    if g.geom_type=='Polygon':return [g]
    return [p for sub in getattr(g,'geoms',[]) for p in polygons(sub)]

def source_network(features,bounds):
    pieces=[];lines=[];steps=[]
    for r in features:
        if r.get('layer')=='Water_line' and len(r.get('coordinates',[]))>=2:
            lines.append(sh.LineString(np.asarray(r['coordinates'])[:,:2]));steps.append(r.get('source',{}).get('coordinateStepM',.02));continue
        if r.get('layer')!='Water_area' or r.get('geometryType')!='polygon':continue
        xy=np.asarray(r['coordinates'],float)[:,:2]
        if len(xy)<3:continue
        triangles=sh.polygons(np.stack([xy[:-2],xy[1:-1],xy[2:]],axis=1))
        pieces.extend(triangles[sh.area(triangles)>1e-8])
    if not pieces:return sh.Polygon(),dict(sourceComponents=0)
    domain=sh.union_all(sh.set_precision(sh.make_valid(pieces),GRID),grid_size=GRID)
    components=polygons(domain);extent=sh.box(*bounds)
    # A closed inland lake is never promoted just because it is large.
    candidates=[p for p in components if p.intersection(extent.boundary).length>GRID and p.intersection(extent).area>0]
    if not candidates:return sh.Polygon(),dict(sourceComponents=len(components))
    # A cropped river can leave and re-enter the scene. All open fragments
    # need the same treatment; proximity never promotes a closed inland pond.
    chosen={components.index(seed) for seed in candidates};nodes=components+lines;tree=sh.STRtree(nodes)
    tolerance=min(.05,max(steps,default=.02)*2)
    pending=list(chosen)
    while pending:
        i=pending.pop()
        for j in tree.query(nodes[i],predicate='dwithin',distance=tolerance):
            j=int(j)
            # Only explicit channel lines can bridge a polygon gap. Never join
            # nearby ponds merely because they are close to the river.
            if j in chosen or (i<len(components) and j<len(components)):continue
            chosen.add(j);pending.append(j)
    selected=[components[i] for i in sorted(chosen) if i<len(components)]
    network=sh.union_all(selected,grid_size=GRID)
    return network,dict(sourceComponents=len(components),boundarySourceComponents=len(candidates),connectedSourceComponents=len(selected),explicitChannelLinks=sum(i>=len(components) for i in chosen),sourceNetworkAreaM2=network.area)

def source_polygons(features,layer):
    pieces=[]
    for r in features:
        if r.get('layer')!=layer or r.get('geometryType')!='polygon':continue
        xy=np.asarray(r['coordinates'],float)[:,:2]
        if len(xy)<3:continue
        tris=sh.polygons(np.stack([xy[:-2],xy[1:-1],xy[2:]],axis=1))
        pieces.extend(tris[sh.area(tris)>1e-8])
    return sh.union_all(pieces,grid_size=GRID) if pieces else sh.Polygon()

def bridge_continuation(features,network,domain,bounds):
    # Bridge polygons are evidence of an elevated crossing. Do not infer a
    # connection across an arbitrary road, dam or nearby isolated pond.
    spans=source_polygons(features,'Bridge_area')
    piers=source_polygons(features,'Pier_quarter')
    allowed=sh.intersection(network,spans,grid_size=GRID).intersection(sh.box(*bounds))
    if not piers.is_empty:allowed=sh.difference(allowed,piers,grid_size=GRID)
    fill=sh.difference(allowed,domain,grid_size=GRID)
    return fill,allowed

def bridge_geometry(fill,terrain_path,origin):
    if fill.is_empty:return np.empty((0,3,8)),np.empty(0,dtype=object),np.empty((0,3))
    terrain=np.load(terrain_path);encoded=terrain['polygons'];coeff=terrain['planes']
    cells=[];planes=[];triangles=[];sh.prepare(fill)
    for start in range(0,len(encoded),50000):
        batch=sh.from_wkb(encoded[start:start+50000]);hit=np.flatnonzero(sh.intersects(fill,batch))
        for i in hit:
            g=sh.intersection(fill,batch[i],grid_size=GRID);c=coeff[start+i]
            for p in polygons(g):
                if p.area<1e-9:continue
                cells.append(p);planes.append(c)
                for t in sh.get_parts(sh.constrained_delaunay_triangles(p)):
                    xy=np.asarray(t.exterior.coords)[:3,:2]
                    if np.linalg.det(xy[1:]-xy[0])<0:xy=xy[::-1]
                    xyz=np.column_stack([xy[:,0]-origin[0],xy@c[:2]+c[2]-DEPTH-origin[2],origin[1]-xy[:,1]])
                    n=np.cross(xyz[1]-xyz[0],xyz[2]-xyz[0]);n/=np.linalg.norm(n)
                    triangles.append(np.column_stack([xyz,np.tile(n,(3,1)),xy]))
    covered=sum(p.area for p in cells)
    if abs(covered-fill.area)>max(.1,fill.area*1e-6):raise ValueError(f'Terrain coverage missing below bridge: {covered} / {fill.area} m2')
    return np.asarray(triangles),np.asarray(cells,dtype=object),np.asarray(planes)

def water_domain(rows,network):
    sh.prepare(network)
    cells=sh.from_geojson([json.dumps(r['geometry']) for r in rows])
    selected=sh.covers(network,sh.point_on_surface(cells))
    batches=[];picked=cells[selected]
    for start in range(0,len(picked),30000):
        batch=picked[start:start+30000]
        try:
            g=sh.coverage_union_all(batch)
            if not g.is_valid:raise ValueError('overlap')
        except Exception:g=sh.union_all(batch,grid_size=GRID)
        batches.append(g)
    return cells,selected,sh.union_all(batches,grid_size=GRID)

def bank_segments(domain,bounds):
    """Each ring has one deterministic UV phase, retained across all tile cuts."""
    starts=[];ends=[];chainage=[];ring_ids=[];removed=0.;sh.prepare(domain)
    extent=sh.box(*bounds);ring_id=0
    for p in sorted(polygons(domain),key=lambda p:(p.bounds,-p.area)):
        p=orient(p,sign=1.)
        for ring in [p.exterior,*p.interiors]:
            xy=np.asarray(sh.segmentize(sh.LineString(ring.coords),4.).coords)[:-1,:2]
            first=np.lexsort((xy[:,1],xy[:,0]))[0];xy=np.roll(xy,-first,axis=0)
            lengths=np.linalg.norm(np.roll(xy,-1,axis=0)-xy,axis=1)
            distance=np.r_[0,np.cumsum(lengths)]
            for i,a in enumerate(xy):
                b=xy[(i+1)%len(xy)];length=lengths[i]
                if length<1e-6:continue
                # Only the outer acquisition edge is artificial. Internal grid
                # lines are deliberately absent from this algorithm.
                cut=any(abs(a[k]-v)<GRID*2 and abs(b[k]-v)<GRID*2 for k,v in [(0,bounds[0]),(0,bounds[2]),(1,bounds[1]),(1,bounds[3])])
                if cut:removed+=length;continue
                # Precision-grid slits are not land. Avoid a tall wall on a
                # micron-wide seam where water is present on both sides.
                outward=np.array([b[1]-a[1],a[0]-b[0]])/length
                if sh.covers(domain,sh.Point((a+b)/2+outward*GRID*4)):continue
                starts.append(a);ends.append(b);chainage.append(distance[i:i+2]);ring_ids.append(ring_id)
            ring_id+=1
    return np.asarray(starts),np.asarray(ends),np.asarray(chainage),np.asarray(ring_ids),removed

def wall_geometry(domain,cells,planes,ground_rows,bounds,origin):
    a,b,along,rings,removed=bank_segments(domain,bounds)
    if not len(a):return np.empty((0,3,8)),{},None
    delta=b-a;length=np.linalg.norm(delta,axis=1);normal=np.column_stack((delta[:,1],-delta[:,0]))/length[:,None]
    midpoint=(a+b)/2;tree=sh.STRtree(cells)
    idx=tree.nearest(sh.points(midpoint))
    base=np.stack([np.einsum('ij,ij->i',a,planes[idx,:2])+planes[idx,2],np.einsum('ij,ij->i',b,planes[idx,:2])+planes[idx,2]],axis=1)
    # Probe the land side, never the overpass projected above the shore.
    probes=sh.points(midpoint+normal*.015);probe_tree=sh.STRtree(probes)
    top=base.copy();matched=np.zeros(len(a),bool)
    batch=[];processed=0
    def apply(batch):
        if not batch:return
        geoms=sh.from_geojson([json.dumps(r['geometry']) for r in batch])
        ri,si=probe_tree.query(geoms,predicate='covers')
        if not len(si):return
        coeff=np.asarray([r['heightPlane'] for r in batch])[ri]
        z=np.stack([np.einsum('ij,ij->i',a[si],coeff[:,:2])+coeff[:,2],np.einsum('ij,ij->i',b[si],coeff[:,:2])+coeff[:,2]],axis=1)
        # Only the bordering ground skin is a bank top; elevated decks and
        # unrelated underground surfaces must never become vertical banks.
        good=(abs(z-base[si]).max(1)<.5)
        si=si[good];z=z[good]
        np.maximum.at(top[:,0],si,z[:,0]);np.maximum.at(top[:,1],si,z[:,1]);matched[si]=True
    for row in ground_rows:
        if row.get('kind') not in {'land','curb_top','green_curb_top','roadbed_flat'}:continue
        batch.append(row)
        if len(batch)==4096:
            apply(batch);batch=[];processed+=4096
            if processed%262144==0:print('BANK GROUND CELLS',processed,'matched',int(matched.sum()),'/',len(a),flush=True)
    apply(batch)
    # Share endpoint heights so a material boundary cannot leave a crack.
    keys=np.rint(np.concatenate([a,b])/GRID).astype(np.int64)
    _,inv=np.unique(keys,axis=0,return_inverse=True);heights=np.full(inv.max()+1,-np.inf)
    np.maximum.at(heights,inv,np.r_[top[:,0],top[:,1]])
    top=np.column_stack([heights[inv[:len(a)]],heights[inv[len(a):]]])
    stats=dict(bankLengthM=float(length.sum()),bankSegments=len(a),rings=int(rings.max()+1),excludedAcquisitionEdgeM=removed,adjacentGroundSegments=int(matched.sum()),bankLipMaxM=float((top-base).max()))
    banks=dict(a=a,b=b,base=base,top=top,chainage=along,rings=rings)
    return bank_triangles(banks,origin),stats,banks

def bank_triangles(banks,origin):
    a,b,base,top,along=(banks[k] for k in ('a','b','base','top','chainage'))
    ox,oy,oz=origin
    at=np.column_stack([a[:,0]-ox,top[:,0]-oz,oy-a[:,1]])
    bt=np.column_stack([b[:,0]-ox,top[:,1]-oz,oy-b[:,1]])
    ab=at.copy();bb=bt.copy();ab[:,1]=base[:,0]-DEPTH-oz;bb[:,1]=base[:,1]-DEPTH-oz
    quads=np.stack([at,bt,bb,ab],axis=1)
    # 4 x 2 metre repeat; V=0 at the original water line. An existing 10 cm
    # curb/paving lip is covered too without rescaling the four main courses.
    uv=np.stack([np.column_stack([along[:,0]/4,(base[:,0]-top[:,0])/2]),np.column_stack([along[:,1]/4,(base[:,1]-top[:,1])/2]),np.column_stack([along[:,1]/4,np.ones(len(a))]),np.column_stack([along[:,0]/4,np.ones(len(a))])],axis=1)
    xyz=quads[:,[0,1,2,0,2,3]].reshape(-1,3,3);tex=uv[:,[0,1,2,0,2,3]].reshape(-1,3,2)
    normals=np.cross(xyz[:,1]-xyz[:,0],xyz[:,2]-xyz[:,0]);normals/=np.maximum(np.linalg.norm(normals,axis=1,keepdims=True),1e-20)
    triangles=np.concatenate([xyz,np.repeat(normals[:,None,:],3,axis=1),tex],axis=2)
    return triangles

def make_texture(folder):
    from waterfront_finish import install_texture
    return install_texture(folder)


def lower_chunk(folder,c,network,origin):
    sh.prepare(network)
    path=Path(folder)/Path(c['file']).name;data=gzip.decompress(path.read_bytes())
    words=np.frombuffer(data[:c['vertexBytes']],'<u4').reshape(-1,8).copy();indices=np.frombuffer(data[c['vertexBytes']:],'<u4').reshape(-1,3)
    pos=words.view('<f4')[:,:3];center=pos[indices].astype(float).mean(1)
    xy=np.column_stack([center[:,0]+origin[0],origin[1]-center[:,2]])
    mask=sh.covers(network,sh.points(xy))
    # Separate shared vertices if a boundary contacts preserved water.
    selected_ids=np.unique(indices[mask]);other_ids=np.unique(indices[~mask]);shared=np.intersect1d(selected_ids,other_ids)
    if len(shared):
        old_count=len(words);words=np.concatenate([words,words[shared]]);remap=np.arange(old_count,dtype=np.uint32);remap[shared]=old_count+np.arange(len(shared));indices=indices.copy();indices[mask]=remap[indices[mask]];selected_ids=np.unique(indices[mask])
    words.view('<f4')[selected_ids,1]-=DEPTH
    path.write_bytes(gzip.compress(words.tobytes()+indices.tobytes(),compresslevel=6,mtime=0))
    pos=words.view('<f4')[:,:3];c.update(vertexBytes=words.nbytes,vertexCount=len(words),bounds=dict(min=pos.min(0).tolist(),max=pos.max(0).tolist()))
    return mask

def install(features,water_rows,ground_rows,scene,folder,bounds,bank_cache_key=None):
    if scene.get('waterfront'):raise ValueError('Waterfront already installed; never lower twice')
    network,stats=source_network(features,bounds)
    if network.is_empty:return None
    # The immutable multi-million-cell input is acyclic and lives until the end
    # of this stage. Do not repeatedly rescan it during streamed shore queries.
    gc.freeze()
    print('WATER SOURCE NETWORK',stats,flush=True)
    cells,selected,domain=water_domain(water_rows,network)
    if domain.is_empty:return None
    print('WATER GLOBAL UNION',len(polygons(domain)),domain.area,flush=True)
    planes=np.asarray([r['heightPlane'] for r in water_rows],float)
    fill,spans=bridge_continuation(features,network,domain,bounds)
    bridge_triangles,bridge_cells,bridge_planes=bridge_geometry(fill,Path(folder).parent/'terrain.npz',scene['origin'])
    print('WATER BELOW BRIDGES',fill.area,'cells',len(bridge_cells),flush=True)
    if len(bridge_cells):
        domain=sh.union_all([domain,fill],grid_size=GRID)
        wall_cells=np.r_[cells[selected],bridge_cells];wall_planes=np.r_[planes[selected],bridge_planes]
    else:wall_cells=cells[selected];wall_planes=planes[selected]
    folder=Path(folder);cache=folder/'water-bank-cache.json';bankfile=folder/'water-bank-segments.npz'
    domain_hash=hashlib.sha256(sh.to_wkb(domain)).hexdigest()
    cached=json.loads(cache.read_text()) if cache.exists() else {}
    if bank_cache_key and cached.get('inputKey')==bank_cache_key and cached.get('domainSha256')==domain_hash and bankfile.exists() and cached.get('bankSha256')==hashlib.sha256(bankfile.read_bytes()).hexdigest():
        banks=dict(np.load(bankfile));bank_stats=cached['stats'];triangles=bank_triangles(banks,scene['origin'])
        print('REUSE VERIFIED BANK GROUND HEIGHTS',len(banks['a']),flush=True)
    else:
        triangles,bank_stats,banks=wall_geometry(domain,wall_cells,wall_planes,ground_rows,bounds,scene['origin'])
    if banks is not None and bank_cache_key:
        np.savez_compressed(bankfile,**banks)
        cache.write_text(json.dumps(dict(inputKey=bank_cache_key,domainSha256=domain_hash,bankSha256=hashlib.sha256(bankfile.read_bytes()).hexdigest(),stats=bank_stats)))
    from waterfront_finish import finished_bank,cornice_geometry
    if banks is not None:
        cornice,finish_stats=cornice_geometry(banks,scene['origin'],domain)
        triangles=np.concatenate([finished_bank(banks,scene['origin']),cornice])
        bank_stats.update(finish_stats)
    folder=Path(folder);folder.mkdir(exist_ok=True,parents=True)
    (folder/'water-network.wkb').write_bytes(sh.to_wkb(network));(folder/'water-bank-domain.wkb').write_bytes(sh.to_wkb(domain))
    (folder/'water-bridge-continuation.wkb').write_bytes(sh.to_wkb(fill))
    (folder/'water-bridge-spans.wkb').write_bytes(sh.to_wkb(spans))
    if banks:np.savez_compressed(folder/'water-bank-segments.npz',**banks)
    stats.update(bank_stats,loweredSurfaceCells=int(selected.sum()),preservedSurfaceCells=int((~selected).sum()),selectedAreaM2=domain.area,visibleWaterComponents=len(polygons(domain)))
    changed=[];lowered=0;preserved=0
    for c in scene['chunks']:
        if c.get('category',c['name'])!='water':continue
        mask=lower_chunk(folder,c,network,scene['origin']);changed.append(c['id']);lowered+=int(mask.sum());preserved+=int((~mask).sum())
    added_surfaces=[]
    if len(bridge_triangles):
        water_material=next(r['material'] for r in water_rows)
        cid=len(scene['chunks']);name=f'mesh-{cid:03d}-bridge-water.bin.gz'
        mesh=pack(bridge_triangles,np.full(len(bridge_triangles),water_material),folder/name)
        if mesh is None:
            # A precision-grid residue can collapse completely in Float32.
            # Retain its topology repair, but never publish an empty mesh.
            assert fill.area<.0001, 'A real bridge-water gap collapsed during packing'
            stats['subprecisionBridgeRepairAreaM2']=fill.area
            bridge_triangles=np.empty((0,3,8));bridge_cells=[]
        else:
            scene['chunks'].append(dict(id=cid,name='water-bridge-continuation',category='water',file='/prototype/assets/full/'+name,**mesh))
            scene['instances'].append(dict(mesh=cid,matrix=[1,0,0,0,0,1,0,0,0,0,1,0]));changed.append(cid)
            for key in ('uniqueTriangles','expandedTriangles'):scene['stats'][key]+=mesh['triangles']
            for i,(g,c) in enumerate(zip(bridge_cells,bridge_planes)):
                added_surfaces.append(dict(id=f'waterfront-bridge:{i}',geometry=json.loads(sh.to_geojson(g)),heightPlane=[*c[:2],c[2]-DEPTH],kind='water',tiers=[0],material=water_material,owner='bridge-water-continuation',waterfrontDepthM=DEPTH))
    stats.update(bridgeWaterAreaM2=fill.area,bridgeWaterCells=len(bridge_cells),bridgeWaterTriangles=mesh['triangles'] if len(bridge_triangles) else 0)
    mid=len(scene['materials']);scene['materials'].append(MATERIAL.copy());scene['textures'].update(make_texture(folder))
    cid=len(scene['chunks']);name=f'mesh-{cid:03d}-waterfront.bin.gz'
    mesh=pack(triangles,np.full(len(triangles),mid),folder/name)
    scene['chunks'].append(dict(id=cid,name='waterfront-bank',category='waterfront-bank',file='/prototype/assets/full/'+name,**mesh))
    scene['instances'].append(dict(mesh=cid,matrix=[1,0,0,0,0,1,0,0,0,0,1,0]));changed.append(cid)
    for key in ('uniqueTriangles','expandedTriangles'):scene['stats'][key]+=mesh['triangles']
    stats.update(loweredWaterTriangles=lowered,preservedWaterTriangles=preserved,bankTriangles=mesh['triangles'])
    scene['waterfront']=dict(policy=POLICY,stats=stats,material=mid,finish=dict(policy=FINISH_POLICY,stats=finish_stats if banks is not None else {}))
    updates=[dict(id=r['id'],heightPlane=[*r['heightPlane'][:2],r['heightPlane'][2]-DEPTH],waterfrontDepthM=DEPTH) for r,keep in zip(water_rows,selected) if keep]
    return dict(changedChunks=changed,surfaces=updates,newSurfaces=added_surfaces,waterfront=scene['waterfront'])
