"""Finish an unpublished transport revision after newly discovered rail mouths."""
import sys,json,pickle,hashlib
from pathlib import Path
import numpy as np
import shapely as sh
from streaming_json import Document
from prepare_railway_entries import load_terrain,passages,meshes,near_passages
from interface_validation import passage_volumes,check_interfaces
from transport_planting import plan,apply
from prepare_foundations import save,refresh_stats,digest
from object_geometry import export_glb

root=Path(sys.argv[1]);doc=Document(root/'canonical/urban-model.json')
assert not (root/'validation.json').exists()
revision=doc.read('geometryRevision');assert revision['type']=='transport-surfaces'
assert 'plantingRepartition' not in revision
base=root.parent/revision['parent'];before=Document(base/'canonical/urban-model.json')
interfaces=doc.read('roadInterfaces');scene=json.loads((root/'canonical/full/scene.json').read_text())
old=json.loads((base/'canonical/full/scene.json').read_text());origin=np.asarray(doc.read('originMSK'))
dem,tree=load_terrain(root)
print('REPARTITION TRANSPORT PLANTING',flush=True)
landscape,proof,faces=plan(before,interfaces,dem,tree)
print('PLANTING PLAN',len(proof['removedSurfaceIds']),len(proof['newSurfaces']),proof['loweredAreaM2'],flush=True)
product=root/'transport-planting.pkl'
with product.open('wb') as f:pickle.dump(dict(landscape=landscape,proof=proof,faces=faces),f)
changes=apply(base,root,scene,old,proof,faces,landscape,origin)
assert not ({c['id'] for c in changes}&{c['id'] for c in revision['changedChunks']})
removed=set(proof['removedSurfaceIds'])
assert not removed.intersection(revision['groundPartition']['clippedSurfaceIds'])
revision['changedChunks'].extend(changes);revision['plantingRepartition']=proof
report=json.loads((root/'canonical/validation.json').read_text())
report.update(landscape=landscape,geometryRevision=revision)
save(root/'canonical/full/scene.json',scene)
patch=sh.geometry.shape(proof['sideMask'])
near=[r for r in interfaces if sh.geometry.shape(r['mouthGeometry']).intersects(patch.buffer(2))]
wanted={p for r in near for e in r['ends'] for p in e['parents']}
city=dict(originMSK=origin,features=doc.read('features'),roadInterfaces=near,
          surfaces=[s for s in before.items('surfaces') if s.get('owner') in wanted and s['kind'].startswith('roadbed')])
for label,volumes in [('interfaces',passage_volumes(city)),
                     ('rail-width',passages(city,[r for r in near if any(e['kind']=='railway_ground' for e in r['ends'])],dem,tree))]:
    audit=check_interfaces(volumes,near_passages(meshes(root,scene),volumes))
    save(root/f'planting-{label}-preflight.json',audit)
    assert audit['passed'],[r for r in audit['checks'] if not r['passed']]
    print('PLANTING PREFLIGHT',label,len(volumes),'PASSED',flush=True)
def rows():
    for s in doc.items('surfaces'):
        if s['id'] not in removed:yield s
    yield from proof['newSurfaces']
doc.rewrite(root/'canonical/urban-model.json',dict(landscape=landscape,geometryRevision=revision),dict(surfaces=rows))
refresh_stats(scene,report,root);save(root/'canonical/full/scene.json',scene)
export_glb(scene,root/'canonical/full');report['export']['glbBytes']=(root/'canonical/full/model.glb').stat().st_size
save(root/'canonical/validation.json',report)
print('TRANSPORT PLANTING REPARTITION COMPLETE',flush=True)
