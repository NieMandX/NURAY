"""Incremental shaft correction. Reuse terrain, streets, plants and all other meshes."""
import argparse,collections,hashlib,json,pickle,shutil
from pathlib import Path
import numpy as np
import shapely as sh
from build_scene import Builder,Terrain,dump
from industrial_chimneys import detect,emit
from apply_crossfall import unpack
from object_geometry import pack
from canonical_store import copy_asset


def replacement_mask(triangles,group,alt):
    xy=triangles[:,:,[0,2]]*[1,-1]
    domain=group['parts'][0]['outer'].buffer(.002)
    inside=sh.covers(domain,sh.points(xy)).all(1)
    # Terrain-conforming walls retain their full-height upper endpoint. The
    # adjoining low industrial building shares an edge, but is a separate
    # object and must not lose that wall. A height gap isolates the shaft.
    high=triangles[:,:,1].max(1)>group['baseLocal']+min(p['height'] for p in group['parts'])-2
    return inside&high


def apply(base,out,source):
    if out.exists():raise ValueError('Use a new immutable output directory')
    parent=json.loads((base/'canonical/full/scene.json').read_text())
    if any(c['name']=='industrial-chimneys' for c in parent['chunks']):raise ValueError('Already corrected')
    rows,*_=pickle.load(open(source/'projected-scene-v1.pickle','rb'))
    buildings=[(f,g) for f,g,l in rows if f['layer']=='building']
    groups=detect(buildings)
    if not groups:raise ValueError('No unambiguous nested circular shaft groups')
    terrain=Terrain(np.load(base/'canonical/terrain.npz')['triangles']);alt=parent['origin'][2]
    for group in groups:
        xy=np.asarray(group['parts'][0]['outer'].exterior.coords)
        group['baseLocal']=float(np.max(terrain.sample(xy)))+.1-alt
    shutil.copytree(base,out,copy_function=copy_asset,ignore=shutil.ignore_patterns('merged','meshes.pack','mesh-pack.json','delivery-*','.DS_Store'))
    # The parent's transport verdict is not a verdict for changed geometry.
    dump(out/'validation.json',dict(passed=False,pending='Revalidate corrected shaft transport and retained city geometry',parent=base.name))
    full=out/'canonical/full';scene=json.loads((full/'scene.json').read_text());changed=[];counts=[];unchanged=[];lineage={}
    for chunk in scene['chunks']:
        original=base/'canonical/full'/chunk['file']
        if chunk['name']=='buildings':
            t,m,tint=unpack(full,chunk);remove=np.zeros(len(t),bool)
            for group in groups:remove|=replacement_mask(t,group,alt)
            if remove.any():
                kept=~remove
                if not kept.any():raise ValueError('Unexpected empty shared building batch')
                # Preserve packed retained words directly, avoiding normal/UV
                # roundtrips that could affect unrelated buildings.
                import gzip
                raw=gzip.decompress(original.read_bytes());v=raw[:chunk['vertexBytes']]
                ix=np.frombuffer(raw[chunk['vertexBytes']:],'<u4').reshape(-1,3)[kept]
                with gzip.GzipFile(filename=str(full/chunk['file']),mode='wb',mtime=0,compresslevel=6) as stream:stream.write(v);stream.write(ix.tobytes())
                chunk['triangles']=len(ix);chunk['bounds']=dict(min=t[kept,:,:3].min((0,1)).tolist(),max=t[kept,:,:3].max((0,1)).tolist())
                changed.append(chunk['id']);counts.append(dict(chunk=chunk['id'],removed=int(remove.sum()),retained=int(kept.sum())))
                lineage[str(chunk['id'])]=np.flatnonzero(kept).astype('<u4')
                continue
        unchanged.append(dict(chunk=chunk['id'],sha256=hashlib.sha256(original.read_bytes()).hexdigest()))
    if not changed:raise ValueError('Source groups not found in existing generic meshes')
    b=Builder.__new__(Builder);b.full=full;b.alt=alt;b.terrain=terrain;b.materials=scene['materials'];b.chunks=scene['chunks'];b.instances=scene['instances'];b.building_tops=[];b.batches=collections.defaultdict(list);b.batch_counts=collections.Counter()
    emit(b,groups)
    for name in list(b.batches):b.flush(name)
    changed.extend(c['id'] for c in b.chunks[len(parent['chunks']):])
    scene['stats']=dict(uniqueTriangles=sum(c['triangles'] for c in b.chunks),expandedTriangles=sum(b.chunks[i['mesh']]['triangles'] for i in b.instances))
    report=dict(version=1,parent=base.name,changedChunks=changed,changedBuildingBatches=counts,unchangedChunks=unchanged,
      policy='Nested concentric circular urban-structure rings, monotonically decreasing radius and increasing height; no object IDs or city coordinates in classification. Retain source center, height and radius envelopes. Single/ambiguous towers untouched.',
      groundAndInstanceTransformsUnchanged=True,groups=[])
    for group in groups:
        center=group['center'].tolist();ids=[str(p['feature']['id']) for p in group['parts']]
        report['groups'].append(dict(sourceIds=ids,centerEastNorth=center,heightM=group['height'],baseLocalM=group['baseLocal'],lowestStepHeightM=min(p['height'] for p in group['parts']),baseRadiusM=group['baseRadius'],topRadiusM=group['topRadius'],bands=8))
    g=groups[0];x,y=g['center'];camera=dict(yaw=-4.57,pitch=.25,distance=340,target=[float(x),g['baseLocal']+g['height']*.48,float(-y)])
    scene.setdefault('witnessViews',{})['chimney-review']=camera
    scene.setdefault('witnessViewLabels',{})['chimney-review']='Заводская труба · плавное сужение'
    revision=dict(version='yandex-industrial-chimney-1',parent=base.name)
    for name in ('urban-model.json','transport-metadata.json'):
        path=out/'canonical'/name
        if path.exists():
            city=json.loads(path.read_text());city['geometryRevision']=revision;city['industrialChimneys']={k:v for k,v in report.items() if k!='unchangedChunks'};dump(path,city)
    validation=json.loads((out/'canonical/validation.json').read_text());validation['industrialChimneys']=report;validation['stats']=scene['stats']
    # Verify every new surface before allowing transport/export.
    for c in b.chunks[len(parent['chunks']):]:
        t,m,tint=unpack(full,c);normal=np.cross(t[:,1,:3]-t[:,0,:3],t[:,2,:3]-t[:,0,:3])
        assert np.isfinite(t).all() and np.all((normal*t[:,:,3:6].mean(1)).sum(1)>0)
    assert parent['instances']==scene['instances'][:len(parent['instances'])]
    for row in unchanged:
        c=scene['chunks'][row['chunk']];assert hashlib.sha256((full/c['file']).read_bytes()).hexdigest()==row['sha256']
    np.savez_compressed(out/'canonical/chimney-retained-primitives.npz',**lineage)
    report['retainedPrimitivesSha256']=hashlib.sha256((out/'canonical/chimney-retained-primitives.npz').read_bytes()).hexdigest()
    dump(full/'scene.json',scene);dump(out/'canonical/validation.json',validation);dump(out/'industrial-chimneys.json',report)
    dump(out/'chimney-patch.json',dict(changedChunks=changed,geometryRevision=revision,witnessViews=scene['witnessViews']))
    print(json.dumps({k:v for k,v in report.items() if k!='unchangedChunks'},ensure_ascii=False),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--base',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--source',type=Path,required=True)
    a=p.parse_args();apply(a.base,a.output,a.source)
