"""Assemble a fresh canonical surface into a validated city release.

The viewer configuration is deliberately outside this command: inspect the
result in a preview tab before activating it. Existing outputs are not erased.
"""
from pathlib import Path
import argparse
import json
import os
import subprocess
import sys
import ijson
from verify_snapshot import verify
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'prototype/tiling'))
from canonical_store import open_canonical,archive_intermediate_glb


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--snapshot',required=True,type=Path)
    parser.add_argument('--surface',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--node',required=True)
    parser.add_argument('--inventory',required=True,type=Path)
    resume=parser.add_mutually_exclusive_group()
    resume.add_argument('--resume-packed',choices=('rail','street'),help='Resume at independent verification of an already packed artifact from this same capture')
    resume.add_argument('--resume-objects',action='store_true',help='Reuse the completed object stage from this same capture and regenerate only the railway stage onward')
    args=parser.parse_args()
    repo=Path(__file__).resolve().parents[2]
    tiling=repo/'prototype/tiling'
    snapshot=args.snapshot.resolve();surface=args.surface.resolve();output=args.output.resolve()
    verify(snapshot)
    report=json.loads((surface/'canonical/validation.json').read_text())
    if not report['passed']:raise ValueError('Canonical surface validation failed')
    # The source receipt is the only field needed here. Stream past the millions
    # of surface rows instead of materializing another complete city in RAM.
    with open_canonical(surface/'canonical/urban-model.json','rb') as stream:
        source_snapshot=next(ijson.items(stream,'sourceSnapshot',use_float=True),None)
    if not source_snapshot or Path(source_snapshot['path']).resolve()!=snapshot or not source_snapshot['freshAcquisition']:
        raise ValueError('Surface belongs to another source capture')
    archive_intermediate_glb(surface)
    objects=output.with_name(output.name+'-objects')
    rail=output.with_name(output.name+'-rail')
    street=output.with_name(output.name+'-street')
    py=sys.executable;node=args.node;inventory=args.inventory.resolve()
    commands=[
        [py,str(tiling/'prepare_objects.py'),'--base',str(surface),'--extraction',str(snapshot/'extraction'),'--output',str(objects)],
        [py,str(tiling/'prepare_railways.py'),'--base',str(objects),'--output',str(rail)],
        [node,str(tiling/'pack_tiles.mjs'),str(rail)],
        [py,str(tiling/'verify_tiles.py'),str(rail)],
        [py,str(repo/'scripts/audit_source_catalog.py'),'--release',str(rail),'--source',str(snapshot),
            '--library-audit',str(snapshot/'extraction/library-audit.json'),'--output',str(inventory)],
        [py,str(tiling/'prepare_street_objects.py'),'--base',str(rail),'--output',str(street),
            '--evidence',str(inventory/'placement-evidence.json.gz'),'--inventory',str(inventory/'inventory.json')],
        [node,str(tiling/'pack_tiles.mjs'),str(street)],
        [py,str(tiling/'verify_tiles.py'),str(street)],
        [py,str(tiling/'build_release.py'),'--base',str(street),'--output',str(output),
            '--node',node,'--inventory',str(inventory/'inventory.json')],
    ]
    env=dict(os.environ,PYTHON=py)
    first=1
    if args.resume_objects:
        object_report=json.loads((objects/'canonical/validation.json').read_text())
        with open_canonical(objects/'canonical/urban-model.json','rb') as stream:
            object_snapshot=next(ijson.items(stream,'sourceSnapshot',use_float=True),None)
        if not object_report['passed'] or not object_report.get('objectLayer',{}).get('passed') or object_snapshot!=source_snapshot:
            raise ValueError('Object artifact is incomplete or belongs to another source capture')
        first=2
        print('RESUME FROM VERIFIED OBJECT PLACEMENT',objects,flush=True)
    if args.resume_packed:
        packed=rail if args.resume_packed=='rail' else street
        with (packed/'tileset.json').open() as f:catalog=json.load(f)
        if catalog.get('sourceSnapshot')!=source_snapshot:
            raise ValueError('Packed artifact belongs to another source capture')
        first=4 if args.resume_packed=='rail' else 8
        print('RESUME AT INDEPENDENT TILE VERIFICATION',packed,flush=True)
    for index,command in enumerate(commands,1):
        if index<first:continue
        print('CITY STAGE',index,'/',len(commands),Path(command[1]).name,flush=True)
        subprocess.run(command,check=True,env=env,cwd=repo)
        if index in (1,2,6):archive_intermediate_glb({1:objects,2:rail,6:street}[index])
    print('FRESH CITY RELEASE VERIFIED',output,flush=True)


if __name__=='__main__':main()
