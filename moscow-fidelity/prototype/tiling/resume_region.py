"""Resume validation/export from this task's own derived geometry checkpoint."""
import argparse,sys,time,faulthandler,signal
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import build as b
from finish_region import finish
from region_checkpoint import restore
p=argparse.ArgumentParser();p.add_argument('checkpoint',type=Path);p.add_argument('--source',type=Path,required=True);a=p.parse_args()
faulthandler.register(signal.SIGUSR1,all_threads=True)
# Only locally generated trusted checkpoints are accepted by this CLI.
inputs=restore(b,a.checkpoint)
if b.SOURCE.resolve()!=a.source.resolve():raise ValueError('Checkpoint belongs to another source capture')
finish(b,*inputs,time.time(),fresh_source=True)
