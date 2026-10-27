"""Build a validated metric region before cutting transport tiles."""
from pathlib import Path
import sys,json,time,argparse,pickle,hashlib,faulthandler,signal
import numpy as np
import shapely as sh
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import build as b
from source_config import load_plan
from region import source_tiles
from region_checkpoint import save as save_checkpoint,restore as restore_checkpoint
from geometry_pickle import dump as dump_geometry,restore_source_precision

parser=argparse.ArgumentParser()
parser.add_argument('--size',type=int,default=500)
parser.add_argument('--output',type=Path)
parser.add_argument('--source',type=Path)
parser.add_argument('--markings',type=Path)
parser.add_argument('--bounds',type=float,nargs=4)
parser.add_argument('--checkpoint',type=Path,help='Optional local checkpoint for diagnosis; contains derived source geometry')
parser.add_argument('--source-checkpoint',type=Path,help='Reuse only a provenance-matched source decode from this build')
parser.add_argument('--surface-checkpoint',type=Path,help='Save fitted road geometry before structural and land overlays')
parser.add_argument('--resume-surfaces',type=Path,help='Resume this task’s own surface checkpoint after a structural rule repair')
parser.add_argument('--resume-stage',type=Path,help='Resume completed surfaces or paint from this same source capture')
args=parser.parse_args()
# The 1 km region remains inside the retained Blender marking extraction.
# These are experiment extents, not coordinate exceptions in geometry rules.
b.B=args.bounds or ([1875.,7820.,2375.,8320.] if args.size==500 else [2125-args.size/2,8000-args.size/2,2125+args.size/2,8000+args.size/2])
if args.source:b.SOURCE=args.source.resolve()
if args.markings:b.DIAG=args.markings.resolve()
if args.source:
    source_plan=load_plan(b.SOURCE)
    if not args.bounds and 'origin_msk' in source_plan:b.B=source_plan['extent_msk_east_north']
    if 'origin_msk' in source_plan:b.ORIGIN=np.asarray(source_plan['origin_msk'],dtype=float)
if args.size<=0:parser.error('--size must be positive')
# Fail before decoding hundreds of source tiles if the large-region solver is
# unavailable. Small fixtures use the same height model's dense path.
knots=np.ceil((np.asarray(b.B)[2:]-np.asarray(b.B)[:2])/b.RoadHeightModel.knot_spacing).astype(int)+4
if np.prod(knots)>=4096:
    try:
        from scipy.sparse.linalg import spsolve
    except ImportError as error:
        raise RuntimeError('Large-region height fitting needs scipy; install prototype/tiling/requirements-region.txt') from error
b.EXTENT=sh.box(*b.B)
b.TILE_KEYS=source_tiles(b.SOURCE,b.B)
b.DATA=args.output or b.WEB/'tiles/assets/canonical'
b.DATA.mkdir(parents=True,exist_ok=True)
start=time.time()
faulthandler.register(signal.SIGUSR1,all_threads=True)
stage=None
if args.resume_stage:
    saved=restore_checkpoint(b,args.resume_stage);stage=saved['stage']
    if stage not in ('surfaces','paint'):raise ValueError('Unknown checkpoint stage')
    if b.SOURCE!=args.source.resolve() or b.DIAG!=args.markings.resolve():raise ValueError('Checkpoint belongs to another source')
    if args.output:b.DATA=args.output
    opening,roads=saved['opening'],saved['roads']
    model=json.loads((b.DIAG/'corrected/manifest.json').read_text())
elif args.resume_surfaces:
    opening,roads,candidates=restore_checkpoint(b,args.resume_surfaces)
    if args.source and b.SOURCE!=args.source.resolve():raise ValueError('Checkpoint belongs to another source snapshot')
    if args.markings and b.DIAG!=args.markings.resolve():raise ValueError('Checkpoint belongs to another marking extraction')
    if args.bounds and b.B!=args.bounds:raise ValueError('Checkpoint belongs to another region')
    if args.output:b.DATA=args.output
    model=json.loads((b.DIAG/'corrected/manifest.json').read_text())
    opening,roads=b.complete_surfaces(opening,roads,candidates)
else:
    signature=hashlib.sha256(json.dumps(dict(bounds=b.B,source=str(b.SOURCE),tiles=b.TILE_KEYS),sort_keys=True).encode())
    for path in [Path(b.__file__),Path(b.__file__).with_name('source_objects.py'),Path(b.__file__).with_name('semantics.py'),b.SOURCE/'source/style_flat.json',b.DIAG/'corrected/manifest.json']:
        signature.update(path.read_bytes())
    receipt=b.SOURCE/'sources.json'
    if receipt.exists():signature.update(receipt.read_bytes())
    signature=signature.hexdigest();cached=None
    if args.source_checkpoint and args.source_checkpoint.exists():
        with args.source_checkpoint.open('rb') as f:cached=pickle.load(f)
    if cached and cached[0]==signature:
        _,state,candidates,model=cached
        if state.get('_sourcePrecisionVersion')!=1:
            restore_source_precision(state,candidates,b.GRID)
            temporary=args.source_checkpoint.with_suffix('.pkl.tmp')
            with temporary.open('wb') as f:dump_geometry((signature,state,candidates,model),f)
            temporary.replace(args.source_checkpoint)
            print('RESTORED SOURCE PRECISION MODEL',b.GRID,flush=True)
        for key,value in state.items():
            if not key.startswith('_'):setattr(b,key,value)
        print('REUSED VERIFIED SOURCE DECODE',flush=True)
    else:
        candidates,model=b.source_data();b.dem,b.demtree=b.make_dem()
        if args.source_checkpoint:
            state={key:getattr(b,key) for key in ['records','source_style','source_owners','dem','demtree','dem_report']}
            state['_sourcePrecisionVersion']=1
            temporary=args.source_checkpoint.with_suffix('.pkl.tmp')
            with temporary.open('wb') as f:dump_geometry((signature,state,candidates,model),f)
            temporary.replace(args.source_checkpoint)
    source_audit=b.audit_semantics(b.records)
    if not source_audit['passed']:
        (b.DATA/'source-semantics-validation.json').write_text(json.dumps(source_audit,ensure_ascii=False,indent=2))
        raise ValueError('Unsupported physical surface classes; resolve source semantics before fitting the region')
    print('REGION SOURCE',len(b.records),'DEM',len(b.dem),flush=True)
    if args.surface_checkpoint:
        b.surface_checkpoint_hook=lambda *inputs:save_checkpoint(b,args.surface_checkpoint,inputs)
    opening,roads=b.build_surfaces(candidates)
print('REGION SURFACES',len(b.surfaces),flush=True)
if stage=='paint':
    paint_checks,total,bound=saved['paint']
else:
    if args.checkpoint and stage!='surfaces':
        save_checkpoint(b,args.checkpoint.with_suffix('.surfaces.pkl'),dict(stage='surfaces',opening=opening,roads=roads))
    paint_checks,total,bound=b.legacy_and_paint(model)
print('REGION PAINT',bound,'/',total,flush=True)
if args.checkpoint and stage!='paint':
    save_checkpoint(b,args.checkpoint.with_suffix('.paint.pkl'),dict(stage='paint',opening=opening,roads=roads,paint=(paint_checks,total,bound)))
wall_count=b.walls(opening,roads)
print('REGION WALLS',wall_count,flush=True)
if args.checkpoint:
    save_checkpoint(b,args.checkpoint,(opening,roads,paint_checks,total,bound))
from finish_region import finish
finish(b,opening,roads,paint_checks,total,bound,start,fresh_source=bool(args.source))
