"""Stream the audit registry and emit the small transport input for Node.

The canonical city can exceed V8's single-string limit. Mesh packing needs only
region metadata; the full provenance registry is serialized with Python's
incremental JSON encoder, without a giant intermediate JSON string.
"""
import gzip,json,sys,os
from pathlib import Path
from canonical_store import load_canonical,dump_compact

def dump_registry(registry, stream, batch_size=4096):
    """A batch is a storage operation only, never a geometry cut."""
    dump_compact(registry,stream,batch_size)

def prepare(root):
    root=Path(root)
    city=load_canonical(root/'canonical/urban-model.json')
    with (root/'canonical/validation.json').open() as f:report=json.load(f)
    if not report['passed']:raise ValueError('Canonical validation failed')
    with (root/'canonical/full/scene.json').open() as f:manifest=json.load(f)
    sources=[]
    for c in manifest['chunks']:
        row={k:c[k] for k in ('id','name','triangles')}
        if c.get('instanced'):row['instanced']=True
        elif c.get('sourceObjectIds'):row['sourceObjectIds']=c['sourceObjectIds']
        sources.append(row)
    registry=dict(version=1,sourceChunks=sources,features=[{k:f[k] for k in ('id','source','layer','properties','semantics')} for f in city['features']])
    for key in ('sourceSnapshot','roadPaint','objectLayer','streetLayer','railwayLayer','landscape','geometryRevision','groundRoadGeometry','tunnelWalls','sourceStyle','sourceStyleChecks','surfaces','relationships','roadNodes','roadInterfaces','gradeConnections','roadSeamRepairs','roadSeamChecks'):
        if key in city:registry[key]=city[key]
    if 'semantics' in report:registry['semantics']=report['semantics']
    temporary=root/'objects.json.gz.tmp'
    # This is the offline provenance registry, not a rendered mesh payload.
    # Prefer fast lossless compression for large regional builds; mesh/BVH
    # downloads keep their existing compression and byte validation.
    level=int(os.environ.get('NURAY_REGISTRY_COMPRESSION_LEVEL','1'))
    if not 0<=level<=9:raise ValueError('Registry compression level must be 0..9')
    with gzip.open(temporary,'wt',encoding='utf-8',compresslevel=level) as f:
        dump_registry(registry,f)
    temporary.replace(root/'objects.json.gz')
    metadata={k:city[k] for k in ('name','crsProj','sourceSnapshot','boundsMSK','originMSK','transportTileSizeM','limitations') if k in city}
    fields={'objectLayer':('stats','policy','variation','customLibrary','roofs','pitchedRoofs'),
            'railwayLayer':('stats','policy','texture'),
            'streetLayer':('stats','policy','witnessViews','fences')}
    for key,names in fields.items():
        if key not in city:continue
        metadata[key]={k:city[key][k] for k in names if k in city[key]}
    if city.get('objectLayer',{}).get('foundations'):
        metadata['objectLayer']['foundations']={k:city['objectLayer']['foundations'][k] for k in ('stats','policy')}
    (root/'canonical/transport-metadata.json').write_text(json.dumps(metadata,ensure_ascii=False,separators=(',',':')))
    print('TRANSPORT METADATA',len(city['features']),'features',len(city['surfaces']),'surfaces',flush=True)

if __name__=='__main__':prepare(sys.argv[1])
