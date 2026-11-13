"""Specific physical cover wins over a broad square envelope, never a path."""
import shapely as sh
from build_scene import union,WIDTHS

def specific_square_surfaces(rows):
    broad=[];paths=[];green=[];parking=[]
    for f,g,l in rows:
        a=f['attributes'];layer=f['layer'];ft=a.get('ft_type_name','')
        if int(a.get('z_level',0)) or a.get('struct','none') not in ('none',''):continue
        if layer=='roadnet_a' and 'square' in ft:broad.append(g)
        elif layer in ('vegetation','hd_road_vegetation'):green.append(g)
        elif layer=='landuse_a' and 'parking' in ft:parking.append(g)
        elif layer=='hd_road_surface' and a.get('type') in ('pedestrian','stairs'):paths.append(g)
        elif layer=='road' and (a.get('class','').startswith('10') or a.get('class') in ('crosswalk','stairs')):
            if not l.is_empty:paths.append(l.buffer(WIDTHS.get(a['class'],1.6)/2,quad_segs=3,join_style='bevel'))
    square=union(broad);explicit=union(paths)
    grass=union(green).intersection(square).difference(explicit)
    carpark=union(parking).intersection(square).difference(explicit).difference(grass)
    return grass,carpark
