"""Replace shared tree meshes in an immutable canonical version, then repack."""
import argparse,hashlib,json,shutil
from pathlib import Path
from custom_vegetation import install,verify
from object_geometry import export_glb

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--base',type=Path,required=True);ap.add_argument('--output',type=Path,required=True);a=ap.parse_args()
    if a.output.exists():raise ValueError('Choose a new version directory')
    assert json.loads((a.base/'validation.json').read_text())['passed']
    shutil.copytree(a.base,a.output);(a.output/'validation.json').unlink()
    folder=a.output/'canonical/full';city=json.loads((a.output/'canonical/urban-model.json').read_text())
    report=json.loads((a.output/'canonical/validation.json').read_text());manifest=json.loads((folder/'scene.json').read_text())
    previous_count=len(manifest['chunks']);lib=install(city['objectLayer'],manifest,folder)
    stats=city['objectLayer']['stats'];stats.update(treeTemplates=len(lib['models']),materials=len(manifest['materials']),
        uniqueObjectTriangles=sum(c['triangles'] for c in manifest['chunks'] if c.get('objectGeometry')),
        expandedObjectTriangles=sum(manifest['chunks'][i['mesh']]['triangles'] for i in manifest['instances'] if manifest['chunks'][i['mesh']].get('objectGeometry')))
    report['objectLayer'].update(stats);report['objectLayer']['customLibrary']=verify(city['objectLayer'],manifest,folder)
    revision=dict(version=4,type='custom-vegetation',parent=a.base.name,previousRevision=city['geometryRevision'],
        parentValidationSha256=hashlib.sha256((a.base/'validation.json').read_bytes()).hexdigest(),
        changedChunks=[dict(id=n,reason='custom-vegetation-model') for n in lib['sourceTemplates'].values()],
        newChunks=list(range(previous_count,len(manifest['chunks']))),
        terrainSha256=hashlib.sha256((a.output/'canonical/terrain.npz').read_bytes()).hexdigest())
    city['geometryRevision']=revision;report['geometryRevision']=revision
    manifest['stats'].update(uniqueTriangles=sum(c['triangles'] for c in manifest['chunks']),expandedTriangles=sum(manifest['chunks'][i['mesh']]['triangles'] for i in manifest['instances']))
    report['export'].update(triangles=manifest['stats']['uniqueTriangles'],expandedTriangles=manifest['stats']['expandedTriangles'],chunks=len(manifest['chunks']),downloadBytes=sum((folder/Path(c['file']).name).stat().st_size for c in manifest['chunks']),objectLayer=stats)
    (folder/'scene.json').write_text(json.dumps(manifest,ensure_ascii=False,separators=(',',':')));export_glb(manifest,folder)
    report['export']['glbBytes']=(folder/'model.glb').stat().st_size
    (a.output/'canonical/urban-model.json').write_text(json.dumps(city,ensure_ascii=False,separators=(',',':')))
    (a.output/'canonical/validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(json.dumps(report['objectLayer']['customLibrary'],ensure_ascii=False),flush=True)

if __name__=='__main__':main()
