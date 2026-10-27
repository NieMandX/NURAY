"""Plan a fresh, overlapping acquisition on the existing metric coordinate grid."""
import argparse
import json
import math
from pathlib import Path
from pyproj import Transformer
from shapely.geometry import Polygon, box
from shapely.ops import unary_union


def plan_expansion(base, output, inventory, expansion=2000, halo=500):
    old = json.loads((base / 'plan.json').read_text())
    b = old['extent_msk_east_north']
    target = [b[0]-expansion, b[1]-expansion, b[2]+expansion, b[3]+expansion]
    capture = [target[0]-halo, target[1]-halo, target[2]+halo, target[3]+halo]
    forward = Transformer.from_crs('EPSG:4326', old['crs_proj'], always_xy=True)
    inverse = Transformer.from_crs(old['crs_proj'], 'EPSG:4326', always_xy=True)
    z = 15
    def tilexy(x, y):
        lon, lat = inverse.transform(x, y)
        return ((lon/360+.5)*2**z, (.5+math.asinh(math.tan(math.radians(lat)))/(2*math.pi))*2**z)
    edge = []
    for i in range(101):
        t=i/100
        edge += [(capture[0]+t*(capture[2]-capture[0]),capture[j]) for j in (1,3)]
        edge += [(capture[j],capture[1]+t*(capture[3]-capture[1])) for j in (0,2)]
    xy = [tilexy(*p) for p in edge]
    tiles=[]; polygons=[]
    for x in range(math.floor(min(p[0] for p in xy))-1, math.floor(max(p[0] for p in xy))+2):
        for y in range(math.floor(min(p[1] for p in xy))-1, math.floor(max(p[1] for p in xy))+2):
            corners=[]
            for dx,dy in [(0,0),(1,0),(1,1),(0,1)]:
                lon=((x+dx)/2**z-.5)*360
                lat=math.degrees(math.atan(math.sinh(((y+dy)/2**z-.5)*2*math.pi)))
                corners.append(forward.transform(lon,lat))
            poly=Polygon(corners)
            if poly.intersects(box(*capture)):
                tiles.append([x,y,z,17]);polygons.append(poly)
    assert box(*capture).difference(unary_union(polygons)).area < 0.001
    assert set(tuple(t[:3]) for t in old['tiles']).issubset(set(tuple(t[:3]) for t in tiles))
    assets=json.loads(inventory.read_text())
    selected={}
    for a in assets['assets']:
        url=a['url']
        if '/rarity-3d.' in url:selected['rarity-3d.js']=url
        if '/map3d.' in url:selected['map3d.js']=url
        if '/styles/' in url and 'styles.api.2gis.com' in url:selected['map_style.json']=url
    assert set(selected)=={'rarity-3d.js','map3d.js','map_style.json'}
    from urllib.parse import urlparse,parse_qs
    public_key=parse_qs(urlparse(selected['map_style.json']).query)['key'][0]
    result={**old,'size_m':target[2]-target[0],'extent_msk_east_north':target,
        'acquisition_bounds_msk':capture,'context_halo_m':halo,'base_bounds_msk':b,
        'base_snapshot':str(base.resolve()),'tiles':tiles,'publicSiteKey':public_key,
        'output_subdir':'area_9000','transport_tile_size_m':250,'origin_msk':[2125,8070,145],
        'source_policy':'Fresh network acquisition, including the complete old region; never copy old source bytes.'}
    output.mkdir(parents=True,exist_ok=False)
    (output/'plan.json').write_text(json.dumps(result,indent=2,ensure_ascii=False))
    (output/'browser').mkdir()
    evidence={'pageUrl':assets['pageUrl'],'resources':selected,'observedAt':__import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat()}
    (output/'browser/observed-resources.json').write_text(json.dumps(evidence,indent=2))
    print(json.dumps({'target':target,'capture':capture,'sourceTiles':len(tiles),'oldSourceTiles':len(old['tiles']),'transportTiles':1296,'newTransportTiles':896}))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('base',type=Path);p.add_argument('output',type=Path);p.add_argument('inventory',type=Path)
    a=p.parse_args();plan_expansion(a.base,a.output,a.inventory)
