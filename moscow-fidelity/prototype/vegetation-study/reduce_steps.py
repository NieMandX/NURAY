"""Three cumulative 20% reductions of the accepted compact tree, foliage only.

Run with Blender --background --factory-startup --python .../reduce_steps.py.
The target is the WHOLE tree's triangle count; wood is kept byte-for-byte.
"""
from pathlib import Path
import sys, json, hashlib
import bpy
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parent))
import build
from optimize import mesh_object, copy_object, apply, geometry


def main():
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    report_path=build.OUT/'optimization.json'
    report=json.loads(report_path.read_text())
    source_id='compact-reduced-35'
    source_path=build.OUT/source_id/'geometry.npz'
    source_hash=hashlib.sha256(source_path.read_bytes()).hexdigest()
    assert report['sourceGeometrySha256']==hashlib.sha256((build.OUT/'compact/geometry.npz').read_bytes()).hexdigest(), 'Stale union experiment'
    source=np.load(source_path)
    attrs,mats=source['attributes'],source['materials']
    wood=mats>=4
    wood_attrs,wood_mats=attrs[wood],mats[wood]
    palette=json.loads((build.OUT/'catalog.json').read_text())['materials']
    materials=[bpy.data.materials.new(m['name']) for m in palette]
    current=mesh_object('accepted-crown',attrs[~wood,:,:3],mats[~wood],materials)
    previous_total=len(attrs)
    previous_id=source_id
    stages=[]
    for stage in range(1,4):
        # A closed triangular surface has an even triangle count. Round to the
        # closest achievable total, then allocate the reduction to foliage.
        target_total=2*round(previous_total*.8/2)
        target_foliage=target_total-len(wood_attrs)
        assert target_foliage>0
        current=copy_object(current,f'cumulative-stage-{stage}')
        current.data.calc_loop_triangles()
        input_foliage=len(current.data.loop_triangles)
        decimate=current.modifiers.new('Next 20 percent', 'DECIMATE')
        decimate.decimate_type='COLLAPSE'
        # A small sub-triangle margin avoids truncating float32 ratios down to
        # the next lower pair of triangles; it does not change the target.
        decimate.ratio=(target_foliage+.1)/input_foliage
        decimate.use_collapse_triangulate=True
        apply(current,decimate)
        foliage,foliage_mats,quality=geometry(current)
        output=np.concatenate([wood_attrs,foliage])
        output_mats=np.concatenate([wood_mats,foliage_mats])
        assert np.array_equal(output[:len(wood_attrs)],wood_attrs)
        assert abs(len(output)-target_total)<=2, 'Unexpected simplification count'
        key=f'compact-step-{stage}'
        folder=build.OUT/key
        meta=build.export(folder,output,output_mats,palette)
        assert meta['triangles']==len(output)
        result=dict(id=key,label=f'Ступень {stage} · ещё −20%',
            description=f'Ступень {stage}: примерно на 20% меньше треугольников, чем на предыдущей. Упрощена только листва; ствол и ветви сохранены.',
            stage=stage,previousVariant=previous_id,previousTriangles=previous_total,targetTriangles=target_total,
            reductionFromPrevious=1-len(output)/previous_total,reductionFromStepBase=1-len(output)/len(attrs),
            triangles=meta['triangles'],foliageTriangles=len(foliage),woodTriangles=len(wood_attrs),
            bounds=meta['bounds'],meshBytes=(folder/'mesh-000.bin.gz').stat().st_size,
            glbBytes=(folder/'model.glb').stat().st_size,**quality)
        stages.append(result)
        previous_id,previous_total=key,len(output)
        print(json.dumps(result,ensure_ascii=False),flush=True)
    assert hashlib.sha256(source_path.read_bytes()).hexdigest()==source_hash
    report['variants']=[v for v in report['variants'] if not v.get('stage')]+stages
    report['reductionSteps']=dict(baseVariant=source_id,baseTriangles=len(attrs),baseGeometrySha256=source_hash,
        factor=.8,scope='total-triangle-count; foliage-only edits; cumulative from previous stage',
        variants=[s['id'] for s in stages])
    report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
