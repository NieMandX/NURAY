"""Apply a local, explicit survey elevation patch to dependent canonical layers.

Re-tessellate surface skins at the new TIN, keep source XY/materials/UVs, seat
rigid buildings and common plant instances, then run the shared road solver.
"""
import argparse,collections,gzip,hashlib,json,pickle,shutil,types
from pathlib import Path
import numpy as np
import shapely as sh
from build_scene import Builder,Terrain,cdt,union,polygons,lines,metadata,dump
from apply_crossfall import unpack,normals
from object_geometry import pack
from canonical_store import copy_asset
from survey_terrain import safe_sample
from pyproj import Transformer


def clip_scalar(vertices,values,threshold,greater):
    result=[]
    for i,a in enumerate(vertices):
        b=vertices[(i+1)%len(vertices)];u=values[i]-threshold;v=values[(i+1)%len(vertices)]-threshold
        ina=u>=-1e-10 if greater else u<=1e-10;inb=v>=-1e-10 if greater else v<=1e-10
        if ina:result.append(a)
        if ina!=inb and abs(u-v)>1e-15:result.append(a+(b-a)*u/(u-v))
    return np.array(result)


class Reproject:
    def __init__(self,old,new,patch,rect,alt):self.old,self.new,self.patch,self.rect,self.alt=old,new,patch,rect,alt
    def delta(self,xy):return safe_sample(self.new,xy)-safe_sample(self.old,xy)
    def mesh(self,t,m,tint,bank=False):
        xy=t[:,:,[0,2]]*[1,-1];minimum=xy.min(1);maximum=xy.max(1);x0,y0,x1,y1=self.rect.bounds
        selected=(minimum[:,0]<=x1)&(maximum[:,0]>=x0)&(minimum[:,1]<=y1)&(maximum[:,1]>=y0)
        # Zero-change regions retain original vertices/normals bit-for-bit.
        result=[t[~selected]];materials=[m[~selected]];colors=[tint[~selected]]
        changed=0
        for idx in np.flatnonzero(selected):
            pts=xy[idx];original=t[idx];color=tint[idx]
            determinant=np.linalg.det(pts[1:]-pts[:1]);pieces=[]
            if abs(determinant)>1e-7:
                poly=sh.Polygon(pts);attrs=np.linalg.solve(np.column_stack([pts,np.ones(3)]),np.column_stack([original,color]))
                for g in [poly.difference(self.rect),*[poly.intersection(self.patch.polygons[i]) for i in self.patch.tree.query(poly,predicate='intersects')]]:
                    p=cdt(g)
                    if not len(p):continue
                    reverse=(np.linalg.det(p[:,1:]-p[:,:1])*determinant)<0;p[reverse]=p[reverse][:,[0,2,1]]
                    a=np.concatenate([p,np.ones((*p.shape[:2],1))],axis=2);pieces.append(a@attrs)
            else:
                # Vertical faces: split in their line parameter at terrain edges.
                j,k=np.unravel_index(np.argmax(np.linalg.norm(pts[:,None]-pts[None,:],axis=2)),(3,3));a,q=pts[j],pts[k];d=q-a;length2=d@d
                if length2<1e-14:pieces=[np.column_stack([original,color])[None]]
                else:
                    line=sh.LineString([a,q]);cuts=[0.,1.]
                    for i in self.patch.tree.query(line,predicate='intersects'):
                        for segment in lines(line.intersection(self.patch.polygons[i])):
                            cuts.extend(float(np.clip((np.array(p)-a)@d/length2,0,1)) for p in (segment.coords[0],segment.coords[-1]))
                    cuts=np.unique(np.round(cuts,10));full=np.column_stack([original,color])
                    for lo,hi in zip(cuts[:-1],cuts[1:]):
                        if hi-lo<1e-9:continue
                        p=full.copy()
                        for threshold,greater in ((lo,True),(hi,False)):
                            if not len(p):break
                            values=((p[:,[0,2]]*[1,-1]-a)@d)/length2;p=clip_scalar(p,values,threshold,greater)
                        if len(p)>=3:pieces.append(np.array([[p[0],p[i],p[i+1]] for i in range(1,len(p)-1)]))
            if not pieces:continue
            packed=np.concatenate(pieces);v=packed[:,:,:8];c=packed[:,:,8];q=v[:,:,[0,2]]*[1,-1];delta=self.delta(q.reshape(-1,2)).reshape(-1,3)
            if bank:
                # Keep the old river bottom; move the bank crest with the land.
                old_ground=safe_sample(self.old,q.reshape(-1,2)).reshape(-1,3)-self.alt
                weight=np.clip((v[:,:,1]-(old_ground-2.12))/2.12,0,1);delta*=weight
            v[:,:,1]+=delta;normals(v)
            result.append(v);materials.append(np.full(len(v),m[idx],np.uint32));colors.append(c);changed+=1
        return np.concatenate(result),np.concatenate(materials),np.concatenate(colors),changed


def landmark_labels(source,models,entries,crs,old,alt):
    """Recover source model ownership in the preserved canonical triangle order."""
    b=Builder.__new__(Builder);b.project=Transformer.from_crs('EPSG:3395',crs,always_xy=True)
    groups=collections.defaultdict(list)
    for tile,f,g in models:groups[metadata(f,'MODEL_METADATA')['light']['id']].append((tile,f,g))
    labels=[]
    for mid,parts in groups.items():
        tile,f,_=parts[0];g=union([r[2] for r in parts]);anchor=g.representative_point();base=float(safe_sample(old,[[anchor.x,anchor.y]])[0])+.12
        manifest=json.loads((source/'decoded-models'/f'{mid}.json').read_text())
        for node in manifest['nodes'].values():
            t=np.load(source/'decoded-models'/node['file'])['triangles'].astype(float);xy,h=b.node_world(t,tile,metadata(f,'MODEL_METADATA')['light']['transform'])
            p=np.stack([xy[:,:,0],h+base-alt,-xy[:,:,1]],axis=2).astype('<f4')
            keep=np.linalg.norm(np.cross(p[:,1]-p[:,0],p[:,2]-p[:,0]),axis=1)>1e-9
            labels.extend([mid]*int(keep.sum()))
    return np.array(labels)


def building_selection(rows,model_footprint,rect):
    records=[]
    for f,g,l in rows:
        if f['layer']!='building' or metadata(f,'COVERED_BY_MODEL_METADATA') and g.intersects(model_footprint):continue
        records.extend((f,p) for p in polygons(g))
    tree=sh.STRtree([g for f,g in records]);initial=set(tree.query(rect,predicate='intersects').tolist());selected=set(initial);pending=list(initial)
    while pending:
        i=pending.pop()
        for j in tree.query(records[i][1],predicate='dwithin',distance=.003):
            j=int(j)
            if j not in selected:selected.add(j);pending.append(j)
    return [records[i] for i in sorted(selected)],records,initial,selected


def conforming_buildings(b,new):
    original_wall=b.wall
    def wall(self,line,bottom,top,mat,name,uvheight=3,reverse=False):
        if np.isscalar(bottom) and np.isscalar(top):return original_wall(line,bottom,top,mat,name,uvheight,reverse=reverse)
        for segment in lines(line):
            p=np.asarray(segment.coords)
            for a,q in zip(p[:-1],p[1:]):
                d=q-a;l2=d@d
                if l2<1e-12:continue
                edge=sh.LineString([a,q]);cuts=[0.,1.]
                for i in new.tree.query(edge,predicate='intersects'):
                    for v in sh.get_coordinates(edge.intersection(new.polygons[i])):cuts.append(float(np.clip((v-a)@d/l2,0,1)))
                cuts=np.unique(np.round(cuts,10));line=sh.LineString(a+cuts[:,None]*d)
                original_wall(line,bottom,top,mat,name,uvheight,reverse=reverse)
    b.wall=types.MethodType(wall,b)
    # The sampling wrapper tolerates only submillimetre serialization boundary drift.
    new.sample=lambda xy:safe_sample(new,xy)
    b.buildings_mesh()


def apply(base,out,source,field):
    assert not out.exists();out.mkdir(parents=True)
    for name in ('canonical','textures','meshes'):shutil.copytree(base/name,out/name,copy_function=copy_asset)
    for name in ('tileset.json','build-audit.json','moscow-style.json','plant-placement-audit.json.gz','placement-masks.json.gz','independent-placement-counts.json'):copy_asset(base/name,out/name)
    full=out/'canonical/full';parent=json.loads((full/'scene.json').read_text());city=json.loads((out/'canonical/urban-model.json').read_text());audit=json.loads((out/'canonical/validation.json').read_text())
    old=Terrain(np.load(base/'canonical/terrain.npz')['triangles']);new=Terrain(np.load(field/'terrain.npz')['triangles']);data=np.load(field/'survey-field.npz');patch=Terrain(data['triangles']);rect=sh.box(*data['bounds']);report=json.loads((field/'survey-terrain.json').read_text())
    project=Reproject(old,new,patch,rect,parent['origin'][2])
    from survey_fairing import TerrainNormals
    ground_normals=TerrainNormals(new)
    rows,features,models,embedded=pickle.load(open(source/'projected-scene-v1.pickle','rb'));model_footprint=union([g for tile,f,g in models])
    chosen,_,_,_=building_selection(rows,model_footprint,rect)
    building_domain=union([g for f,g in chosen]);building_mask=building_domain.buffer(.002)
    landmarks=audit['landmarks'];model_groups=collections.defaultdict(list)
    for tile,f,g in models:model_groups[metadata(f,'MODEL_METADATA')['light']['id']].append((tile,f,g))
    landmark_changes=[]
    for entry in landmarks:
        g=union([row[2] for row in model_groups[entry['model']]])
        if not g.intersects(rect):continue
        anchor=g.representative_point();change=float(project.delta([[anchor.x,anchor.y]])[0])
        entry['baseM']+=change;landmark_changes.append((entry,g,change))
    labels=landmark_labels(source,models,landmarks,city['crsProj'],old,parent['origin'][2]);landmark_cursor=0
    assert len(labels)==sum(c['triangles'] for c in parent['chunks'] if c['name']=='landmarks')
    np.savez_compressed(out/'canonical/source-model-ownership.npz',labels=labels)
    changed=[];counts=collections.Counter();chunks=[]
    for c in parent['chunks']:
        c=dict(c);old_file=full/c['file'];new_file='survey-parent-'+Path(c['file']).name;old_file.rename(full/new_file);c['file']=new_file
        name=c['name']
        if c.get('instanced') or name.startswith('nuray-approved'):chunks.append(c);continue
        t,m,tint=unpack(full,c);xy=t[:,:,[0,2]]*[1,-1];dirty=False
        if name=='buildings':
            remove=sh.covers(building_mask,sh.points(xy.mean(1)));counts['buildingTrianglesReplaced']+=int(remove.sum());dirty=remove.any();t,m,tint=t[~remove],m[~remove],tint[~remove]
        elif name=='landmarks':
            owners=labels[landmark_cursor:landmark_cursor+len(t)];landmark_cursor+=len(t)
            for entry,g,delta in landmark_changes:
                hit=owners==entry['model'];t[hit,:,1]+=delta;counts['landmarkTrianglesSeated']+=int(hit.sum());dirty|=hit.any()
        elif name!='water':
            t,m,tint,n=project.mesh(t,m,tint,bank=name=='waterfront-granite');counts[name]+=n;dirty=n>0
            if name=='land' and dirty:
                xy=t[:,:,[0,2]]*[1,-1]
                hit=sh.covers(rect,sh.points(xy.mean(1))) & (m!=0)
                t[hit,:,3:6]=ground_normals.for_triangles(xy[hit])
        if dirty and len(t):c.update(pack(t,m,full/c['file'],tints=None if not np.any(tint) else tint));changed.append(c['id'])
        if len(t):chunks.append(c)
        print('SURVEY CHUNK',c['id'],name,'triangles',len(t),'changed',bool(dirty),flush=True)
    mapping={c['id']:i for i,c in enumerate(chunks)}
    for c in chunks:c['id']=mapping[c['id']]
    instances=[{**i,'mesh':mapping[i['mesh']]} for i in parent['instances'] if i['mesh'] in mapping]
    b=Builder.__new__(Builder);b.out=out;b.full=full;b.source=source;b.terrain=new;b.alt=parent['origin'][2];b.materials=parent['materials'];b.chunks=chunks;b.instances=instances;b.batches=collections.defaultdict(list);b.batch_counts=collections.Counter();b.audit=collections.Counter();b.building_tops=[];b.buildings=chosen;b.fences=[];b.rails=[]
    b.matmap=dict(zip((0,1,2,3,4,5,6,7,9,10,13,25,26,27,28,29,30,31,317,327,329),range(21)))
    conforming_buildings(b,new)
    # Detailed source models stay rigid. Close only exposed footing gaps.
    for entry,g,delta in landmark_changes:
        base_height=entry['baseM']
        b.boundary_walls(g,lambda xy:new.sample(xy),lambda xy:np.maximum(new.sample(xy),base_height),20,'survey-model-foundations')
        oldtop=next((h for w,h in json.loads(gzip.decompress((out/'placement-masks.json.gz').read_bytes()))['buildings'] if sh.from_wkb(bytes.fromhex(w)).equals(g)),None)
        if oldtop is not None:b.building_tops.append((g,oldtop+delta))
    for name in list(b.batches):b.flush(name)
    masks=json.loads(gzip.decompress((out/'placement-masks.json.gz').read_bytes()));plants=json.loads(gzip.decompress((out/'plant-placement-audit.json.gz').read_bytes()))
    changed_tops={p.wkb_hex:float(h) for p,h in b.building_tops}
    masks['buildings']=[(w,changed_tops.get(w,h)) for w,h in masks['buildings']]
    accepted=plants['acceptedPoints'];xy=np.array([p['eastNorth'] for p in accepted]);delta=project.delta(xy)
    for p,d in zip(accepted,delta):p['matrix'][7]+=float(d)
    building_tree=sh.STRtree([sh.from_wkb(bytes.fromhex(w)) for w,h in masks['buildings']]);tops=np.array([h for w,h in masks['buildings']]);mat=np.array([p['matrix'] for p in accepted]).reshape(-1,3,4);scale=np.linalg.norm(mat[:,:,:3],axis=1)[:,0];crowns=np.array([masks['crowns'][p['model']] for p in accepted])*scale[:,None]
    pi,bi=building_tree.query(sh.buffer(sh.points(xy),crowns[:,0],quad_segs=8),predicate='intersects');bad=set(pi[tops[bi]>mat[pi,1,3]+b.alt+crowns[pi,1]+1e-6].tolist());removed=set()
    for i in bad:
        p=accepted[i];plants['rejectedPoints'].append({**p,'conflicts':['buildingCanopyAfterSurvey']});removed.add(p['id'])
    plants['acceptedPoints']=[p for i,p in enumerate(accepted) if i not in bad];plants['accepted']-=len(bad);plants['rejected']+=len(bad);plants['byModel']=dict(collections.Counter(p['model'] for p in plants['acceptedPoints']));plants['byConflict']=dict(collections.Counter(k for p in plants['rejectedPoints'] for k in p['conflicts']))
    matrices={p['id']:p['matrix'] for p in plants['acceptedPoints']};b.instances=[{**i,'matrix':matrices[i['id']]} if i.get('id') in matrices else i for i in b.instances if i.get('id') not in removed]
    for name,value in [('placement-masks.json.gz',masks),('plant-placement-audit.json.gz',plants)]:
        with gzip.open(out/name,'wt') as f:json.dump(value,f,separators=(',',':'))
    copy_asset(field/'terrain.npz',out/'canonical/terrain.npz');copy_asset(field/'survey-field.npz',out/'canonical/survey-field.npz')
    scene={**parent,'chunks':b.chunks,'instances':b.instances};scene['stats']=dict(uniqueTriangles=sum(c['triangles'] for c in b.chunks),expandedTriangles=sum(b.chunks[i['mesh']]['triangles'] for i in b.instances))
    marks=data['marks'];q=np.median(marks,axis=0);scene.setdefault('witnessViews',{})['survey-review']=dict(yaw=-.7,pitch=.68,distance=1050,target=[float(q[0]),float(q[2]-b.alt),float(-q[1])]);scene.setdefault('witnessViewLabels',{})['survey-review']='Детинец · топосъёмка'
    report.update(changedChunks=changed,changedTriangleCounts=dict(counts),genericBuildingParts=len(chosen),detailedModelsSeated=len(landmark_changes),plantRootsMoved=int((abs(delta)>.001).sum()),plantsRejectedByNewBuildingHeights=len(bad),waterSurfacePreserved=True,
        buildingPolicy='Rigid roofs/author models; terrain-conforming generic footings; detailed model footing skirts; source XY retained',appliedToScene=True)
    city['surveyTerrain']=report;city['geometryRevision']={'version':'yandex-survey-terrain-6','parent':base.name};city['objectLayer']['stats']['vegetationInstances']=plants['accepted']
    audit.update(stats=scene['stats'],surveyTerrain=report,landmarks=landmarks,plants={k:v for k,v in plants.items() if not k.endswith('Points')});audit['terrain']['triangles']=len(new.triangles)
    for name,value in [('canonical/full/scene.json',scene),('canonical/urban-model.json',city),('canonical/validation.json',audit),('build-audit.json',audit),('survey-terrain.json',report)]:dump(out/name,value)
    print('SURVEY APPLIED',json.dumps(report,ensure_ascii=False),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--base',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--source',type=Path,required=True);p.add_argument('--field',type=Path,required=True);a=p.parse_args();apply(a.base,a.output,a.source,a.field)
