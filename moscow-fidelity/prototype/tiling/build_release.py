"""Required final city stages: refine globally, tile, validate serialized output.

The input is the canonical source/object/railway build. Publication or viewer
activation must use the output only after this command exits successfully.
"""
from pathlib import Path
import argparse,json,shutil,subprocess,sys
from canonical_store import archive_intermediate_glb

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--base',type=Path,required=True)
    ap.add_argument('--output',type=Path,required=True)
    ap.add_argument('--node',default=shutil.which('node'))
    ap.add_argument('--inventory',type=Path,default=Path(__file__).resolve().parents[2]/'diagnostics/source-catalog/inventory.json')
    ap.add_argument('--start-stage',type=int,default=1,help='Resume at a numbered stage; each retained input is still validated by the stage that consumes it')
    ap.add_argument('--reuse-landscape',type=Path,help='Validated same-parent partition cache for stage 1')
    args=ap.parse_args()
    if not args.node:ap.error('Node.js is required; supply --node /path/to/node')
    here=Path(__file__).resolve().parent
    # These counts are written by the same canonical generators and checked
    # against the serialized objects by verify_tiles. Loading several GB of
    # surface polygons just to select two stages wastes time and peak memory.
    base_report=json.loads((args.base/'canonical/validation.json').read_text())
    if not base_report['passed']:raise ValueError('Canonical parent validation failed')
    has_buildings=bool(base_report.get('objectLayer',{}).get('buildingObjects',0))
    has_fences=bool(base_report.get('streetLayer',{}).get('byLayer',{}).get('Fence',0))
    cleared=args.output.with_name(args.output.name+'-paint-base')
    painted=args.output.with_name(args.output.name+'-water-base')
    assembled=args.output.with_name(args.output.name+'-boundary-base')
    surface=assembled.with_name(assembled.name+'-surface-base') if has_fences else assembled
    landscape=surface.with_name(surface.name+'-landscape-base') if has_buildings else surface
    commands=[
        [sys.executable,str(here/'prepare_landscape.py'),'--base',str(args.base),'--output',str(landscape)],
        [args.node,str(here/'pack_tiles.mjs'),str(landscape)],
        [sys.executable,str(here/'verify_tiles.py'),str(landscape)],
    ]
    # Foundation bottoms must use finished paths, lawns and curbs. Keep the
    # validated intermediate as immutable provenance for the final release.
    if has_buildings:commands += [
        [sys.executable,str(here/'prepare_foundations.py'),'--base',str(landscape),'--output',str(surface)],
        [args.node,str(here/'pack_tiles.mjs'),str(surface)],
        [sys.executable,str(here/'verify_tiles.py'),str(surface)],
    ]
    # Fences follow finished paths/curbs too; never inherit an obsolete ground
    # profile from the earlier street-object import stage.
    if has_fences:commands += [
        [sys.executable,str(here/'prepare_fence_types.py'),'--base',str(surface),'--output',str(assembled),'--inventory',str(args.inventory)],
        [sys.executable,str(here/'preview_fences.py'),str(assembled)],
        [args.node,str(here/'pack_tiles.mjs'),str(assembled)],
        [sys.executable,str(here/'verify_tiles.py'),str(assembled)],
    ]
    commands += [
        [sys.executable,str(here/'prepare_passage_clearance.py'),'--base',str(assembled),'--output',str(cleared)],
        [args.node,str(here/'pack_tiles.mjs'),str(cleared)],
        [sys.executable,str(here/'verify_tiles.py'),str(cleared)],
        [sys.executable,str(here/'prepare_road_paint.py'),'--base',str(cleared),'--output',str(painted)],
        [args.node,str(here/'pack_tiles.mjs'),str(painted)],
        [sys.executable,str(here/'verify_tiles.py'),str(painted)],
        # Reuses the validated ground, constructs complete shores on canonical
        # contours, then clips only water and bank meshes into transport tiles.
        [sys.executable,str(here/'prepare_waterfront.py'),'--base',str(painted),'--output',str(args.output),'--node',args.node],
    ]
    if args.reuse_landscape:commands[0] += ['--reuse',str(args.reuse_landscape)]
    if not 1<=args.start_stage<=len(commands):ap.error('--start-stage is outside the release stage range')
    for index,command in enumerate(commands,1):
        if index<args.start_stage:continue
        print('RELEASE STAGE',index,'/',len(commands),Path(command[1]).name,flush=True)
        subprocess.run(command,check=True)
        if Path(command[1]).name.startswith('prepare_') and '--output' in command:
            produced=Path(command[command.index('--output')+1])
            if produced!=args.output:archive_intermediate_glb(produced)
    print('Validated city release:',args.output.resolve())

if __name__=='__main__':main()
