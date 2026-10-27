"""Remove Float32-collapsed paint from an unpublished draft, retaining a witness."""
import sys,json,shutil
from pathlib import Path
import numpy as np
from streaming_json import Document
from prepare_road_paint import read,write
from paint_domain import paint_projection_mask
from prepare_foundations import digest,save,refresh_stats
from object_geometry import export_glb

def cleanup(root):
    assert not (root/'validation.json').exists(),'Published releases are immutable'
    doc=Document(root/'canonical/urban-model.json');revision=doc.read('geometryRevision')
    assert revision['type']=='transport-surfaces'
    road=doc.read('roadPaint');assert road['validation']['passed']
    scene=json.loads((root/'canonical/full/scene.json').read_text())
    report=json.loads((root/'canonical/validation.json').read_text())
    removed=0;witness=[]
    for cid in revision['newChunks']:
        c=scene['chunks'][cid];assert c['name']=='paint'
        w=read(root,c);keep=paint_projection_mask(w.view('<f4')[:,:,:3])
        if keep.all():continue
        before=dict(c);path=root/'canonical/full'/Path(c['file']).name
        backup=root/'canonical/full'/f'paint-projection-before-{cid}.bin.gz'
        assert not backup.exists(),'Partial cleanup already has a witness; inspect before retrying'
        shutil.copyfile(path,backup);before['file']=backup.name
        n=int((~keep).sum());removed+=n
        witness.append(dict(id=cid,before=before,beforeSha256=digest(backup),removedTriangles=n))
        c.update(write(path,w[keep]))
        assert np.array_equal(read(root,c),w[keep])
    if not removed:return
    proof=dict(chunks=witness,removedTriangles=removed,policy='Discard only zero XZ area after Float32 packing; preserve all remaining vertex attributes exactly.')
    revision['paint']['collapsedProjectionTriangles']=revision['paint'].get('collapsedProjectionTriangles',0)+removed
    revision['paintProjectionCleanup']=proof
    road['tierRestoration']=revision['paint']
    road['validation']['preCleanupTrianglesChecked']=road['validation']['trianglesChecked']
    road['validation']['trianglesChecked']-=removed
    road['validation']['projectionCleanup']=proof
    report.update(geometryRevision=revision,roadPaint=road)
    doc.rewrite(root/'canonical/urban-model.json',dict(geometryRevision=revision,roadPaint=road))
    refresh_stats(scene,report,root);save(root/'canonical/full/scene.json',scene)
    export_glb(scene,root/'canonical/full')
    report['export']['glbBytes']=(root/'canonical/full/model.glb').stat().st_size
    save(root/'canonical/validation.json',report)
    work=json.loads((root/'transport-surface-work.json').read_text());work['paint']=revision['paint'];save(root/'transport-surface-work.json',work)
    print('DISCARDED COLLAPSED PAINT',removed,'remaining validation count',road['validation']['trianglesChecked'],flush=True)

if __name__=='__main__':cleanup(Path(sys.argv[1]))
