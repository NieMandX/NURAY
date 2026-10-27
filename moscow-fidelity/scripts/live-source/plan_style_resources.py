"""Retain assets of physical style candidates occurring in the fresh capture."""
import json
import sys
from pathlib import Path
from collections import Counter
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from audit_source_catalog import layer_selectors, strings
from source_objects import exterior_record, INFORMATION_LAYERS, EXCLUDED_SOURCE_LAYERS
from semantics import classify

root=Path(sys.argv[1]).resolve()
plan=json.loads((root/'plan.json').read_text())
style=json.loads((root/'source/map_style.json').read_text())['result']
flat=json.loads((root/'source/style_flat.json').read_text())
layers=Counter();geometry={}
for x,y,z,*_ in plan['tiles']:
    data=json.loads((root/f'source/cache/{x}_{y}_{z}.json').read_text())
    for f in data['features']:
        p=f['properties'];layer=p['db_sublayer']
        if exterior_record(p) and layer not in INFORMATION_LAYERS|EXCLUDED_SOURCE_LAYERS:
            layers[layer]+=1;geometry.setdefault(layer,p)
physical=set()
for layer,p in geometry.items():
    s=classify(layer,p,p.get('db_geometry_type'))
    if s['status'] in ('built','legacy-marking','source-modifier','source-boundary') or s['purpose']=='building':physical.add(layer)
for r in flat:
    if r.get('type')=='model':physical.update(layer_selectors(r.get('filter')) & layers.keys())
selected=[];assets={}
for r in flat:
    selectors=layer_selectors(r.get('filter'))
    if not selectors.intersection(physical):continue
    selected.append(str(r['id']))
    values=set(strings(r.get('style',{})))
    for kind in ('models','icons'):
        for name in values.intersection(style.get(kind,{})):
            rel=style[kind][name].get('url')
            if not rel:continue
            url=rel if rel.startswith('https://') else f'https://disk.2gis.com/styles/assets/{kind}/{rel}'
            file=root/'source/cache'/('style_'+Path(rel).name)
            assets[url]=dict(url=url,file=str(file),kind=kind,name=name)
output=root/'output'/plan.get('output_subdir','area_5000');output.mkdir(parents=True,exist_ok=True)
(output/'resources.json').write_text(json.dumps(list(assets.values()),indent=2))
(root/'style-selection.json').write_text(json.dumps(dict(layers=dict(layers),physicalLayers=sorted(physical),candidateStyleIds=selected,resourceCount=len(assets),policy='All declared assets for matching physical layer candidates; candidates are not a placement approval.'),indent=2))
print('Physical source style assets',len(assets),'candidate layers',len(physical),flush=True)
