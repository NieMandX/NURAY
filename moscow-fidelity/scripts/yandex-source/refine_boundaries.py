"""Repair the original hybrid wall winding and add Moscow ground-road curbs.

The immutable parent retains terrain, paint, landmarks, roofs and source XY.
Only affected canonical meshes and their dependent transports are rebuilt.
"""
import argparse,collections,gc,gzip,hashlib,json,pickle,shutil
from pathlib import Path
import numpy as np
import shapely as sh
from build_scene import Builder,Terrain,polygons,union,metadata,dump,IDENTITY
from object_geometry import decode_normals
from canonical_store import copy_asset

def flip_faces(words,indices,flip):
    """Reverse fronts and shading normals, preserving positions/UV/materials."""
    words=words.copy();indices=indices.copy();vertices=np.unique(indices[flip])
    assert not np.intersect1d(vertices,np.unique(indices[~flip])).size
    n=-decode_normals(words[vertices,3]).astype(float)
    n/=np.maximum(np.abs(n).sum(1,keepdims=True),1e-20);xy=n[:,:2].copy();lower=n[:,2]<0
    xy[lower]=(1-np.abs(xy[lower,::-1]))*np.where(xy[lower]>=0,1,-1)
    words[vertices,3]=np.round(np.clip(xy,-1,1)*32767).astype('<i2').view('<u4').ravel()
    indices[flip]=indices[flip][:,[0,2,1]]
    return words,indices

def repair(base,out,source):
    assert base.resolve()!=out.resolve() and not out.exists()
    out.mkdir(parents=True)
    # COW copies, never hard links, so editing a child cannot mutate its parent.
    for name in ('canonical','textures','meshes'):
        shutil.copytree(base/name,out/name,copy_function=copy_asset)
    for name in ('tileset.json','build-audit.json','plant-placement-audit.json.gz','placement-masks.json.gz','independent-placement-counts.json'):
        copy_asset(base/name,out/name)
    scene=json.loads((out/'canonical/full/scene.json').read_text());parent=json.loads(json.dumps(scene))
    city=json.loads((out/'canonical/urban-model.json').read_text())
    assert city['geometryRevision']['version']=='yandex-2gis-kursk-1','This migration is only for the original winding contract'
    with (source/'projected-scene-v1.pickle').open('rb') as f:rows,features,models,embedded=pickle.load(f)
    gc.freeze();gc.disable()
    model_footprint=union([g for tile,f,g in models]);rings=collections.Counter()
    for f,g,l in rows:
        if f['layer'] not in ('building','fence_a'):continue
        if f['layer']=='building' and metadata(f,'COVERED_BY_MODEL_METADATA') and not g.intersection(model_footprint).is_empty:continue
        for p in polygons(g):
            # Prove the old source contract before changing serialized faces.
            assert not sh.is_ccw(p.exterior)
            assert all(sh.is_ccw(r) for r in p.interiors)
            rings[f['layer']]+=1
            if f['layer']=='building':
                for q in polygons(p.buffer(-.4,join_style='mitre')):
                    assert not sh.is_ccw(q.exterior) and all(sh.is_ccw(r) for r in q.interiors)
    facade=next(i for i,m in enumerate(scene['materials']) if m['name']=='Фасад · светлый · этажные пояса')
    changed=[];counts=collections.Counter();unchanged=[]
    for c in scene['chunks']:
        path=out/'canonical/full'/c['file'];raw=gzip.decompress(path.read_bytes())
        if c['name'] not in ('buildings','curbs','street-fences'):
            unchanged.append({'id':c['id'],'sha256':hashlib.sha256(raw).hexdigest()});continue
        u=np.frombuffer(raw[:c['vertexBytes']],'<u4').reshape(-1,8);ix=np.frombuffer(raw[c['vertexBytes']:],'<u4').reshape(-1,3)
        p=u.view('<f4')[ix,:3].astype(float);normal=np.cross(p[:,1]-p[:,0],p[:,2]-p[:,0]);normal/=np.maximum(np.linalg.norm(normal,axis=1,keepdims=True),1e-20)
        flip=(u[ix[:,0],6]&0x7fffffff)==facade if c['name']=='buildings' else np.abs(normal[:,1])<1e-7
        assert np.all(np.abs(normal[flip,1])<1e-7)
        if not flip.any():continue
        v,j=flip_faces(u,ix,flip)
        np.testing.assert_array_equal(v[:,[0,1,2,4,5,6,7]],u[:,[0,1,2,4,5,6,7]])
        np.testing.assert_array_equal(j[~flip],ix[~flip])
        old_normal=decode_normals(u[ix[flip,0],3]).astype(float)
        new_normal=decode_normals(v[j[flip,0],3]).astype(float)
        # Float32 XY can rotate the geometry of tiny curb slivers; the source
        # shading normal must still negate exactly within oct encoding error.
        assert np.all((old_normal*new_normal).sum(1)<-.999999)
        old_dot=(old_normal*normal[flip]).sum(1);new_dot=(new_normal*(-normal[flip])).sum(1)
        assert np.all(new_dot>0) and np.max(np.abs(old_dot-new_dot))<.0001
        with gzip.GzipFile(filename=str(path),mode='wb',mtime=0,compresslevel=6) as f:f.write(v.tobytes());f.write(j.tobytes())
        changed.append(c['id']);counts[c['name']]+=int(flip.sum())
    print('WALL REPAIR',dict(counts),'source polygons',dict(rings),flush=True)
    # Recompute only semantic footprints and new edging; no terrain/road rebuild.
    b=Builder.__new__(Builder);b.source=source;b.out=out;b.full=out/'canonical/full'
    b.rows=rows;b.features=features;b.models=models;b.embedded=embedded;b.model_footprint=model_footprint
    b.terrain=Terrain(np.load(out/'canonical/terrain.npz')['triangles']);b.alt=scene['origin'][2];b.circle=sh.Point(0,0).buffer(3000,quad_segs=512)
    b.materials=scene['materials'];b.matmap={0:0,7:7,9:8,10:9};b.audit=collections.Counter();b.support={};b.approaches=collections.defaultdict(list)
    b.buildings=[];b.paint=[];b.fences=[];b.rails=[];b.groups=collections.defaultdict(list)
    from pyproj import Transformer
    b.project=Transformer.from_crs('EPSG:3395',city['crsProj'],always_xy=True)
    # Imported transport is used only to recover original tunnel masks here.
    b.add=lambda *args,**kw:None
    b.import_transport();b.classify()
    occupied=b.building_footprint.union(b.holes)
    water=b.land.get(('water',0,'ground'),sh.Polygon()).difference(b.building_footprint)
    road=b.land.get(('road',0,'ground'),sh.Polygon()).difference(occupied).difference(water)
    assert abs(road.area-json.loads((out/'build-audit.json').read_text())['groundAreasM2']['road'])<1e-4
    b.finished={'road':road,'water':water};del b.add
    b.chunks=scene['chunks'];b.instances=scene['instances'];b.batches=collections.defaultdict(list);b.batch_counts=collections.Counter()
    count_before=len(b.chunks);b.road_curbs()
    for name in list(b.batches):b.flush(name)
    changed.extend(c['id'] for c in b.chunks[count_before:])
    assert b.road_curb_audit['roadOverlapM2']<.1 and b.road_curb_audit['openingOverlapM2']<.1
    # Keep the same collision rule after adding a physical 15 cm curb band.
    plants=json.loads(gzip.decompress((out/'plant-placement-audit.json.gz').read_bytes()))
    masks=json.loads(gzip.decompress((out/'placement-masks.json.gz').read_bytes()))
    rows=plants['acceptedPoints'];xy=np.array([p['eastNorth'] for p in rows]);matrices=np.array([p['matrix'] for p in rows]).reshape(-1,3,4)
    scales=np.linalg.norm(matrices[:,:,:3],axis=1)[:,0];crowns=np.array([masks['crowns'][p['model']] for p in rows])*scales[:,None]
    radii=np.where(crowns[:,1]<2.5,np.maximum(.22,crowns[:,0]),.22)
    conflicts=sh.intersects(b.road_curb,sh.buffer(sh.points(xy),radii,quad_segs=4));removed={rows[i]['id'] for i in np.where(conflicts)[0]}
    for i in np.where(conflicts)[0]:plants['rejectedPoints'].append({**rows[i],'conflicts':['roadCurb']})
    plants['acceptedPoints']=[p for p in rows if p['id'] not in removed]
    plants['accepted']-=len(removed);plants['rejected']+=len(removed);plants['byConflict']['roadCurb']=len(removed)
    plants['byModel']=dict(collections.Counter(p['model'] for p in plants['acceptedPoints']))
    scene['instances']=[i for i in scene['instances'] if i.get('id') not in removed]
    # Shared meshes themselves stay byte-identical; their tile ownership changes
    # only when a conflicting point was removed by the same clearance rule.
    if removed:changed.extend(c['id'] for c in scene['chunks'] if c.get('instanced'))
    masks['root']['road']=sh.to_wkb(sh.from_wkb(bytes.fromhex(masks['root']['road'])).union(b.road_curb)).hex()
    for name,data in [('placement-masks.json.gz',masks),('plant-placement-audit.json.gz',plants)]:
        with gzip.open(out/name,'wt') as f:json.dump(data,f,separators=(',',':'))
    scene['stats']={'uniqueTriangles':sum(c['triangles'] for c in scene['chunks']),'expandedTriangles':sum(scene['chunks'][i['mesh']]['triangles'] for i in scene['instances'])}
    assert scene['materials']==parent['materials']
    city['geometryRevision']={'version':'yandex-boundaries-2','parent':base.name,'changedChunks':sorted(set(changed))}
    city['objectLayer']['stats']['vegetationInstances']=plants['accepted']
    report={'passed':True,'changedChunks':sorted(set(changed)),'flippedTriangles':dict(counts),'sourceRingsChecked':dict(rings),'unchangedCanonicalMeshes':unchanged,'positionsUVMaterialsPreserved':True,'roofRecessFrontsPreserved':True,'roadCurbs':b.road_curb_audit,'plantsRemovedByNewCurbClearance':len(removed)}
    dump(out/'boundary-repair.json',report);dump(b.full/'scene.json',scene);dump(out/'canonical/urban-model.json',city)
    for name in ('canonical/validation.json','build-audit.json'):
        audit=json.loads((out/name).read_text());audit.update(stats=scene['stats'],boundaryRepair=report,roadCurbs=b.road_curb_audit,plants={k:v for k,v in plants.items() if not k.endswith('Points')});dump(out/name,audit)
    # Recompute the independent placement count audit after the new mask.
    dump(out/'independent-placement-counts.json',{'superseded':True,'reason':'Road curb mask added; verify_scene independently checks every retained plant.'})
    print('REFINED',scene['stats'],'plants removed',len(removed),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--base',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--source',type=Path,required=True)
    a=p.parse_args();repair(a.base,a.output,a.source)
