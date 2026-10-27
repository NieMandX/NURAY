"""Prepare immutable foliage fragments; optional legacy LODs require Blender."""
from pathlib import Path
import sys,json,gzip,hashlib
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parent))
import build

def encode(attributes,pivot=None):
    p=attributes[:,:,:3].copy()
    if pivot is not None:p-=pivot
    v,ix=np.unique(p.reshape(-1,3),axis=0,return_inverse=True)
    return dict(positions=v.ravel().tolist(),indices=ix.tolist(),triangles=len(p))

def main(model='birch',fragments_only=False):
    if not fragments_only:
        import bpy
        from optimize import mesh_object,copy_object,apply,geometry
        for obj in list(bpy.data.objects):bpy.data.objects.remove(obj,do_unlink=True)
    root=build.OUT/model
    data=np.load(root/'geometry.npz');a,m=data['attributes'],data['materials']
    catalog=json.loads((build.OUT/'catalog.json').read_text())
    row=next(r for r in catalog['models'] if r['id']==model)
    check,check_mats,parts=build.make(model,row['sourceBounds'])
    assert np.array_equal(a,check)
    assert np.array_equal(m,check_mats)
    build.validate(check,parts)
    wood=m>=4
    wood_mesh=encode(a[wood]);wood_mesh['materials']=m[wood].tolist()
    materials=[bpy.data.materials.new(x['name']) for x in catalog['materials']] if not fragments_only else []
    fragments=[]
    for index,part in enumerate(parts):
        if part['kind']!='foliage':continue
        first,last=part['start'],part['end'];pivot=np.array(part['pivot'])
        assert len(np.unique(m[first:last]))==1
        levels=[encode(a[first:last],pivot)]
        if not fragments_only:
            original=mesh_object(f'fragment-{index}',a[first:last,:,:3],m[first:last],materials)
            for target in range(last-first-2,3,-2):
                obj=copy_object(original,f'fragment-{index}-{target}')
                mod=obj.modifiers.new('Reduce fragment','DECIMATE');mod.decimate_type='COLLAPSE'
                mod.ratio=(target+.1)/(last-first);mod.use_collapse_triangulate=True
                apply(obj,mod)
                simplified,_,quality=geometry(obj)
                assert len(simplified)==target and quality['closed']
                levels.append(encode(simplified,pivot))
                bpy.data.objects.remove(obj,do_unlink=True)
            bpy.data.objects.remove(original,do_unlink=True)
        fragments.append(dict(id=f'{model}-foliage-{index}',pivot=pivot.tolist(),material=int(m[first]),levels=levels))
    result=dict(version=1,model=model,label=row['label'],baseGeometrySha256=hashlib.sha256((root/'geometry.npz').read_bytes()).hexdigest(),
        wood=wood_mesh,fragments=fragments,materials=catalog['materials'],axisConvention='Y-up',
        baseline='Current source model; scale 100% and zero rotations reproduce it.')
    with gzip.GzipFile(filename=str(root/'editor.json.gz'),mode='wb',mtime=0) as f:
        f.write(json.dumps(result,separators=(',',':')).encode())
    print('Editor ready:',len(fragments),'fragments,',sum(len(x['levels']) for x in fragments),'closed LODs')

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument('--model',choices=[m[0] for m in build.MODELS],default='birch')
    parser.add_argument('--fragments-only',action='store_true')
    argv=sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else ([] if 'bpy' in sys.modules else None)
    args=parser.parse_args(argv)
    main(args.model,args.fragments_only)
