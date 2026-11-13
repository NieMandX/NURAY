"""Apply finished street grades and source-backed square surface precedence.

Survey terrain remains immutable. Pavement, its curb and neighbouring verge
share a new civil surface; only the collar blends back to the natural slope.
"""
import argparse,collections,gzip,hashlib,json,pickle,shutil
from pathlib import Path
import numpy as np
import shapely as sh
from build_scene import Builder,Terrain,cdt,union,polygons,dump
from apply_crossfall import RoadField,unpack,normals,reproject_paint
from road_grade import fade
from paving_domains import specific_square_surfaces
from survey_terrain import safe_sample
from canonical_store import copy_asset
from object_geometry import pack
from street_placement import SurfaceSampler


class FinishedGrade:
    def __init__(self,root,field,settings):
        self.terrain=Terrain(np.load(root/'canonical/terrain.npz')['triangles'])
        self.road=RoadField(field);self.alt=json.loads((root/'canonical/full/scene.json').read_text())['origin'][2]
        self.center=np.asarray(settings['center']);self.inner=settings['innerRadiusM'];self.outer=settings['outerRadiusM']
        from finished_grade_field import load_or_build
        self.continuous=load_or_build(field.with_name('finished-grade-field.npz'),self.road,self.terrain,self.alt,self.center,self.outer)
    def weight(self,xy):return fade(np.linalg.norm(np.asarray(xy)-self.center,axis=1),self.inner,self.outer)
    def delta(self,xy):
        xy=np.asarray(xy).reshape(-1,2);weight=self.weight(xy);result=np.zeros(len(xy));selected=weight>0
        if selected.any():
            q=xy[selected];d,z,distance=self.road.sample(q)
            natural=safe_sample(self.terrain,q)-self.alt
            # Exact contact at the roadway; a continuous harmonic collar
            # replaces nearest-road switching between separate carriageways.
            near=fade(distance,.15,2.)
            smooth=(self.continuous(q)-natural)*fade(distance,26.,30.)
            result[selected]=((d+z-.035-natural)*near+smooth*(1-near))*weight[selected]
        return result
    def base(self,xy):return safe_sample(self.terrain,xy)+self.delta(xy)


def clip_material(t,m,tint,domain,replace_material=None):
    """Split exact XY footprints; preserve barycentric UV, tint and height."""
    sh.prepare(domain)
    xy=t[:,:,[0,2]]*[1,-1];selected=sh.intersects(domain,sh.polygons(xy))
    out=[t[~selected]];mats=[m[~selected]];colors=[tint[~selected]];area=0.
    for original,mat,color,p in zip(t[selected],m[selected],tint[selected],xy[selected]):
        design=np.column_stack([p,np.ones(3)])
        if abs(np.linalg.det(design))<1e-10:
            out.append(original[None]);mats.append(np.array([mat]));colors.append(color[None]);continue
        attributes=np.linalg.solve(design,original);tints=np.linalg.solve(design,color);poly=sh.Polygon(p)
        for g,inside in ((poly.difference(domain),False),(poly.intersection(domain),True)):
            if inside:area+=g.area
            if inside and replace_material is None:continue
            q=cdt(g)
            if not len(q):continue
            reverse=np.linalg.det(q[:,1:]-q[:,:1])<0;q[reverse]=q[reverse][:,[0,2,1]]
            a=np.concatenate([q,np.ones((*q.shape[:2],1))],axis=2)
            v=a@attributes
            if inside:v[:,:,6:8]=q # metre-scale paving UVs
            out.append(v);mats.append(np.full(len(q),replace_material if inside else mat));colors.append(a@tints)
    return np.concatenate(out),np.concatenate(mats),np.concatenate(colors),area


def apply(base,out,source,field,evidence,reuse_road_derived=None):
    assert not out.exists();out.mkdir(parents=True)
    for name in ('canonical','textures','meshes'):shutil.copytree(base/name,out/name,copy_function=copy_asset)
    for path in base.iterdir():
        if path.is_file() and path.suffix in ('.json','.gz'):copy_asset(path,out/path.name)
    # Past stage receipts remain evidence for their immutable stage, not a
    # false claim that this later grading stage left all geometry unchanged.
    history=out/'prior-stages';history.mkdir();historical={}
    for stem in ('survey-lamps','survey-plants','ravine-plants'):
        for suffix in ('.json','-validation.json'):
            p=out/(stem+suffix)
            if p.exists():
                historical[p.name]=hashlib.sha256(p.read_bytes()).hexdigest();p.rename(history/p.name)
    for p in out.glob('survey*-validation.json'):
        historical[p.name]=hashlib.sha256(p.read_bytes()).hexdigest();p.rename(history/p.name)
    full=out/'canonical/full';scene=json.loads((full/'scene.json').read_text());original_scene=json.loads((base/'canonical/full/scene.json').read_text())
    masks=json.loads(gzip.decompress((out/'placement-masks.json.gz').read_bytes()));settings=json.loads((field/'road-crossfall.json').read_text())
    grade=FinishedGrade(base,field/'road-height-field.npz',settings)
    finished={r['kind']:sh.from_wkb(bytes.fromhex(r['geometry'])) for r in masks['finishedGround']}
    offsets={r['kind']:r['offsetM'] for r in masks['finishedGround']}
    rows,*_=pickle.load(open(source/'projected-scene-v1.pickle','rb'))
    grass,parking=specific_square_surfaces(rows)
    # Scope this inspected release to the central area; the rule itself is
    # shared by the general builder for subsequent city builds.
    roi=sh.Point(grade.center).buffer(grade.inner)
    grass=grass.intersection(finished['ped']).intersection(roi)
    parking=parking.intersection(finished['ped']).intersection(roi)
    restored=grass.union(parking);finished['ped']=finished['ped'].difference(restored)
    finished['grass']=finished['grass'].union(grass);finished['parking']=finished['parking'].union(parking)
    for geometry in finished.values():sh.prepare(geometry)
    band=grass.difference(grass.buffer(-.12,join_style='mitre',mitre_limit=2))
    masks['root']['walkway']=sh.from_wkb(bytes.fromhex(masks['root']['walkway'])).difference(restored).wkb_hex
    masks['root']['road']=sh.from_wkb(bytes.fromhex(masks['root']['road'])).union(parking).wkb_hex
    masks['root']['greenCurb']=sh.from_wkb(bytes.fromhex(masks['root']['greenCurb'])).union(band).wkb_hex
    masks['finishedGround']=[dict(kind=k,geometry=g.wkb_hex,offsetM=offsets[k])for k,g in finished.items()]
    # Evidence zones assign material classes, never hand-edit mesh vertices.
    spec=json.loads(evidence.read_text());zones=[]
    for zone in spec['zones']:
        material={**scene['materials'][13],**zone['material']};index=len(scene['materials']);scene['materials'].append(material)
        eligible=finished['ped'].union(finished['default']) if zone.get('includeUnclassifiedGround') else finished['ped']
        g=sh.Polygon(zone['polygon']).intersection(eligible);zones.append((zone,g,index))
    changed=[];counts=collections.Counter();paving={};changed_files=[]
    road=RoadField(field/'road-height-field.npz')
    reusable={};reuse_receipt={}
    if reuse_road_derived:
        reuse_receipt=json.loads((reuse_road_derived/'paved-grade.json').read_text())
        assert reuse_receipt['passed'] and reuse_receipt['parent']==base.name
        assert hashlib.sha256((field/'road-height-field.npz').read_bytes()).digest()==hashlib.sha256((reuse_road_derived/'canonical/road-height-field.npz').read_bytes()).digest()
        reusable={c['id']:c for c in json.loads((reuse_road_derived/'canonical/full/scene.json').read_text())['chunks'] if c['name'] in ('paint','road-curbs')}
    for c in scene['chunks']:
        if c.get('instanced') or c['name'].startswith('nuray-approved') or c['name'] in ('water','landmarks','transport-structures','transport-approaches','rails'):continue
        if c['id'] in reusable:
            cached=reusable[c['id']];assert cached['name']==c['name'] and cached['file']==c['file']
            copy_asset(reuse_road_derived/'canonical/full'/c['file'],full/c['file']);c.update(cached)
            changed.append(c['id']);changed_files.append(c['file']);counts[c['name']]=reuse_receipt['changedTriangleCounts'][c['name']]
            print('REUSED UNCHANGED ROAD DERIVATIVE',c['id'],c['name'],flush=True);continue
        name=c['name'];t,m,tint=unpack(full,c);xy=t[:,:,[0,2]]*[1,-1]
        radial=np.linalg.norm(xy-grade.center,axis=2);local=(radial.min(1)<grade.outer+5)
        dirty=False
        if name=='land':
            t,m,tint,removed=clip_material(t,m,tint,restored);dirty=removed>0
            for zone,g,index in zones:
                t,m,tint,area=clip_material(t,m,tint,g,index);paving[zone['id']]=paving.get(zone['id'],0)+area;dirty|=area>0
            xy=t[:,:,[0,2]]*[1,-1];q=xy.reshape(-1,2);delta=grade.delta(q).reshape(-1,3);hit=(abs(delta).max(1)>1e-7)
            # Most skins have natural height + constant finish offset. Old
            # entrance ramps are superseded by the shared sidewalk grade.
            nat=safe_sample(grade.terrain,q).reshape(-1,3)-grade.alt
            ped=np.isin(m,[7,12,13,14,15,16])
            zone_ped=np.isin(m,[i for _,_,i in zones])
            zone_ped[zone_ped]=sh.covers(finished['ped'],sh.points(xy[zone_ped].mean(1)))
            ped|=zone_ped
            local=grade.weight(xy.mean(1))>0
            hit|=ped&local
            t[ped&local,:,1]=nat[ped&local]+.075
            t[:,:,1]+=delta
            hitroad=m==0
            if hitroad.any():
                d,z,_=road.sample(xy[hitroad].reshape(-1,2));t[hitroad,:,1]=(z+d).reshape(-1,3);hit|=hitroad
            dirty|=hit.any()
        elif name=='paint':
            t,m,tint,stats=reproject_paint(t,m,tint,road);hit=np.ones(len(t),bool);dirty=stats['sourceTriangles']>0
        elif name=='road-curbs':
            q=xy.reshape(-1,2);d=road.sample(q)[0].reshape(-1,3);t[:,:,1]+=d;hit=abs(d).max(1)>1e-7;dirty=hit.any()
        elif name in ('road-cut-fill','road-entry-ramp-sides'):
            q=xy.reshape(-1,2);w=grade.weight(q).reshape(-1,3);h=(grade.base(q)-grade.alt+.035).reshape(-1,3)
            t[:,:,1]=(1-w)*t[:,:,1]+w*h;hit=w.max(1)>0;dirty=hit.any()
            # The old artificial side skirt collapses where both street and
            # verge now meet the same profile. Retain skirts outside the ROI.
            keep=np.linalg.norm(np.cross(t[:,1,:3]-t[:,0,:3],t[:,2,:3]-t[:,0,:3]),axis=1)>1e-7
            t,m,tint,hit=t[keep],m[keep],tint[keep],hit[keep]
        elif name in ('buildings','survey-model-foundations'):
            q=xy[local].reshape(-1,2);h=safe_sample(grade.terrain,q).reshape(-1,3)-grade.alt
            foot=abs(t[local,:,1]-h)<.003;delta=grade.delta(q).reshape(-1,3)*foot
            v=t[local].copy();v[:,:,1]+=delta;t[local]=v;hit=np.zeros(len(t),bool);hit[local]=abs(delta).max(1)>1e-7;dirty=hit.any()
        else:
            q=xy[local].reshape(-1,2);delta=grade.delta(q).reshape(-1,3)
            if name=='waterfront-granite':
                natural=safe_sample(grade.terrain,q).reshape(-1,3)-grade.alt
                delta*=np.clip((t[local,:,1]-(natural-2.12))/2.12,0,1)
            v=t[local].copy();v[:,:,1]+=delta;t[local]=v;hit=np.zeros(len(t),bool);hit[local]=abs(delta).max(1)>1e-7;dirty=hit.any()
        if dirty:
            v=t[hit].copy();normals(v);t[hit]=v
            c.update(pack(t,m,full/c['file'],tints=None if not np.any(tint) else tint));changed.append(c['id']);counts[name]+=int(hit.sum());changed_files.append(c['file'])
            print('GRADED',c['id'],name,len(t),flush=True)
    b=Builder.__new__(Builder);b.full=full;b.out=out;b.alt=grade.alt;b.terrain=grade.terrain;b.materials=scene['materials'];b.chunks=scene['chunks'];b.instances=scene['instances'];b.batches=collections.defaultdict(list);b.batch_counts=collections.Counter()
    b.surface(grass.difference(band),2,'land',offset=.175,height=grade.base)
    b.surface(band,8,'land',offset=.175,height=grade.base)
    b.boundary_walls(grass,grade.base,lambda xy:grade.base(xy)+.175,8,'green-curbs')
    b.surface(parking,17,'land',offset=.035,height=grade.base)
    for name in list(b.batches):b.flush(name)
    scene['chunks']=b.chunks;scene['instances']=b.instances
    # Seat every shared object on the actual serialized, graded surface.
    sampler=SurfaceSampler(out,scene,{'land','road-curbs','green-curbs','curbs'})
    moved=[];matrices={}
    for inst in scene['instances']:
        if 'id' not in inst:continue
        mat=inst['matrix'];xy=np.array([[mat[3],-mat[11]]])
        if grade.weight(xy)[0]<=0:continue
        hit=sampler.ground(mat[3],mat[11]);assert hit is not None,inst['id']
        if abs(hit['height']-mat[7])>1e-7:moved.append(dict(id=inst['id'],beforeM=mat[7],afterM=hit['height']))
        mat[7]=hit['height'];matrices[inst['id']]=mat
    plants=json.loads(gzip.decompress((out/'plant-placement-audit.json.gz').read_bytes()))
    for row in plants['acceptedPoints']:
        if row['id'] in matrices:row['matrix']=matrices[row['id']]
    for filename,value in [('placement-masks.json.gz',masks),('plant-placement-audit.json.gz',plants)]:
        with gzip.open(out/filename,'wt')as f:json.dump(value,f,separators=(',',':'))
    # A matching appearance override plan is derived, leaving historical
    # infill evidence and its old transforms in prior-stages unchanged.
    appearance=json.loads((history/'ravine-plants.json').read_text())
    for row in appearance['records']:
        if row.get('id') in matrices:row['matrix']=matrices[row['id']]
    dump(out/'vegetation-appearance.json',appearance)
    report=dict(version=1,parent=base.name,passed=False,method='Smoothed source road network; shared finished sidewalk/verge grade; immutable survey terrain',
       settings=settings,changedChunks=changed,changedTriangleCounts=dict(counts),historicalReceipts=historical,
       restoredSourceGreenM2=grass.area,restoredSourceParkingM2=parking.area,pavingM2=paving,pavingEvidence=spec,
       relocatedVerticalInstances=moved,sourceXYScaleYawPreserved=True,terrainAndSurveyUnchanged=True,waterMeshUnchanged=True,
       note='Visual civil grading, not surveyed engineering design; imagery dates retained in evidence')
    dump(out/'paved-grade.json',report);copy_asset(field/'road-height-field.npz',out/'canonical/road-height-field.npz');copy_asset(field/'network-grade.npz',out/'canonical/network-grade.npz');dump(out/'road-crossfall.json',settings)
    for name in ('finished-grade-field.npz','finished-grade-field.json'):copy_asset(field/name,out/'canonical'/name)
    scene['stats']=dict(uniqueTriangles=sum(c['triangles']for c in scene['chunks']),expandedTriangles=sum(scene['chunks'][i['mesh']]['triangles']for i in scene['instances']))
    scene.setdefault('witnessViews',{})['street-grade-review']=dict(yaw=5.141,pitch=.08,distance=53.1647483,target=[372.7614897,18.5297579,-176.5299997])
    scene['witnessViews']['circus-paving-review']=dict(yaw=-.35,pitch=.95,distance=380,target=[-45,float(grade.base([[-45,155]])[0]-grade.alt),-155])
    scene['witnessViews']['central-streets-review']=dict(yaw=-.35,pitch=.95,distance=900,target=[125,20,-150])
    scene['witnessViews']['philharmonic-paving-review']=dict(yaw=-1.3,pitch=.85,distance=160,target=[207,float(grade.base([[207,55]])[0]-grade.alt),-55])
    scene.setdefault('witnessViewLabels',{}).update({'street-grade-review':'Сонина · плавная улица','circus-paving-review':'Цирк · мощение и газоны','central-streets-review':'Центральный участок · улицы вокруг','philharmonic-paving-review':'Филармония · мощение'})
    dump(full/'scene.json',scene)
    city=json.loads((out/'canonical/urban-model.json').read_text());city['geometryRevision']=dict(version='yandex-paved-grade-11',parent=base.name);city['pavedGrade']={k:v for k,v in report.items()if k!='relocatedVerticalInstances'};dump(out/'canonical/urban-model.json',city)
    for name in ('canonical/validation.json','build-audit.json'):
        audit=json.loads((out/name).read_text());audit['stats']=scene['stats'];audit['pavedGrade']=city['pavedGrade'];dump(out/name,audit)
    print('PAVED GRADE COMPLETE',dict(counts),'green',grass.area,'parking',parking.area,'moved',len(moved),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser()
    for name in ('base','output','source','field','evidence'):p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--reuse-road-derived',type=Path,help='Validated same-parent, byte-identical road field; reuse only paint and road curbs')
    a=p.parse_args();apply(a.base,a.output,a.source,a.field,a.evidence,a.reuse_road_derived)
