"""All foundation geometry checks on the serialized object-layer subset.

This preflight deliberately does not replace verify_tiles' complete registry,
immutable-parent, tile ownership, seam, BVH and transport checks.
"""
import argparse,gzip,json,gc
from pathlib import Path
import ijson
from prepare_foundations import verify_foundations


def check(root,out):
    print('FOUNDATION PREFLIGHT loading serialized object layer',flush=True)
    with gzip.open(root/'objects.json.gz','rb') as stream:
        layer=next(ijson.items(stream,'objectLayer',use_float=True))
    origin=json.loads((root/'tileset.json').read_text())['origin']
    city=dict(objectLayer=layer,originMSK=origin)
    scene=json.loads((root/'canonical/full/scene.json').read_text())
    gc.freeze()
    result=dict(passed=True,**verify_foundations(root,city,scene))
    out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);p.add_argument('out',type=Path)
    a=p.parse_args();check(a.root,a.out)
