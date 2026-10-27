"""Convert the actual 2GIS waffle SVG repeat into clipped yellow geometry."""
import math,json
from pathlib import Path
from collections import defaultdict
import numpy as np
from pyproj import CRS,Transformer
from shapely.geometry import Polygon
from shapely.ops import unary_union,triangulate,transform
from shapely.affinity import scale,translate
from svgpathtools import parse_path
import xml.etree.ElementTree as ET

def apply_waffle_pattern(scene):
    plan=scene['plan'];crs=CRS.from_proj4(plan['crs_proj'])
    to_ll=Transformer.from_crs(crs,'EPSG:4326',always_xy=True)
    to_msk=Transformer.from_crs('EPSG:4326',crs,always_xy=True)
    # Public renderer: tileSizeZpt=256, textureSize=51 CSS px, zoom fixed at 19.
    world_pixels=256*2**19
    def to_pixels(x,y,z=None):
        lon,lat=to_ll.transform(x,y);lon=np.asarray(lon);lat=np.asarray(lat)
        return (lon/360+.5)*world_pixels,(np.arcsinh(np.tan(np.radians(lat)))/(2*math.pi)+.5)*world_pixels
    def to_coordinates(x,y,z=None):
        x=np.asarray(x);y=np.asarray(y);lon=(x/world_pixels-.5)*360;lat=np.degrees(np.arctan(np.sinh((y/world_pixels-.5)*2*math.pi)))
        return to_msk.transform(lon,lat)
    root_dir=Path(plan['output']).parents[1]
    style=json.loads((root_dir/'source/map_style.json').read_text())['result']
    svg=root_dir/'source/cache'/('style_'+style['icons']['waffle']['url'])
    root=ET.parse(svg).getroot();box=[float(v) for v in root.attrib['viewBox'].split()];shapes=[]
    for node in root.iter():
        if not node.tag.endswith('path') or not node.get('d'):continue
        shape=None
        for path in parse_path(node.get('d')).continuous_subpaths():
            pts=[]
            for seg in path:
                count=1 if seg.__class__.__name__=='Line' else 12
                pts.extend((seg.point(i/count).real,seg.point(i/count).imag) for i in range(count))
            if len(pts)<3:continue
            poly=Polygon(pts).buffer(0);shape=poly if shape is None else shape.symmetric_difference(poly)
        if shape is not None:shapes.append(shape)
    pattern=scale(unary_union(shapes),xfact=51/box[2],yfact=51/box[3],origin=(0,0))
    count=0;area_before=0;area_after=0
    for mesh in scene['meshes']:
        if mesh['name'].split('__')[0]!='PolygonMarkings_waffle':continue
        groups=defaultdict(list);heights={}
        for face,tiers in zip(mesh['faces'],mesh['face_tiers']):
            key=tuple(tiers);coords=[mesh['vertices'][i] for i in face];poly=Polygon([v[:2] for v in coords])
            if poly.area<1e-8:continue
            groups[key].append(poly);heights[key]=sum(v[2] for v in coords)/len(coords)
        vs=[];fs=[];ts=[]
        for tiers,polys in groups.items():
            source=unary_union(polys).buffer(0);parts=list(source.geoms) if hasattr(source,'geoms') else [source]
            for source_part in parts:
                area_before+=source_part.area;px=transform(to_pixels,source_part);minx,miny,maxx,maxy=px.bounds;pieces=[]
                for ix in range(math.floor(minx/51),math.floor(maxx/51)+1):
                    for iy in range(math.floor(miny/51),math.floor(maxy/51)+1):
                        piece=px.intersection(translate(pattern,xoff=ix*51,yoff=iy*51))
                        if not piece.is_empty:pieces.append(piece)
                # The original style also has a one-pixel yellow outline.
                pieces.append(px.boundary.buffer(.5,join_style=2).intersection(px))
                painted=transform(to_coordinates,unary_union(pieces));area_after+=painted.area
                for t in triangulate(painted):
                    if not painted.covers(t):continue
                    xy=list(t.exterior.coords)[:3];start=len(vs);vs.extend([[x,y,heights[tiers]] for x,y in xy]);fs.append([start,start+1,start+2]);ts.append(list(tiers))
                count+=1
        mesh['vertices']=vs;mesh['faces']=fs;mesh['face_tiers']=ts
        mesh['material_color']=[.991102,.955974,.0865,1]
        mesh['pattern_source']='Original waffle.svg; 51 px repeat at map zoom 19; transparent holes represented by geometry gaps'
    return {'waffle_polygons':count,'footprint_area_m2':area_before,'yellow_paint_area_m2':area_after,'texture_size_px':51,'reference_zoom':19,'source_svg':str(svg),'symbol_rotation':'Positive counterclockwise source rotation; SVG Y inverted independently'}
