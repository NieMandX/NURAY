"""Retained 2GIS semantics over authoritative Yandex footprints.

The geometry of a source polygon is a triangle strip, not a GeoJSON boundary.
Only explicit material classes may change an appearance. Unknowns stay unknown.
"""
import collections, hashlib, json, pickle
from pathlib import Path
import numpy as np
import shapely as sh
from pyproj import Transformer
from landscape import GREEN_VARIANTS
from pedestrian_materials import RULES

def load(root, crs, cache):
    paths=sorted(p for p in (root/'source/cache').glob('*.json') if not p.name.startswith('dem'))
    digest=hashlib.sha256(''.join(hashlib.sha256(p.read_bytes()).hexdigest() for p in paths).encode()).hexdigest()
    signature=(2,digest,crs)
    if cache.exists():
        with cache.open('rb') as f:data=pickle.load(f)
        if data['signature']==signature:return data
    project=Transformer.from_crs('EPSG:4326',crs,always_xy=True)
    pieces=collections.defaultdict(list);fences=[];counts=collections.Counter();seen=set()
    allowed=set(GREEN_VARIANTS)|set(RULES)|{'Suburban_forest_quarter'}
    for path in paths:
        for feature in json.loads(path.read_text()).get('features',[]):
            p=feature['properties'];layer=p.get('db_sublayer');g=feature['geometry']
            if layer not in allowed and layer!='Fence':continue
            if layer=='Fence':
                if g['type']!='LineString' or any(p.get(k,0) for k in ('db_segment_level','db_segment_begin_level','db_segment_end_level')):continue
                a=np.asarray(g['coordinates']);xy=np.column_stack(project.transform(a[:,0],a[:,1]));line=sh.LineString(xy)
                key=(p.get('db_fence_type'),sh.normalize(line).wkb)
                if key in seen:continue
                seen.add(key);fences.append(dict(line=line,properties=p,sourceTile=path.stem));counts['Fence:'+str(p.get('db_fence_type'))]+=1
                continue
            if g['type']!='Polygon':continue
            counts[layer]+=1
            for strip in g['coordinates']:
                a=np.asarray(strip)
                if len(a)<3:continue
                xy=np.column_stack(project.transform(a[:,0],a[:,1]))
                tris=sh.polygons(np.stack([xy[:-2],xy[1:-1],xy[2:]],axis=1))
                pieces[layer].extend(tris[sh.area(tris)>1e-8])
    areas={}
    for layer,ps in pieces.items():
        batches=[sh.union_all(sh.set_precision(ps[i:i+10000],1e-5),grid_size=1e-5) for i in range(0,len(ps),10000)]
        areas[layer]=sh.union_all(batches,grid_size=1e-5)
    rules=[r for r in json.loads((root/'source/style_flat.json').read_text()) if r.get('type')=='model' and 'fence' in str(r.get('style',{}).get('modelSrc','')).lower()]
    data=dict(signature=signature,areas=areas,fences=fences,fenceRules=rules,counts=dict(counts),sourceRoot=str(root))
    with cache.open('wb') as f:pickle.dump(data,f,protocol=5)
    print('STYLE EVIDENCE',dict(counts),flush=True)
    return data
