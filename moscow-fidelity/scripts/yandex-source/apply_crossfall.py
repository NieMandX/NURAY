"""Apply a solved road profile to asphalt, its paint and boundary construction.

Lawns and the general pedestrian/terrain relief retain their source slope.
Only short pedestrian entrance ramps meet the adjusted roadway; cut/fill faces
close the road edge instead of tilting a whole neighbourhood to match asphalt.
"""
import argparse,collections,gzip,json,shutil
from pathlib import Path
import numpy as np
import shapely as sh
from build_scene import Builder,Terrain,cdt,lines,polygons,union,dump
from object_geometry import pack,decode_normals
from canonical_store import copy_asset

class RoadField:
    def __init__(self,path):
        d=np.load(path);self.xy=d['xy'];self.z0=d['z0'];self.z=d['z'];self.polygons=sh.polygons(self.xy);self.tree=sh.STRtree(self.polygons)
        from scipy.spatial import cKDTree
        self.vertices,self.first=np.unique(self.xy.reshape(-1,2),axis=0,return_index=True);self.vertex_tree=cKDTree(self.vertices)
        design=np.concatenate([self.xy,np.ones((*self.xy.shape[:2],1))],axis=2)
        self.delta=np.linalg.solve(design,(self.z-self.z0)[:,:,None])[:,:,0]
        self.original=np.linalg.solve(design,self.z0[:,:,None])[:,:,0]
        self.height=np.linalg.solve(design,self.z[:,:,None])[:,:,0]
    def sample(self,xy):
        xy=np.asarray(xy).reshape(-1,2)
        # Triangle soup repeats every corner several times. Evaluate each
        # coordinate once, and resolve known road corners before a costly
        # polygon-nearest query. The interpolation/nearest policy is unchanged.
        xy,inverse=np.unique(xy,axis=0,return_inverse=True)
        distance,vertex=self.vertex_tree.query(xy);exact=distance<1e-9;corner=self.first[vertex[exact]]
        delta=np.empty(len(xy));original=np.empty(len(xy));offroad=np.zeros(len(xy))
        original[exact]=self.z0.ravel()[corner];delta[exact]=(self.z-self.z0).ravel()[corner]
        if (~exact).any():
            other=xy[~exact];pts=sh.points(other);ids=self.tree.nearest(pts)
            nearest=sh.get_point(sh.shortest_line(pts,self.polygons[ids]),1);q=sh.get_coordinates(nearest)
            delta[~exact]=(q*self.delta[ids,:2]).sum(1)+self.delta[ids,2]
            original[~exact]=(q*self.original[ids,:2]).sum(1)+self.original[ids,2]
            offroad[~exact]=np.linalg.norm(q-other,axis=1)
        return delta[inverse],original[inverse],offroad[inverse]

def unpack(root,c):
    raw=gzip.decompress((root/c['file']).read_bytes());u=np.frombuffer(raw[:c['vertexBytes']],'<u4').reshape(-1,8);ix=np.frombuffer(raw[c['vertexBytes']:],'<u4').reshape(-1,3)
    f=u.view('<f4');t=np.concatenate([f[ix,:3],decode_normals(u[:,3])[ix],f[ix,4:6]],axis=2).astype(float)
    return t,(u[ix[:,0],6]&0x7fffffff),f[ix,7]

def normals(t):
    n=np.cross(t[:,1,:3]-t[:,0,:3],t[:,2,:3]-t[:,0,:3]);n/=np.maximum(np.linalg.norm(n,axis=1,keepdims=True),1e-20);t[:,:,3:6]=n[:,None,:]

def cut_fill_faces(xy,terrain,field,land_offset,alt):
    """Batch the same signed road-edge quads; avoid per-edge spatial queries."""
    xy=np.asarray(xy);keep=field.sample(xy.mean(1))[2]>=.065;xy=xy[keep]
    if not len(xy):return np.empty((0,3,8))
    direction=xy[:,1]-xy[:,0];length=np.linalg.norm(direction,axis=1)
    outward=np.column_stack([direction[:,1],-direction[:,0]])/length[:,None]*.015
    base=terrain.sample(xy.reshape(-1,2)).reshape(-1,2)
    old=base+land_offset((xy+outward[:,None]).reshape(-1,2)).reshape(-1,2)
    delta=field.sample(xy.reshape(-1,2))[0].reshape(-1,2);bottom=base+.035+delta
    connection=np.maximum(bottom,np.minimum(old,bottom+.1))
    keep=np.max(abs(connection-old),axis=1)>=.003;xy,old,connection,length=xy[keep],old[keep],connection[keep],length[keep]
    a=np.stack([xy[:,:,0],old-alt,-xy[:,:,1]],axis=2);b=np.stack([xy[:,:,0],connection-alt,-xy[:,:,1]],axis=2)
    t=np.zeros((len(xy)*2,3,8));t[::2,:,:3]=np.stack([a[:,0],a[:,1],b[:,1]],axis=1);t[1::2,:,:3]=np.stack([a[:,0],b[:,1],b[:,0]],axis=1)
    distance=np.column_stack([np.zeros(len(xy)),length]);uv0=np.stack([distance,old/3],axis=2);uv1=np.stack([distance,connection/3],axis=2)
    t[::2,:,6:8]=np.stack([uv0[:,0],uv0[:,1],uv1[:,1]],axis=1);t[1::2,:,6:8]=np.stack([uv0[:,0],uv1[:,1],uv1[:,0]],axis=1);normals(t)
    return t

def reproject_paint(t,m,tint,field):
    """Split paint at solved profile edges; vertex-only lifting bridges kinks."""
    xy=t[:,:,[0,2]]*[1,-1];_,h,distance=field.sample(xy.reshape(-1,2))
    hit=(abs(t[:,:,1]-h.reshape(-1,3)-.020)<.025).all(1)&(distance.reshape(-1,3).max(1)<.03)
    out_t=[t[~hit]];out_m=[m[~hit]];out_tint=[tint[~hit]];source_area=0.;result_area=0.
    selected=np.flatnonzero(hit);polys=sh.polygons(xy[hit]);pi,fi=field.tree.query(polys,predicate='intersects')
    intersections=sh.intersection(polys[pi],field.polygons[fi]);order=np.argsort(pi,kind='stable')
    last=-1
    for j in order:
        k=int(pi[j]);g=intersections[j]
        if g.is_empty or g.area<1e-10:continue
        if k!=last:
            idx=selected[k];design=np.column_stack([xy[idx],np.ones(3)])
            if abs(np.linalg.det(design))<1e-10:continue
            attrs=np.linalg.solve(design,t[idx]);colors=np.linalg.solve(design,tint[idx]);last=k
        points=cdt(g)
        if not len(points):continue
        reverse=np.linalg.det(points[:,1:]-points[:,:1])<0;points[reverse]=points[reverse][:,[0,2,1]]
        a=np.concatenate([points,np.ones((*points.shape[:2],1))],axis=2);tris=a@attrs
        tris[:,:,1]=a@field.height[fi[j]]+.020;normals(tris)
        out_t.append(tris);out_m.append(np.full(len(tris),m[idx]));out_tint.append(a@colors);result_area+=g.area
    source_area=float(sh.area(polys).sum())
    return np.concatenate(out_t),np.concatenate(out_m),np.concatenate(out_tint),dict(sourceTriangles=int(hit.sum()),sourceAreaM2=source_area,resultAreaM2=result_area,clippedAreaM2=source_area-result_area)

def apply(base,out,field_path):
    assert not out.exists();out.mkdir(parents=True)
    for name in ('canonical','textures','meshes'):shutil.copytree(base/name,out/name,copy_function=copy_asset)
    for name in ('tileset.json','build-audit.json','moscow-style.json','plant-placement-audit.json.gz','placement-masks.json.gz','independent-placement-counts.json'):copy_asset(base/name,out/name)
    if (base/'survey-terrain.json').exists():copy_asset(base/'survey-terrain.json',out/'survey-terrain.json')
    full=out/'canonical/full';scene=json.loads((full/'scene.json').read_text());city=json.loads((out/'canonical/urban-model.json').read_text());masks=json.loads(gzip.decompress((out/'placement-masks.json.gz').read_bytes()))
    field=RoadField(field_path);finished={r['kind']:sh.from_wkb(bytes.fromhex(r['geometry'])) for r in masks['finishedGround']}
    offsets={r['kind']:r['offsetM'] for r in masks['finishedGround']};road=finished['road'];curb=finished['road-curb'];ped=finished['ped']
    for g in finished.values():sh.prepare(g)
    # The domain of a crossing is inherited from the existing open curb mouths.
    entrances=road.boundary.difference(curb.buffer(.035)).intersection(ped.buffer(.05))
    ramp=entrances.buffer(4).intersection(ped).difference(curb);ramp_boundary=sh.STRtree(list(lines(entrances)))
    def ramp_delta(xy):
        xy=np.asarray(xy);pts=sh.points(xy);ids=ramp_boundary.nearest(pts)
        distance=sh.distance(pts,ramp_boundary.geometries[ids]);u=np.clip(distance/4,0,1)
        return field.sample(xy)[0]*(1-3*u*u+2*u*u*u)
    changed=[];counts=collections.Counter();ramp_mats=collections.Counter();paint_reports=[]
    for c in scene['chunks']:
        if c['name'] not in ('land','paint','road-curbs'):continue
        t,m,tint=unpack(full,c);xy=t[:,:,[0,2]]*[1,-1];hit=np.zeros(len(t),bool)
        if c['name']=='land':hit=m==0
        elif c['name']=='road-curbs':hit[:]=True
        else:
            t,m,tint,paint_report=reproject_paint(t,m,tint,field);hit=np.ones(len(t),bool);counts['paint']+=paint_report['sourceTriangles'];paint_reports.append(paint_report)
        if hit.any() and c['name']!='paint':
            delta,original,_=field.sample(xy[hit].reshape(-1,2));delta=delta.reshape(-1,3)
            if c['name']=='land':t[hit,:,1]=original.reshape(-1,3)+delta
            else:t[hit,:,1]+=delta
            changed_t=t[hit].copy();normals(changed_t);t[hit]=changed_t;counts[c['name']]+=int(hit.sum())
        if c['name']=='land' and not ramp.is_empty:
            candidate=np.isin(m,[7,12,13,14,15,16])
            candidate[candidate]=sh.intersects(ramp,sh.polygons(xy[candidate]))
            if candidate.any():
                out_t=[t[~candidate]];out_m=[m[~candidate]];out_tint=[tint[~candidate]]
                for original,mat,color,poly in zip(t[candidate],m[candidate],tint[candidate],sh.polygons(xy[candidate])):
                    original_xy=original[:,[0,2]]*[1,-1];design=np.column_stack([original_xy,np.ones(3)])
                    if abs(np.linalg.det(design))<1e-10:continue
                    attrs=np.linalg.solve(design,original);colors=np.linalg.solve(design,color)
                    for g,is_ramp in ((poly.difference(ramp),False),(poly.intersection(ramp),True)):
                        if is_ramp:g=sh.segmentize(g,1.)
                        points=cdt(g)
                        if not len(points):continue
                        reverse=np.linalg.det(points[:,1:]-points[:,:1])<0;points[reverse]=points[reverse][:,[0,2,1]]
                        a=np.concatenate([points,np.ones((*points.shape[:2],1))],axis=2);tris=a@attrs
                        if is_ramp:tris[:,:,1]+=ramp_delta(points.reshape(-1,2)).reshape(-1,3);normals(tris);ramp_mats[int(mat)]+=len(tris)
                        out_t.append(tris);out_m.append(np.full(len(tris),mat));out_tint.append(a@colors)
                t=np.concatenate(out_t);m=np.concatenate(out_m);tint=np.concatenate(out_tint);hit=np.ones(len(t),bool)
        if hit.any():
            c.update(pack(t,m,full/c['file'],tints=None if not np.any(tint) else tint));changed.append(c['id']);print('PROFILE CHUNK',c['id'],c['name'],flush=True)
    b=Builder.__new__(Builder);b.out=out;b.full=full;b.alt=scene['origin'][2];b.materials=scene['materials'];b.chunks=scene['chunks'];b.instances=scene['instances'];b.batches=collections.defaultdict(list);b.batch_counts=collections.Counter();b.terrain=Terrain(np.load(out/'canonical/terrain.npz')['triangles'])
    def land_offset(xy):
        p=sh.points(xy);result=np.zeros(len(p))
        for k,g in finished.items():
            if k not in ('road','road-curb'):result[sh.covers(g,p)]=offsets[k]
        return result
    skirts=0;edges=[]
    for poly in polygons(sh.orient_polygons(curb)):
        for ring in [poly.exterior,*poly.interiors]:
            p=np.asarray(sh.segmentize(ring,2).coords)
            edges.append(np.stack([p[:-1],p[1:]],axis=1))
    edges=np.concatenate(edges) if edges else np.empty((0,2,2))
    for start in range(0,len(edges),10000):
        t=cut_fill_faces(edges[start:start+10000],b.terrain,field,land_offset,b.alt)
        if len(t):b.add(t,8,'road-cut-fill');skirts+=len(t)//2
    # Side faces of the short entrance ramps meet unchanged terrain/pavement.
    b.boundary_walls(ramp,lambda xy:b.terrain.sample(xy)+.075,lambda xy:b.terrain.sample(xy)+.075+ramp_delta(xy),8,'road-entry-ramp-sides')
    for name in list(b.batches):b.flush(name)
    report=json.loads(field_path.with_name('road-crossfall.json').read_text());report.update(changedChunks=changed,changedTriangles=dict(counts),paintConformsToProfile=paint_reports,pedestrianRampAreaM2=ramp.area,pedestrianRampTriangles=sum(ramp_mats.values()),cutFillBoundarySegments=skirts,
        neighbourPolicy='Lawns and general sidewalks keep their original terrain slope; only 4 m entrance ramps connect open curb mouths; signed retaining faces close cut/fill road edges.')
    # Keep the solved, source-axis evidence in the canonical release.
    copy_asset(field_path,out/'canonical/road-height-field.npz')
    dump(out/'road-crossfall.json',report);scene['stats']=dict(uniqueTriangles=sum(c['triangles'] for c in scene['chunks']),expandedTriangles=sum(scene['chunks'][i['mesh']]['triangles'] for i in scene['instances']))
    revision=('yandex-survey-road-crossfall-6' if city.get('surveyTerrain',{}).get('fairing') else 'yandex-survey-road-crossfall-5') if city.get('surveyTerrain') else 'yandex-road-crossfall-4'
    city['geometryRevision']={'version':revision,'parent':base.name};city['roadCrossfall']=report
    # Camera-only witness: largest corrected road patch near the scene centre.
    delta=np.abs(field.z-field.z0).max(1);centers=field.xy.mean(1);score=delta/(1+np.linalg.norm(centers,axis=1)/800);i=int(np.argmax(score));q=centers[i]
    scene.setdefault('witnessViews',{})['road-crossfall-review']=dict(yaw=-.65,pitch=1.17,distance=130,target=[float(q[0]),float(field.z[i].mean()),float(-q[1])]);scene.setdefault('witnessViewLabels',{})['road-crossfall-review']='Дорога · поперечный профиль'
    dump(full/'scene.json',scene);dump(out/'canonical/urban-model.json',city)
    for name in ('canonical/validation.json','build-audit.json'):
        audit=json.loads((out/name).read_text());audit.update(stats=scene['stats'],roadCrossfall=report);dump(out/name,audit)
    print('ROAD PROFILE APPLIED',report,flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--base',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--field',type=Path,required=True);a=p.parse_args();apply(a.base,a.output,a.field)
