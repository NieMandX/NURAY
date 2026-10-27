"""Plan a fresh metric square around a centre observed in the public map."""
import argparse,json,math
from datetime import datetime,timezone
from pathlib import Path
from urllib.parse import urlparse,parse_qs
from pyproj import Transformer
from shapely.geometry import Polygon,box
from shapely.ops import unary_union

def plan_region(output,inventory,lon,lat,size=10000,halo=500,name='Санкт-Петербург'):
    proj=f'+proj=tmerc +lat_0={lat} +lon_0={lon} +k=1 +x_0=0 +y_0=0 +datum=WGS84 +units=m +no_defs'
    forward=Transformer.from_crs('EPSG:4326',proj,always_xy=True)
    inverse=Transformer.from_crs(proj,'EPSG:4326',always_xy=True)
    bounds=[-size/2,-size/2,size/2,size/2];r=size/2+halo;capture=[-r,-r,r,r];z=15
    samples=[]
    for i in range(101):
        v=-r+2*r*i/100
        for x,y in ((v,-r),(v,r),(-r,v),(r,v)):
            a,b=inverse.transform(x,y);samples.append(((a/360+.5)*2**z,(.5+math.asinh(math.tan(math.radians(b)))/(2*math.pi))*2**z))
    tiles=[];polys=[]
    for x in range(math.floor(min(p[0] for p in samples))-1,math.floor(max(p[0] for p in samples))+2):
        for y in range(math.floor(min(p[1] for p in samples))-1,math.floor(max(p[1] for p in samples))+2):
            corners=[]
            for dx,dy in ((0,0),(1,0),(1,1),(0,1)):
                a=((x+dx)/2**z-.5)*360;b=math.degrees(math.atan(math.sinh(((y+dy)/2**z-.5)*2*math.pi)))
                corners.append(forward.transform(a,b))
            p=Polygon(corners)
            if p.intersects(box(*capture)):tiles.append([x,y,z,17]);polys.append(p)
    assert box(*capture).difference(unary_union(polys)).area<.001
    observed=json.loads(inventory.read_text());resources={}
    for a in observed['assets']:
        u=a['url']
        if '/rarity-3d.' in u:resources['rarity-3d.js']=u
        if '/map3d.' in u:resources['map3d.js']=u
        if 'styles.api.2gis.com/styles/' in u:resources['map_style.json']=u
    assert len(resources)==3
    key=parse_qs(urlparse(resources['map_style.json']).query)['key'][0]
    plan=dict(name=name,size_m=size,center_msk_east_north=[0,0],center_wgs84=[lon,lat],extent_msk_east_north=bounds,
        acquisition_bounds_msk=capture,context_halo_m=halo,crs_proj=proj,crs_name='Local WGS84 transverse Mercator centred on selected point; not an official city surveying grid',
        vertical_reference='2GIS relative map ground, NOT surveyed absolute elevations',origin_msk=[0,0,0],transport_tile_size_m=250,
        output_subdir=f'area_{size}',tiles=tiles,publicSiteKey=key,source_policy='Fresh network acquisition from current public browser resources; no previous geometry fallback.',
        selected_view_url=observed['pageUrl'],created_at=datetime.now(timezone.utc).isoformat())
    output.mkdir(parents=True,exist_ok=False);(output/'browser').mkdir()
    (output/'plan.json').write_text(json.dumps(plan,ensure_ascii=False,indent=2))
    (output/'browser/observed-resources.json').write_text(json.dumps(dict(pageUrl=observed['pageUrl'],resources=resources,observedAt=plan['created_at']),indent=2))
    print(json.dumps(dict(centre=[lon,lat],bounds=bounds,capture=capture,sourceTiles=len(tiles),transportTiles=(size//250)**2)))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('output',type=Path);p.add_argument('inventory',type=Path);p.add_argument('--lon',type=float,required=True);p.add_argument('--lat',type=float,required=True);p.add_argument('--size',type=int,default=10000)
    a=p.parse_args();plan_region(a.output,a.inventory,a.lon,a.lat,a.size)
