"""Build repair masks from retained 2GIS features, not from screenshot guesses."""
import argparse, json, math
from collections import Counter, defaultdict
from pathlib import Path
import numpy as np
import shapely
from shapely.geometry import Polygon, LineString, box
from pyproj import CRS, Transformer

def evaluate(x, p, ppm):
    if not isinstance(x, list): return x
    if not x: return x
    op=x[0]
    if op=='get': return p.get(x[1], p.get('db_'+x[1]))
    if op=='global': return {'graphicsPreset':'immersive','immersiveRoadsOn':True,'_activeFloorIsMetro':False}.get(x[1],False)
    if op=='zoom': return 19
    if op=='literal': return x[1]
    if op=='meters-to-pixels': return evaluate(x[1],p,ppm)*ppm
    if op=='match':
        value=evaluate(x[1],p,ppm)
        for i in range(2,len(x)-1,2):
            if value in (x[i] if isinstance(x[i],list) else [x[i]]): return evaluate(x[i+1],p,ppm)
        return evaluate(x[-1],p,ppm)
    if op=='case':
        for i in range(1,len(x)-1,2):
            if evaluate(x[i],p,ppm): return evaluate(x[i+1],p,ppm)
        return evaluate(x[-1],p,ppm)
    if op=='interpolate':
        value=evaluate(x[2],p,ppm); stops=x[3:]
        if value<=stops[0]: return evaluate(stops[1],p,ppm)
        for i in range(2,len(stops),2):
            if value<stops[i]:
                a,b=evaluate(stops[i-1],p,ppm),evaluate(stops[i+1],p,ppm)
                return a+(b-a)*(value-stops[i-2])/(stops[i]-stops[i-2]) if isinstance(a,(int,float)) and isinstance(b,(int,float)) else a
        return evaluate(stops[-1],p,ppm)
    if op=='step':
        value=evaluate(x[1],p,ppm); out=x[2]
        for i in range(3,len(x),2):
            if value>=x[i]:out=x[i+1]
        return evaluate(out,p,ppm)
    args=[evaluate(v,p,ppm) for v in x[1:]]
    if op=='all':return all(args)
    if op=='any':return any(args)
    if op=='!':return not args[0]
    if op=='==':return args[0]==args[1]
    if op=='!=':return args[0]!=args[1]
    if op=='*':return math.prod(args)
    if op=='+':return sum(args)
    if op=='coalesce':return next((a for a in args if a is not None),None)
    return None

def main(root,out):
    out.mkdir(parents=True,exist_ok=True)
    plan=json.loads((root/'output/area_10000/plan.json').read_text())
    styles=json.loads((root/'source/style_flat.json').read_text())
    project=Transformer.from_crs('EPSG:4326',CRS.from_proj4(plan['crs_proj']),always_xy=True)
    bounds=box(*plan['extent_msk_east_north'])
    masks=defaultdict(list); counts=Counter(); paths=[]
    path_layers={'Pedestrian_road','Pedestrian_road_park_path','Pedestrian_road_park_footpath'}
    for number,tile in enumerate(plan['tiles']):
        data=json.loads((root/'source/cache'/('_'.join(map(str,tile[:3]))+'.json')).read_text())
        info=data['tile_info']; groups=defaultdict(list)
        for feature in data['features']:
            p=feature['properties']; layer=p['db_sublayer']; raw=feature['_raw']; typ=p['db_geometry_type']
            is_descent=p.get('db_road_part')=='roadbed_tunnel_descent'
            selected=is_descent or layer in {'Water_area','Pedestrian_quarter','PolygonMarkings_pedestrian_crossing','Administrative_quarter','Forest_quarter','Internal_forest_quarter','Internal_lawn','Flowerbed_quarter'} or layer.startswith('Immersive_park_polygon_') or layer in path_layers
            if not selected or not raw.get('x'):continue
            wx=info['offset'][0]+np.asarray(raw['x'])*info['size']/32768
            wy=info['offset'][1]+np.asarray(raw['y'])*info['size']/32768
            lon=wx/2**32*360; lat=np.degrees(np.arctan(np.sinh(wy/2**32*2*math.pi)))
            xx,yy=project.transform(lon,lat); xy=np.column_stack((xx,yy))
            if max(xx)<bounds.bounds[0] or min(xx)>bounds.bounds[2] or max(yy)<bounds.bounds[1] or min(yy)>bounds.bounds[3]:continue
            if typ=='polygon':
                key='tunnel_descent' if is_descent else layer
                if layer=='PolygonMarkings_pedestrian_crossing':
                    if p.get('db_road_marking_color_type') not in (2,'yellow'):continue
                    key='yellow_crossing_tier_'+str(max(p.get('db_tiers') or [0]))
                ids=np.arange(len(xy)-2)[:,None]+np.array([0,1,2])
                tris=shapely.polygons(xy[ids]); tris=tris[shapely.area(tris)>1e-8]
                if len(tris):groups[key].append(shapely.union_all(tris).intersection(bounds));counts[key]+=1
            elif typ=='polyline' and layer in path_layers and (p.get('db_tiers') or [0])==[0]:
                ppm=256*2**19/(2*math.pi*6378137*math.cos(math.radians(float(np.mean(lat)))))
                matches=[s for s in styles if s['type']=='line' and layer in str(s.get('filter')) and s.get('style',{}).get('visibility')!='none' and evaluate(s.get('filter'),p,ppm)]
                # First matching line is the source's broad background, subsequent ones are strokes.
                if not matches:continue
                width=evaluate(matches[0]['style'].get('width'),p,ppm)
                if not isinstance(width,(int,float)) or width<=0:continue
                width=float(width)/ppm
                if len(xy)<2:continue
                poly=LineString(xy).buffer(width/2,cap_style='flat',join_style='mitre').intersection(bounds)
                if poly.is_empty:continue
                groups['pedestrian_lines'].append(poly)
                paths.append({'layer':layer,'width_m':width,'style_id':matches[0]['id']})
                counts[layer]+=1
        for key,polys in groups.items():masks[key].append(shapely.union_all(polys))
        if number%20==0:print('source tiles',number+1,'/',len(plan['tiles']),flush=True)
    result={}
    for key,parts in masks.items():
        shape=shapely.union_all(parts)
        (out/(key+'.wkb')).write_bytes(shapely.to_wkb(shape))
        result[key]={'area_m2':shape.area,'features':counts[key]}
    (out/'source-report.json').write_text(json.dumps({'masks':result,'path_features':dict(Counter(p['layer'] for p in paths)),'path_width_ranges':{k:[min(p['width_m'] for p in paths if p['layer']==k),max(p['width_m'] for p in paths if p['layer']==k)] for k in path_layers if any(p['layer']==k for p in paths)},'reference_zoom':19},indent=2))
    print(json.dumps(result),flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('root',type=Path);parser.add_argument('out',type=Path);args=parser.parse_args();main(args.root,args.out)
