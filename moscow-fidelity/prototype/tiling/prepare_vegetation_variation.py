"""Update instance transforms in a new version; retain all packed meshes/BVHs."""
import argparse,gzip,hashlib,json,shutil
from pathlib import Path
import numpy as np
from vegetation_variation import apply,verify
from object_geometry import export_glb

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--base',type=Path,required=True);ap.add_argument('--output',type=Path,required=True)
    a=ap.parse_args();base=a.base;out=a.output
    if out.exists():raise ValueError('Choose a new version directory')
    receipt=json.loads((base/'validation.json').read_text());assert receipt['passed']
    shutil.copytree(base,out)
    # A parent's successful receipt must never validate a partially built child.
    (out/'validation.json').unlink()
    city=json.loads((out/'canonical/urban-model.json').read_text())
    report=json.loads((out/'canonical/validation.json').read_text())
    scene=json.loads((out/'canonical/full/scene.json').read_text())
    apply(city['objectLayer'],scene);result=verify(city['objectLayer'],scene)
    revision=dict(version=3,type='vegetation-variation',parent=base.name,previousRevision=city.get('geometryRevision'),
        terrainSha256=hashlib.sha256((out/'canonical/terrain.npz').read_bytes()).hexdigest(),
        parentValidationSha256=hashlib.sha256((base/'validation.json').read_bytes()).hexdigest())
    city['geometryRevision']=revision;report['geometryRevision']=revision
    city['rules']['vegetationVariation']=city['objectLayer']['variation']
    report['objectLayer']['variation']=result
    (out/'canonical/full/scene.json').write_text(json.dumps(scene,ensure_ascii=False,separators=(',',':')))
    export_glb(scene,out/'canonical/full')
    report['export']['glbBytes']=(out/'canonical/full/model.glb').stat().st_size
    (out/'canonical/urban-model.json').write_text(json.dumps(city,ensure_ascii=False,separators=(',',':')))
    (out/'canonical/validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    registry=json.loads(gzip.decompress((out/'objects.json.gz').read_bytes()))
    registry.update(objectLayer=city['objectLayer'],geometryRevision=revision)
    (out/'objects.json.gz').write_bytes(gzip.compress(json.dumps(registry,ensure_ascii=False,separators=(',',':')).encode(),mtime=0))
    catalog=json.loads((out/'tileset.json').read_text());assets={c['id']:c for c in catalog['chunks']}
    instances={i['id']:i for r in city['objectLayer']['vegetation'] for i in r['renderInstances']}
    for tile in catalog['tiles']:
        tile['instances']=[{**instances[i['id']],'mesh':i['mesh']} for i in tile['instances']]
        bounds=[assets[k]['bounds'] for k in tile['chunks']]
        for i in tile['instances']:
            b=assets[i['mesh']]['bounds'];corners=np.array([[b['max' if bits&(1<<axis) else 'min'][axis] for axis in range(3)] for bits in range(8)])
            m=np.array(i['matrix']).reshape(3,4);world=corners@m[:,:3].T+m[:,3]
            bounds.append(dict(min=world.min(0).tolist(),max=world.max(0).tolist()))
        if bounds:
            tile['contentBounds']=dict(min=np.min([b['min'] for b in bounds],axis=0).tolist(),max=np.max([b['max'] for b in bounds],axis=0).tolist())
            tile['bounds']['min'][1]=tile['contentBounds']['min'][1];tile['bounds']['max'][1]=tile['contentBounds']['max'][1]
    catalog['objectLayer']['policy']=city['objectLayer']['policy']
    catalog['objectLayer']['variation']=city['objectLayer']['variation']
    (out/'tileset.json').write_text(json.dumps(catalog,ensure_ascii=False,separators=(',',':')))
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
