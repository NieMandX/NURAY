import bpy,sys,json,runpy
from pathlib import Path
WORK=Path('/Users/niemandx/Documents/ChatGPT/IDEAS/moscow-fidelity')
sys.path[:0]=[str(WORK/'scripts'),'/private/tmp/nuray-fidelity-deps311']
import shapely
from repair_blender import resolve_background,restore_open_descents
masks={p.stem:shapely.from_wkb(p.read_bytes()) for p in (WORK/'output/source-masks').glob('*.wkb')}
path=Path(bpy.data.filepath);report_path=path.with_suffix('.report.json')
report=json.loads(report_path.read_text())
assert not report.get('coarse_terrain_hidden'),'Already finalized'
resolve_background(masks,report)
restore_open_descents(masks,report)
report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2))
bpy.ops.wm.save_as_mainfile(filepath=str(path),compress=True)
print('BACKGROUND FINALIZED',flush=True)
sys.argv=['blender','--','--extent','5000','--output',str(WORK/'web-preview/assets/moscow-city-5km-v2'),'--require-fidelity']
runpy.run_path('/Users/niemandx/Documents/ChatGPT/IDEAS/light-study/scripts/export-moscow.py',run_name='__main__')
sys.argv=['blender','--','--view','park','--output',str(WORK/'output/park-after.png')]
runpy.run_path(str(WORK/'scripts/render_review.py'),run_name='__main__')
print('FINAL GROUND COMPLETE',flush=True)
