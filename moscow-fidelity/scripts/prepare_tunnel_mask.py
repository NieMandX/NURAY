"""Extract only explicitly open descents, leaving covered tunnel footprints intact."""
import json,math,sys
from pathlib import Path
import numpy as np,shapely
from pyproj import CRS,Transformer
root=Path('/Users/niemandx/AI_Modeling/moscow_10x10');out=Path('/Users/niemandx/Documents/ChatGPT/IDEAS/moscow-fidelity/output/source-masks')
plan=json.loads((root/'output/area_10000/plan.json').read_text());project=Transformer.from_crs('EPSG:4326',CRS.from_proj4(plan['crs_proj']),always_xy=True)
bounds=shapely.box(*plan['extent_msk_east_north']);parts=[];records=[]
for tile in plan['tiles']:
    data=json.loads((root/'source/cache'/('_'.join(map(str,tile[:3]))+'.json')).read_text());info=data['tile_info']
    for f in data['features']:
        p=f['properties'];raw=f['_raw']
        if p.get('db_road_part')!='roadbed_tunnel_descent' or p['db_geometry_type']!='polygon':continue
        wx=info['offset'][0]+np.asarray(raw['x'])*info['size']/32768;wy=info['offset'][1]+np.asarray(raw['y'])*info['size']/32768
        lon=wx/2**32*360;lat=np.degrees(np.arctan(np.sinh(wy/2**32*2*math.pi)));xx,yy=project.transform(lon,lat);xy=np.column_stack((xx,yy))
        ids=np.arange(len(xy)-2)[:,None]+[0,1,2];tris=shapely.polygons(xy[ids]);tris=tris[shapely.area(tris)>1e-8]
        if not len(tris):continue
        poly=shapely.union_all(tris).intersection(bounds)
        if poly.is_empty:continue
        parts.append(poly);records.append({'layer':p['db_sublayer'],'center':list(poly.centroid.coords)[0],'signed_z':list(set(raw.get('signed_z',[])))})
mask=shapely.union_all(parts);(out/'tunnel_descent.wkb').write_bytes(shapely.to_wkb(mask))
(out/'tunnel-descents.json').write_text(json.dumps({'area_m2':mask.area,'source_fragments':len(records),'records':records},indent=2))
print('OPEN DESCENTS',len(records),mask.area,flush=True)
