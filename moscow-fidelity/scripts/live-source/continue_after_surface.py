"""Continue this local build only after the owned surface process succeeds."""
import argparse,json,os,subprocess,sys,time
from pathlib import Path

p=argparse.ArgumentParser()
p.add_argument('--pid',type=int,help='Optional owned process to detect premature exit; a fresh per-run log is required')
p.add_argument('--log',required=True,type=Path)
p.add_argument('--snapshot',required=True,type=Path)
p.add_argument('--surface',required=True,type=Path)
p.add_argument('--output',required=True,type=Path)
p.add_argument('--node',required=True)
p.add_argument('--inventory',required=True,type=Path)
a=p.parse_args()
while True:
    tail=''
    if a.log.exists():
        with a.log.open('rb') as f:
            f.seek(max(0,a.log.stat().st_size-65536));tail=f.read().decode('utf-8',errors='replace')
    if 'Traceback (most recent call last)' in tail:
        raise RuntimeError('Surface build failed; assembly was not started')
    if 'REGION VERIFIED ' in tail:break
    if a.pid is not None:
        try:os.kill(a.pid,0)
        except ProcessLookupError:
            raise RuntimeError('Surface process stopped before verified export; assembly was not started')
    time.sleep(15)
with (a.surface/'canonical/validation.json').open() as f:report=json.load(f)
if not report['passed'] or 'export' not in report:
    raise RuntimeError('Surface report is incomplete; assembly was not started')
print('Verified surface completed; starting fresh city assembly',flush=True)
subprocess.run([sys.executable,str(Path(__file__).with_name('build_assets.py')),
    '--snapshot',str(a.snapshot),'--surface',str(a.surface),'--output',str(a.output),
    '--node',a.node,'--inventory',str(a.inventory)],check=True)
