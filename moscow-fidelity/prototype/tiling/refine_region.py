"""Upgrade this task's own checkpoint with the current general seam rule."""
import sys,pickle,time,argparse,hashlib,signal,faulthandler,gc
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import build as b
from region_checkpoint import restore,save
from partition_refinement import refine
from finish_region import finish

p=argparse.ArgumentParser();p.add_argument('--checkpoint',type=Path,required=True);p.add_argument('--source-decode',type=Path,required=True);p.add_argument('--output-checkpoint',type=Path,required=True);p.add_argument('--rebuild-walls',action='store_true');a=p.parse_args()
faulthandler.register(signal.SIGUSR1,all_threads=True)
inputs=restore(b,a.checkpoint);opening,road,checks,total,bound=inputs
print('RESTORED CANONICAL',len(b.surfaces),flush=True)
with a.source_decode.open('rb') as f:_,state,candidates,_=pickle.load(f)
receipts={r['source']['tile']:r['source']['fileSha256'] for r in state['records']}
for tile,digest in receipts.items():
    if hashlib.sha256((b.SOURCE/'source/cache'/f'{tile}.json').read_bytes()).hexdigest()!=digest:
        raise ValueError('Source decode differs from this live capture')
del state;gc.collect()
road=refine(b,opening,road,candidates)
del candidates;gc.collect()
if a.rebuild_walls:
    names={'tunnel_wall_top','tunnel_wall_bottom','tunnel_wall_side','inferred-walls',
           'portal_guard_top','portal_guard_bottom','portal_guard_side'}
    for key in list(b.groups):
        if key[0] in names:
            b.groups[key]=[];b.shading_flags.pop(key,None)
    print('REBUILDING RETAINING WALLS',flush=True)
    print('REBUILT WALL SEGMENTS',b.walls(opening,road),flush=True)
save(b,a.output_checkpoint,(opening,road,checks,total,bound))
finish(b,opening,road,checks,total,bound,time.time(),fresh_source=True)
