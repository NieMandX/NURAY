"""Project the public 2GIS geometry into the documented MGGT approximation.
Keep source coordinates in the cache; geometry is clipped to a metric square.
"""
import json, math, sys, gzip, hashlib, re
from pathlib import Path
from collections import Counter
import numpy as np
from pyproj import CRS, Transformer
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'prototype'))
from source_objects import exterior_record, BUILDING_LAYERS

plan_path=Path(sys.argv[1]).resolve()
plan=json.loads(plan_path.read_text()); OUT=Path(plan['output']); ROOT=plan_path.parents[2]; CACHE=ROOT/'source/cache'
proj=Transformer.from_crs('EPSG:4326',CRS.from_proj4(plan['crs_proj']),always_xy=True)
MPM=2**32/(2*math.pi*6378137)
B=plan['extent_msk_east_north']; cx,cy=plan['center_msk_east_north']
style=json.loads((ROOT/'source/map_style.json').read_text())['result']
layers=json.loads((ROOT/'source/style_flat.json').read_text())
meshes={}; points=[]; instances=[]; icons=[]; resources={}; counts=Counter(); used=Counter(); unmatched=Counter()
footprints={}
active_tiers=[]
active_color='white'
modeldata=json.loads((OUT/'models.json').read_text()); modelids={str(f['properties'].get(k)) for f in modeldata for k in ('building_id','db_object_building_id')}
def ll(wx,wy):return wx/2**32*360,np.degrees(np.arctan(np.sinh(wy/2**32*2*math.pi)))
def inside(x,y):return B[0]<=x<=B[2] and B[1]<=y<=B[3]
def mapping(lon,lat):
    e,n=proj.transform(lon,lat); wx=lon/360*2**32;wy=math.asinh(math.tan(math.radians(lat)))/(2*math.pi)*2**32
    ex,nx=proj.transform(*ll(wx+100,wy));ey,ny=proj.transform(*ll(wx,wy+100))
    return [e,n], [[(ex-e)/100,(ey-e)/100],[(nx-n)/100,(ny-n)/100]],1/(MPM/math.cos(math.radians(lat)))
def evaluate(x,p):
    if not isinstance(x,list):return x
    if not x:return x
    op=x[0]
    if op=='get':return p.get('db_'+x[1],p.get(x[1]))
    if op=='global':return {'graphicsPreset':'immersive','immersiveRoadsOn':True,'_activeFloorIsMetro':False}.get(x[1],False)
    if op=='zoom':return 19
    if op=='distance':return 0
    if op=='literal':return [evaluate(a,p) for a in x[1]]
    if op=='random':return (x[1]+x[2])/2 # display variation only; deterministic representative
    if op=='coalesce':return next((v for a in x[1:] if (v:=evaluate(a,p)) is not None),None)
    if op=='match':
        v=evaluate(x[1],p)
        for k in range(2,len(x)-1,2):
            if v in (x[k] if isinstance(x[k],list) else [x[k]]):return evaluate(x[k+1],p)
        return evaluate(x[-1],p)
    if op=='case':
        for k in range(1,len(x)-1,2):
            if evaluate(x[k],p):return evaluate(x[k+1],p)
        return evaluate(x[-1],p)
    if op=='step':
        v=evaluate(x[1],p);result=x[2]
        for k in range(3,len(x),2):
            if v>=x[k]:result=x[k+1]
        return evaluate(result,p)
    if op=='interpolate':return evaluate(x[-1],p) # final zoom stop, fixed detailed map view
    if op=='meters-to-pixels':return evaluate(x[1],p) # Blender operates in metres
    if op=='pattern':return [x[1]]+[evaluate(v,p) for v in x[2:]]
    a=[evaluate(v,p) for v in x[1:]]
    try:
        if op=='all':return all(a)
        if op=='any':return any(a)
        if op=='!':return not a[0]
        if op=='==':return a[0]==a[1]
        if op=='!=':return a[0]!=a[1]
        if op=='*':return math.prod(a)
        if op=='+':return sum(a)
        if op=='-':return a[0]-a[1]
        if op=='/':return a[0]/a[1]
        if op=='>':return a[0]>a[1]
        if op=='>=':return a[0]>=a[1]
        if op=='<':return a[0]<a[1]
    except (TypeError,ValueError,ZeroDivisionError):pass
    return None
bylayer={}
def findstyle(s,p,kind):
    key=(s,kind)
    if key not in bylayer:bylayer[key]=[l for l in layers if l['type']==kind and s in str(l.get('filter')) and l.get('style',{}).get('visibility')!='none']
    for l in bylayer[key]:
        if evaluate(l.get('filter'),p):return l['style']
    return None
def resource(kind,name):
    if name not in style.get(kind,{}):return None
    rel=style[kind][name]['url'];file=CACHE/('style_'+rel)
    resources[str(file)]={'url':f'https://disk.2gis.com/styles/assets/{kind}/{rel}','file':str(file)}
    return str(file)
def clip(poly):
    for axis,edge,sign in [(0,B[0],1),(0,B[2],-1),(1,B[1],1),(1,B[3],-1)]:
        if not poly:return []
        out=[];a=poly[-1];ain=(a[axis]-edge)*sign>=-1e-7
        for b in poly:
            bin=(b[axis]-edge)*sign>=-1e-7
            if ain!=bin:
                t=(edge-a[axis])/(b[axis]-a[axis]);out.append([a[k]+t*(b[k]-a[k]) for k in range(3)])
            if bin:out.append(b)
            a,ain=b,bin
        poly=out
    return poly
def face(name,category,vs):
    if category not in {'Buildings','Road_markings','Road_marking_symbols'}:return
    if category in {'Road_markings','Road_marking_symbols'}:name=name+'__'+active_color
    vs=clip([list(v) for v in vs])
    if len(vs)<3:return
    # Permit vertical building walls; reject actual degenerate polygons.
    if np.linalg.norm(np.cross(np.subtract(vs[1],vs[0]),np.subtract(vs[2],vs[0])))<1e-7:return
    m=meshes.setdefault(name,{'name':name,'category':category,'vertices':[],'faces':[],'face_tiers':[]});offset=len(m['vertices']);m['vertices'].extend(vs);m['faces'].append(list(range(offset,offset+len(vs))));m['face_tiers'].append(active_tiers)
def strip(s,cat,xyz):
    for i in range(len(xyz)-2):face(s,cat,[xyz[i+1],xyz[i],xyz[i+2]] if i%2 else xyz[i:i+3])
def ribbon(s,cat,xyz,width,dash=None,offset=0):
    distance=0.0
    for a,b in zip(xyz,xyz[1:]):
        dx,dy=b[0]-a[0],b[1]-a[1];length=math.hypot(dx,dy)
        if length<1e-6:continue
        nx,ny=-dy/length,dx/length;t=0
        while t<length-1e-7:
            end=length;draw=True
            if dash:
                phase=(distance+t)%sum(dash);draw=phase<dash[0];end=min(length,t+(dash[0]-phase if draw else sum(dash)-phase))
                if end<=t+1e-7:end=min(length,t+1e-6)
            if draw:
                v0=[a[k]+(b[k]-a[k])*t/length for k in range(3)];v1=[a[k]+(b[k]-a[k])*end/length for k in range(3)]
                face(s,cat,[[v0[0]+nx*(offset-width/2),v0[1]+ny*(offset-width/2),v0[2]],[v1[0]+nx*(offset-width/2),v1[1]+ny*(offset-width/2),v1[2]],[v1[0]+nx*(offset+width/2),v1[1]+ny*(offset+width/2),v1[2]],[v0[0]+nx*(offset+width/2),v0[1]+ny*(offset+width/2),v0[2]]])
            t=end
        distance+=length

for tile in plan['tiles']:
    data=json.loads((CACHE/('_'.join(map(str,tile[:3]))+'.json')).read_text());info=data['tile_info']
    for f in data['features']:
        p=f['properties'];s=p['db_sublayer'];raw=f['_raw'];counts[s]+=1;active_tiers=p.get('db_tiers') or [0]
        if not exterior_record(p):continue
        active_color='yellow' if p.get('db_road_marking_color_type') in (2,'yellow') or s in ('LinearMarking_Stop','LinearMarking_TramStop') else 'blue' if p.get('db_road_marking_color_type') in (3,'blue') else 'white'
        if not raw.get('x'):continue
        wx=info['offset'][0]+np.array(raw['x'])*info['size']/32768;wy=info['offset'][1]+np.array(raw['y'])*info['size']/32768
        lon,lat=ll(wx,wy);e,n=proj.transform(lon,lat);factor=MPM/np.cos(np.radians(lat))
        z=np.array(raw.get('signed_z',np.array(raw.get('z',np.zeros(len(e))))*32))/factor
        xyz=np.column_stack((e,n,z)).tolist()
        if max(e)<B[0] or min(e)>B[2] or max(n)<B[1] or min(n)>B[3]:continue
        used[s]+=1
        typ=p['db_geometry_type']
        if typ=='polygon':
            building=s in BUILDING_LAYERS
            if building:
                if p.get('id'):
                    target=footprints.setdefault(str(p['id']),[])
                    for k in range(len(xyz)-2):target.append([v[:2] for v in xyz[k:k+3]])
                if str(p.get('id')) in modelids:continue
                h=p.get('db_height_m',p.get('db_height',p.get('db_nominal_height',0))/float(np.mean(factor)))
                name=f"{s}_{p.get('id',tile[0])}";roof=[[a,b,c+h] for a,b,c in xyz];strip(name,'Buildings',roof)
                order=[0]+[min(2*i-1,2*(len(xyz)-i)) for i in range(1,len(xyz))]
                for i,j in zip(order,order[1:]+order[:1]):
                    if raw.get('cut',[1]*len(xyz))[i]==1 and h:face(name,'Buildings',[xyz[i],xyz[j],roof[j],roof[i]])
                continue
            if s in ['Region','Administrative_district','Area_of_interest']:
                cat='Source_areas_hidden'
            elif s.startswith('PolygonMarkings'):
                cat='Road_markings'
                if s=='PolygonMarkings_waffle':resource('icons','waffle')
            elif 'Roadbed' in s or s.startswith('Roadbed'):cat='Road_surfaces'
            elif s in ['Water_area','Immersive_park_polygon_blue']:cat='Water'
            elif any(k in s.lower() for k in ['forest','green','flowerbed']):cat='Green_areas'
            else:cat='Land_cover'
            offset={'Road_markings':0.035,'Road_surfaces':0.01,'Water':-0.02,'Green_areas':-0.025,'Land_cover':-0.04,'Source_areas_hidden':-0.5}[cat]
            if s=='Administrative_quarter':offset=-.12
            strip(s,cat,[[a,b,c+offset] for a,b,c in xyz])
            if cat=='Road_surfaces' and active_tiers!=[0] and max(z)>0.05:
                st=findstyle(s,p,'overpass') or {};thickness=st.get('thickness',.5)
                strip(s+'_Deck_bottom','Overpass_structure',[[a,b,c-thickness] for a,b,c in xyz])
                order=[0]+[min(2*i-1,2*(len(xyz)-i)) for i in range(1,len(xyz))]
                for i,j in zip(order,order[1:]+order[:1]):
                    if raw.get('cut',[1]*len(xyz))[i]==1:face(s+'_Deck_sides','Overpass_structure',[xyz[i],xyz[j],[xyz[j][0],xyz[j][1],xyz[j][2]-thickness],[xyz[i][0],xyz[i][1],xyz[i][2]-thickness]])
        elif typ=='polyline':
            if s.startswith('LinearMarking'):
                st=findstyle(s,p,'line') or {};w=evaluate(st.get('width',0.15),p) or .15;pattern=evaluate(st.get('pattern'),p)
                xyz=[[a,b,c+.05] for a,b,c in xyz]
                if pattern and pattern[0]=='doubledash':
                    gap=pattern[2] if isinstance(pattern[2],(float,int)) else .2;lw=max(.1,(w-gap)/2)
                    ribbon(s,'Road_markings',xyz,lw,None,-(gap+lw)/2)
                    ribbon(s,'Road_markings',xyz,lw,None if s.endswith('Double') else (pattern[3],pattern[4]),(gap+lw)/2)
                else:ribbon(s,'Road_markings',xyz,w,(pattern[1],pattern[2]) if pattern and pattern[0]=='stripe' else None)
            elif s.startswith('Roadbed_outline'):
                ribbon(s,'Road_edges',[[a,b,c+.06] for a,b,c in xyz],.12)
                if max(z)>.05:
                    st=findstyle(s,p,'overpass') or {};w=st.get('borderWidth',.7);h=st.get('borderHeight',.3)
                    ribbon(s+'_Border_top','Overpass_structure',[[a,b,c+h] for a,b,c in xyz],w)
                    for a,b in zip(xyz,xyz[1:]):
                        length=math.hypot(b[0]-a[0],b[1]-a[1])
                        if length<1e-7:continue
                        nx,ny=-(b[1]-a[1])/length*w/2,(b[0]-a[0])/length*w/2
                        for sign in [-1,1]:face(s+'_Border_sides','Overpass_structure',[[a[0]+sign*nx,a[1]+sign*ny,a[2]],[b[0]+sign*nx,b[1]+sign*ny,b[2]],[b[0]+sign*nx,b[1]+sign*ny,b[2]+h],[a[0]+sign*nx,a[1]+sign*ny,a[2]+h]])
            else:
                m=meshes.setdefault(s,{'name':s,'category':'Source_lines_hidden','vertices':[],'faces':[],'edges':[]});o=len(m['vertices']);m['vertices'].extend(xyz);m['edges'].extend([[o+i,o+i+1] for i in range(len(xyz)-1)])
        else:
            st=findstyle(s,p,'metricPoint') if s.startswith('PointMarkings') else findstyle(s,p,'model')
            for idx,v in enumerate(xyz):
                if not inside(*v[:2]):continue
                points.append({'layer':s,'position':v,'properties':p})
                if st and s.startswith('PointMarkings'):
                    icon=evaluate(st.get('iconImage'),p);file=resource('icons',icon)
                    if file:icons.append({'file':file,'layer':s,'position':[v[0],v[1],v[2]+.055],'width':evaluate(st.get('width',1),p),'height':evaluate(st.get('height',1),p),'angle':evaluate(st.get('rotation',0),p) or 0,'tiers':active_tiers})
                elif st:
                    name=evaluate(st.get('modelSrc'),p);file=resource('models',name)
                    if file:
                        scale=evaluate(st.get('scale',1),p);rot=evaluate(st.get('rotation',['literal',[0,0,0]]),p)
                        instances.append({'file':file,'layer':s,'position':v,'scale':scale,'rotation':rot,'properties':p})
                    else:unmatched[s]+=1
                else:unmatched[s]+=1
    print('prepared tile',tile[:3],flush=True)

models=[]
for f in modeldata:
    lon,lat=f['geometry']['coordinates'][:2];position,jac,factor=mapping(lon,lat)
    # Match current browser Oh(): direction provides the Mercator-unit scale
    # and rotation when explicit angle/scale are absent (Commercial_model).
    props=f['properties'];direction=props.get('direction',{}).get('coordinates')
    if direction:
        wx,wy=lon/360*2**32,math.asinh(math.tan(math.radians(lat)))/(2*math.pi)*2**32
        tx,ty=direction[0]/360*2**32,math.asinh(math.tan(math.radians(direction[1])))/(2*math.pi)*2**32
        props.setdefault('angle',math.atan2(ty-wy,tx-wx));props.setdefault('scale',math.hypot(tx-wx,ty-wy))
    else:props.setdefault('scale',1/factor)

    f.update(position=position,jacobian=jac,z_factor=factor);models.append(f)
scene={'plan':plan,'meshes':list(meshes.values()),'models':models,'instances':instances,'icons':icons,'building_footprints':footprints}
# Heights and road-domain clipping are resolved by the canonical surface builder.

with gzip.open(OUT/'scene.json.gz','wt') as h:json.dump(scene,h,separators=(',',':'))
with gzip.open(OUT/'source_points.json.gz','wt') as h:json.dump(points,h,separators=(',',':'))
(OUT/'resources.json').write_text(json.dumps(list(resources.values()),indent=2))
report={'source_features_by_layer':dict(counts),'intersecting_features_by_layer':dict(used),'point_features_without_display_mesh':dict(unmatched),'mesh_groups':len(meshes),'vertices':sum(len(x['vertices']) for x in meshes.values()),'faces':sum(len(x['faces']) for x in meshes.values()),'street_model_instances':len(instances),'road_marking_icons':len(icons),'retained_point_records':len(points),'custom_models_before_clipping':len(models)}
(OUT/'preparation_report.json').write_text(json.dumps(report,indent=2));print(json.dumps({k:v for k,v in report.items() if not isinstance(v,dict)},indent=2))
