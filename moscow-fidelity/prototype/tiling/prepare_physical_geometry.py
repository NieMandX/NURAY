"""Create a new release containing physical city objects only."""
from pathlib import Path
import argparse, gzip, hashlib, json, shutil
from physical_geometry import ownership, filter_mesh, read, partition, receipt, classify, audit, validate_policy
from object_geometry import export_glb


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--base',type=Path,required=True);ap.add_argument('--output',type=Path,required=True);args=ap.parse_args()
    assert args.base.resolve().parent==args.output.resolve().parent, 'Keep immutable release parents adjacent'
    assert not args.output.exists(), 'Do not overwrite a release'
    city=json.loads((args.base/'canonical/urban-model.json').read_text())
    manifest=json.loads((args.base/'canonical/full/scene.json').read_text())
    report=json.loads((args.base/'canonical/validation.json').read_text())
    parent_proof=(args.base/'validation.json').read_bytes();assert report['passed'] and json.loads(parent_proof)['passed']
    kept,excluded=partition(city['objectLayer']['buildings']);excluded_ids={r['id'] for r in excluded}
    owners=ownership(args.base,city,manifest)
    # Ownership is established before any output is written. Old transport pages
    # are regenerated; copy only reusable canonical assets, textures and library.
    args.output.mkdir()
    for name in ['canonical','textures','library']:
        if (args.base/name).exists():shutil.copytree(args.base/name,args.output/name)
    changed=[];folder=args.output/'canonical/full'
    for i,c in enumerate(manifest['chunks']):
        if c['id'] not in owners:continue
        before=read(args.base,c);after,meta=filter_mesh(before,c,owners[c['id']],excluded_ids)
        if after==before:continue
        (folder/Path(c['file']).name).write_bytes(gzip.compress(after,mtime=0))
        manifest['chunks'][i]=meta
        changed.append(dict(id=c['id'],name=c['name'],beforeSha256=hashlib.sha256(before).hexdigest(),afterSha256=hashlib.sha256(after).hexdigest(),removedTriangles=c['triangles']-meta['triangles']))
    layer=city['objectLayer'];layer['buildings']=kept;layer['sourceGeometry']=receipt(excluded)
    for f in city['features']:f['semantics']=classify(f['layer'],f['properties'],f['geometryType'])
    report['semantics']=audit(city['features']);assert report['semantics']['passed']
    layer['stats'].update(buildingObjects=len(kept),ordinaryBuildingObjects=sum(r['category']=='building' for r in kept),detailedModelGroups=sum(r['category']=='landmark' for r in kept),
        uniqueObjectTriangles=sum(c['triangles'] for c in manifest['chunks'] if c.get('objectGeometry')),
        expandedObjectTriangles=sum(manifest['chunks'][i['mesh']]['triangles'] for i in manifest['instances'] if manifest['chunks'][i['mesh']].get('objectGeometry')))
    manifest['stats'].update(uniqueTriangles=sum(c['triangles'] for c in manifest['chunks']),expandedTriangles=sum(manifest['chunks'][i['mesh']]['triangles'] for i in manifest['instances']))
    revision=dict(version=1,type='physical-source',parent=args.base.name,previousRevision=city.get('geometryRevision'),parentValidationSha256=hashlib.sha256(parent_proof).hexdigest(),changedChunks=changed)
    city['geometryRevision']=revision;report['geometryRevision']=revision
    report['sourceGeometry']=validate_policy(city,manifest)
    report['objectLayer']=dict(passed=True,**layer['stats'])
    report['export'].update(objectLayer=layer['stats'],triangles=manifest['stats']['uniqueTriangles'],expandedTriangles=manifest['stats']['expandedTriangles'],downloadBytes=sum((folder/Path(c['file']).name).stat().st_size for c in manifest['chunks']))
    (folder/'scene.json').write_text(json.dumps(manifest,ensure_ascii=False,separators=(',',':')))
    export_glb(manifest,folder);report['export']['glbBytes']=(folder/'model.glb').stat().st_size
    (args.output/'canonical/urban-model.json').write_text(json.dumps(city,ensure_ascii=False,separators=(',',':')))
    (args.output/'canonical/validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(json.dumps(dict(excluded=layer['sourceGeometry']['excludedObjects'],changedChunks=changed,stats=layer['stats']),ensure_ascii=False),flush=True)

if __name__=='__main__':main()
