"""Finish legacy batch filtering and validate the saved, complete scene before export."""
import bpy,sys,json,runpy
from pathlib import Path
import numpy as np
WORK=Path('/Users/niemandx/Documents/ChatGPT/IDEAS/moscow-fidelity')
sys.path[:0]=[str(WORK/'scripts'),'/private/tmp/nuray-fidelity-deps311']
import shapely
from repair_blender import remove_legacy_entrances,separate_detailed_greens,sample_heights,array
path=Path(bpy.data.filepath);report_path=path.with_suffix('.report.json');report=json.loads(report_path.read_text())
assert bpy.context.scene.get('fidelity_repair_version')==1
assert bpy.context.scene.get('fidelity_open_descents')
assert bpy.data.objects['Terrain_2GIS_TIN'].hide_render
assert bpy.data.objects['Shore'].hide_render
remove_legacy_entrances(report)
masks={p.stem:shapely.from_wkb(p.read_bytes()) for p in (WORK/'output/source-masks').glob('*.wkb')}
separate_detailed_greens(masks,report)
index=json.loads(bpy.data.texts['building_source_index.json'].as_string())
legacy=[int(k) for k,v in index.items() if v['source_layer'].startswith('Underpass_entrance_')]
for o in bpy.data.collections['Buildings'].objects:
    if o.type=='MESH':assert not np.isin(array(o.data.attributes['source_object_index'].data,'value',1,np.int32),legacy).any(),o.name
grass_points=[(880,7910),(910,7070),(940,6980),(1120,7430),(250,7790)]
rows=sample_heights(['Administrative_quarter','Dwelling_quarter','Forest_quarter','Internal_forest_quarter','Internal_lawn'],grass_points)
for r in rows:
    assert any(k in r['hits'] for k in ['Forest_quarter','Internal_forest_quarter','Internal_lawn']),r
    assert 'Administrative_quarter' not in r['hits'],r
    assert 'Dwelling_quarter' not in r['hits'],r
report['background_validation']=rows
points=[(473.597189,7455.452357),(475.23203,7459.01459),(468.69571,7462.95584),(2253.50538,8563.33647),(2204.20238,8538.11055),(2273.99935,8533.50767)]
assert all(masks['tunnel_descent'].covers(shapely.Point(p)) for p in points),'Samples must lie inside actual open descents'
names=[o.name for cat in ['Land_cover','Green_areas'] for o in bpy.data.collections[cat].objects if o.type=='MESH' and not o.hide_render and o.name not in ['Pier_quarter','Bridge_area']]
rows=sample_heights(names+['Roadbed_underpasses','Main_Roadbed'],points)
for r in rows:
    assert not any(k in r['hits'] for k in names),r
    assert any(k in r['hits'] for k in ['Roadbed_underpasses','Main_Roadbed']),r
report['open_descent_validation']=rows
report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2))
bpy.ops.wm.save_as_mainfile(filepath=str(path),compress=True)
print('FINAL MODEL VALIDATED',json.dumps({'background_samples':len(grass_points),'descent_samples':len(points),'legacy_triangles_removed':report['legacy_entrance_triangles_removed']}),flush=True)
sys.argv=['blender','--','--extent','5000','--output',str(WORK/'web-preview/assets/moscow-city-5km-v2'),'--require-fidelity']
runpy.run_path('/Users/niemandx/Documents/ChatGPT/IDEAS/light-study/scripts/export-moscow.py',run_name='__main__')
print('FINAL EXPORT READY',flush=True)
