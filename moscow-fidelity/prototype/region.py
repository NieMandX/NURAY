"""Metric region configuration, independent of source/transport tile grids."""
import json
import numpy as np
import shapely as sh
from pyproj import CRS,Transformer
from source_config import load_plan

def source_tiles(source,bounds):
    plan=load_plan(source)
    project=Transformer.from_crs('EPSG:4326',CRS.from_proj4(plan['crs_proj']),always_xy=True)
    extent=sh.box(*bounds);keys=[]
    for x,y,z,*_ in plan['tiles']:
        size=2**32/2**z;half=2**(z-1)
        wx=np.array([x-half,x+1-half,x+1-half,x-half])*size
        wy=np.array([y-half,y-half,y+1-half,y+1-half])*size
        px,py=project.transform(wx/2**32*360,np.degrees(np.arctan(np.sinh(wy/2**32*2*np.pi))))
        if sh.Polygon(np.column_stack([px,py])).intersects(extent):
            key=f'{x}_{y}_{z}'
            for prefix in ['', 'dem_']:
                if not (source/'source/cache'/f'{prefix}{key}.json').exists():raise FileNotFoundError(f'Missing source tile: {prefix}{key}')
            keys.append(key)
    if not keys:raise ValueError('Region has no source coverage')
    return keys
