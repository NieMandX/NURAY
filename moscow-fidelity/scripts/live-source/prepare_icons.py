import json,gzip,sys,math,xml.etree.ElementTree as ET
from pathlib import Path
from svgpathtools import parse_path
from shapely.geometry import Polygon
from shapely.ops import triangulate
out=Path(sys.argv[1]);scene=json.load(gzip.open(out/'scene.json.gz','rt'));cache={};meshes={}
for icon in scene['icons']:
    file=icon['file']
    if file not in cache:
        root=ET.parse(file).getroot();box=[float(x) for x in root.attrib['viewBox'].split()];polys=[]
        for node in root.iter():
            if not node.tag.endswith('path') or not node.get('d'):continue
            if node.get('fill')=='none':continue
            shape=None
            for path in parse_path(node.get('d')).continuous_subpaths():
                pts=[]
                for seg in path:
                    samples=1 if seg.__class__.__name__=='Line' else 12
                    pts.extend((seg.point(i/samples).real,seg.point(i/samples).imag) for i in range(samples))
                if len(pts)<3:continue
                p=Polygon(pts).buffer(0);shape=p if shape is None else shape.symmetric_difference(p)
            if shape is not None:
                polys.extend([list(t.exterior.coords)[:3] for t in triangulate(shape) if shape.covers(t)])
        cache[file]=(box,polys)
    box,polys=cache[file];m=meshes.setdefault(icon['layer'],{'name':icon['layer'],'category':'Road_marking_symbols','vertices':[],'faces':[],'face_tiers':[]})
    # The site's metricPoint generator uses positive counterclockwise rotation.
    # SVG's downward Y is inverted separately; negating rotation mirrors bearings.
    a=math.radians(icon['angle']);c,s=math.cos(a),math.sin(a)
    for tri in polys:
        start=len(m['vertices'])
        for x,y in tri:
            x=((x-box[0])/box[2]-.5)*icon['width'];y=(.5-(y-box[1])/box[3])*icon['height']
            dx,dy=c*x-s*y,s*x+c*y;grad=icon.get('surface_gradient',[0,0]);m['vertices'].append([icon['position'][0]+dx,icon['position'][1]+dy,icon['position'][2]+grad[0]*dx+grad[1]*dy])
        m['faces'].append([start,start+1,start+2])
        m['face_tiers'].append(icon.get('tiers',[0]))
scene['meshes'].extend(meshes.values())
from prepare_patterns import apply_waffle_pattern
pattern_report=apply_waffle_pattern(scene)
(out/'pattern_report.json').write_text(json.dumps(pattern_report,indent=2))
with gzip.open(out/'scene_with_icons.json.gz','wt',compresslevel=1) as f:f.write(json.dumps(scene,separators=(',',':')))
print('SVG symbols',len(scene['icons']),'triangles',sum(len(m['faces']) for m in meshes.values()))
