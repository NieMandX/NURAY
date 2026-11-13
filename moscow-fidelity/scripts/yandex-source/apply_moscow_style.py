"""Selective, reproducible style migration; no fresh terrain/building rebuild."""
import argparse,collections,gc,gzip,math,hashlib,json,pickle,shutil
from pathlib import Path
import numpy as np
import shapely as sh
from pyproj import Transformer
from build_scene import Builder,Terrain,union,dump
from canonical_store import copy_asset
import moscow_style as style
from style_evidence import load

def apply(base,out,source,supplement):
    assert not out.exists() and base.resolve()!=out.resolve()
    parent=json.loads((base/'canonical/full/scene.json').read_text())
    city=json.loads((base/'canonical/urban-model.json').read_text())
    assert not city.get('moscowStyle'),'Never lower water twice'
    out.mkdir(parents=True)
    for name in ('canonical','textures','meshes'):
        shutil.copytree(base/name,out/name,copy_function=copy_asset)
    copy_asset(base/'tileset.json',out/'tileset.json')
    evidence=load(supplement,city['crsProj'],supplement/'nuray-style-evidence-v2.pickle')
    b=Builder.__new__(Builder);b.source=source;b.out=out;b.full=out/'canonical/full';b.materials=parent['materials'];b.textures=parent['textures']
    with (source/'projected-scene-v1.pickle').open('rb') as f:b.rows,b.features,b.models,b.embedded=pickle.load(f)
    gc.freeze();gc.disable()
    b.model_footprint=union([g for tile,f,g in b.models]);b.terrain=Terrain(np.load(out/'canonical/terrain.npz')['triangles']);b.alt=parent['origin'][2];b.circle=sh.Point(0,0).buffer(3000,quad_segs=512)
    b.matmap=dict(zip((0,1,2,3,4,5,6,7,9,10,13,25,26,27,28,29,30,31,317,327,329),range(21)))
    b.audit=collections.Counter();b.support={};b.approaches=collections.defaultdict(list);b.buildings=[];b.paint=[];b.fences=[];b.rails=[];b.groups=collections.defaultdict(list)
    b.project=Transformer.from_crs('EPSG:3395',city['crsProj'],always_xy=True)
    # Recover source domains and opening masks without rebuilding old geometry.
    b.add=lambda *args,**kw:None;b.surface=lambda *args,**kw:None;b.boundary_walls=lambda *args,**kw:None
    b.import_transport();b.classify();b.grounds();b.road_curbs()
    del b.add,b.surface,b.boundary_walls
    replace={'land','water','curbs','street-fences'};b.chunks=[];mapping={};unchanged=[]
    for c in parent['chunks']:
        if c['name'] in replace:continue
        c=dict(c);oldid=c['id'];mapping[oldid]=len(b.chunks);c['id']=mapping[oldid]
        oldpath=b.full/c['file'];newname='inherited-'+Path(c['file']).name;oldpath.rename(b.full/newname);c['file']=newname
        unchanged.append(dict(name=c['name'],parentMesh=oldid,newMesh=c['id'],sha256=hashlib.sha256((b.full/newname).read_bytes()).hexdigest()))
        b.chunks.append(c)
    for c in parent['chunks']:
        if c['name'] in replace:(b.full/c['file']).unlink()
    b.instances=[{**i,'mesh':mapping[i['mesh']]} for i in parent['instances'] if i['mesh'] in mapping]
    b.batches=collections.defaultdict(list);b.batch_counts=collections.Counter()
    style.grounds(b,evidence)
    for name in list(b.batches):b.flush(name)
    style.waterfront(b)
    for name in list(b.batches):b.flush(name)
    style.fences(b,evidence)
    for name in list(b.batches):b.flush(name)
    plants=json.loads(gzip.decompress((base/'plant-placement-audit.json.gz').read_bytes()))
    masks=json.loads(gzip.decompress((base/'placement-masks.json.gz').read_bytes()))
    masks['root']['greenCurb']=b.green_band.wkb_hex
    # Raised stone is landward of a river; extend the plant blocker there.
    parapet=b.water_selected.buffer(.42,join_style='mitre').difference(b.water_selected)
    masks['root']['waterfrontParapet']=parapet.wkb_hex
    rows=plants['acceptedPoints'];xy=np.array([p['eastNorth'] for p in rows]);matrices=np.array([p['matrix'] for p in rows]).reshape(-1,3,4)
    scales=np.linalg.norm(matrices[:,:,:3],axis=1)[:,0];crowns=np.array([masks['crowns'][p['model']] for p in rows])*scales[:,None]
    radii=np.where(crowns[:,1]<2.5,np.maximum(.22,crowns[:,0]),.22);footprints=sh.buffer(sh.points(xy),radii,quad_segs=4)
    conflicts={k:sh.intersects(sh.from_wkb(bytes.fromhex(masks['root'][k])),footprints) for k in ('greenCurb','waterfrontParapet')}
    removed=set();offsets=style.ground_offset(b,xy);heights=b.terrain.sample(xy)+offsets-b.alt;updated={}
    for i,p in enumerate(rows):
        reasons=[k for k,hit in conflicts.items() if hit[i]]
        if reasons:
            removed.add(p['id']);plants['rejectedPoints'].append({**p,'conflicts':reasons});continue
        p['matrix'][7]=float(heights[i]);updated[p['id']]=p['matrix']
    plants['acceptedPoints']=[p for p in rows if p['id'] not in removed];plants['accepted']-=len(removed);plants['rejected']+=len(removed)
    plants['byConflict']=dict(collections.Counter(k for p in plants['rejectedPoints'] for k in p['conflicts']))
    plants['byModel']=dict(collections.Counter(p['model'] for p in plants['acceptedPoints']))
    b.instances=[{**i,'matrix':updated[i['id']]} if i.get('id') in updated else i for i in b.instances if i.get('id') not in removed]
    masks['finishedGround']=[{'kind':k,'geometry':g.wkb_hex,'offsetM':style.OFFSETS[k]} for k,g in b.finished.items() if k in style.OFFSETS and k!='water']
    masks['finishedGround'].append({'kind':'road-curb','geometry':b.road_curb.wkb_hex,'offsetM':.135})
    for name,data in [('placement-masks.json.gz',masks),('plant-placement-audit.json.gz',plants)]:
        with gzip.open(out/name,'wt') as f:json.dump(data,f,separators=(',',':'))
    report=b.style_audit;report.update(sourceEvidenceSha256=evidence['signature'][1],sourceCounts=evidence['counts'],unchangedCanonicalMeshes=unchanged,plantRootsUpdated=len(updated),plantsRemovedByEdging=len(removed))
    scene={**parent,'chunks':b.chunks,'instances':b.instances,'materials':b.materials,'textures':b.textures}
    scene['stats']=dict(uniqueTriangles=sum(c['triangles'] for c in b.chunks),expandedTriangles=sum(b.chunks[i['mesh']]['triangles'] for i in b.instances))
    views={};labels={}
    for code,camera in report['fences']['witnessViews'].items():
        key='fence-'+('unknown' if code=='None' else code)+'-review';views[key]=camera;labels[key]='Ограждение · '+('тип не указан' if code=='None' else style.TYPES[int(code)][1])
    if hasattr(b,'water_banks'):
        banks=b.water_banks;mid=(banks['a']+banks['b'])/2
        # Review selection affects camera only, never construction.
        pick=np.argmin(np.linalg.norm(mid,axis=1));q=mid[pick];d=banks['b'][pick]-banks['a'][pick];waterward=np.array([-d[1],d[0]])/np.linalg.norm(d)
        views['waterfront-review']=dict(yaw=math.atan2(waterward[0],-waterward[1]),pitch=.40,distance=75,target=[float(q[0]),float(banks['top'][pick].mean()-b.alt-.7),float(-q[1])]);labels['waterfront-review']='Набережная · гранит и парапет'
    # Closest sufficiently large lawn near the circus, for a reproducible view.
    candidates=[g for g in style.polygons(b.finished['grass']) if 100<g.area<15000]
    if candidates:
        g=min(candidates,key=lambda g:g.distance(sh.Point(0,0)));q=g.representative_point();views['landscape-review']=dict(yaw=-.6,pitch=.72,distance=155,target=[q.x,float(b.terrain.sample([[q.x,q.y]])[0]-b.alt),-q.y]);labels['landscape-review']='Покрытия · газоны и бордюры'
    scene['witnessViews']=views;scene['witnessViewLabels']=labels
    city['moscowStyle']=report;city['geometryRevision']={'version':'yandex-moscow-style-3','parent':base.name}
    city['objectLayer']['stats']['vegetationInstances']=plants['accepted']
    city['limitations']=[x for x in city['limitations'] if not x.startswith('Source fences')]+['Fence types transferred only where parallel source spans match within 1.5 m; unspecified types remain neutral.','Unspecified paving materials remain neutral; no inferred wood, gravel or stone.','River banks/parapets are algorithmic Moscow design rules, not surveyed Kursk quay geometry.']
    dump(out/'moscow-style.json',report);dump(b.full/'scene.json',scene);dump(out/'canonical/urban-model.json',city)
    for name in ('canonical/validation.json','build-audit.json'):
        audit=json.loads((base/name).read_text());audit.update(stats=scene['stats'],moscowStyle=report,plants={k:v for k,v in plants.items() if not k.endswith('Points')});dump(out/name,audit)
    dump(out/'independent-placement-counts.json',{'superseded':True,'reason':'New edging/root heights verified against canonical finished ground and source XY.'})
    print('MOSCOW STYLE COMPLETE',scene['stats'],'plants',plants['accepted'],flush=True)

if __name__=='__main__':
    import math
    p=argparse.ArgumentParser();p.add_argument('--base',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--source',type=Path,required=True);p.add_argument('--supplement',type=Path,required=True)
    a=p.parse_args();apply(a.base,a.output,a.source,a.supplement)
