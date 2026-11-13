"""Conservative recognition of nested circular shafts, without object-ID rules.

Single round towers and residential buildings are deliberately left alone.
This is a geometric inference, not a semantic claim by the source provider.
"""
import math
import numpy as np
import shapely as sh


def detect(buildings):
    candidates=[]
    for index,(feature,geometry) in enumerate(buildings):
        a=feature['attributes'];height=a.get('height',0)
        if a.get('ft_type_name')!='urban-structure' or not isinstance(height,(int,float)) or height<30 or geometry.geom_type!='Polygon':continue
        outer=sh.Polygon(geometry.exterior)
        if len(geometry.interiors)!=1 or len(geometry.exterior.coords)<9:continue
        center=np.array(outer.centroid.coords[0]);r=math.sqrt(outer.area/math.pi)
        distances=np.linalg.norm(np.asarray(outer.exterior.coords)[:-1]-center,axis=1)
        if height/(2*r)<3 or distances.std()/distances.mean()>.08:continue
        candidates.append(dict(index=index,feature=feature,geometry=geometry,outer=outer,center=center,radius=r,height=float(height)))
    groups=[];used=set()
    for c in sorted(candidates,key=lambda c:-c['radius']):
        if c['index'] in used:continue
        nested=[q for q in candidates if q['index'] not in used and np.linalg.norm(q['center']-c['center'])<min(.75,c['radius']*.15) and c['outer'].buffer(.01).covers(q['outer'])]
        nested.sort(key=lambda q:q['height'])
        if len(nested)<2 or nested[-1]['height']/(2*c['radius'])<6:continue
        if any(b['height']-a['height']<5 or b['radius']>=a['radius']*.98 for a,b in zip(nested,nested[1:])):continue
        if not .3<nested[-1]['radius']/nested[0]['radius']<.9:continue
        groups.append(dict(parts=nested,center=nested[0]['center'],baseRadius=nested[0]['radius'],topRadius=nested[-1]['radius'],height=nested[-1]['height']))
        used.update(q['index'] for q in nested)
    return groups


def materials(existing):
    specs=[('Industrial chimney · white',[.65,.65,.62]),('Industrial chimney · red',[.32,.052,.035]),('Industrial chimney · inner shaft',[.055,.048,.042])]
    result=[]
    for name,color in specs:
        match=next((i for i,m in enumerate(existing) if m['name']==name),None)
        if match is None:
            match=len(existing);existing.append(dict(name=name,family='IndustrialChimney',color=color,roughness=.82,metallic=0.,ior=1.5,kind=1,texture=None,alphaCutoff=0.))
        result.append(match)
    return result


def mesh(group,base,ground,alt,segments=48,bands=8):
    """Smooth frustum: horizontal paint bands, recessed dark opening, seated base.

    Coordinates are east/north in, east/up/south out. Paint is two shared
    materials, with no facade-floor shader, surface offsets or texture seams.
    """
    center=np.asarray(group['center']);r0=group['baseRadius'];r1=group['topRadius'];height=group['height']
    theta=np.arange(segments)*2*math.pi/segments
    radial=np.column_stack([np.cos(theta),np.sin(theta)])
    slope=(r0-r1)/height
    outward=np.column_stack([radial[:,0],np.full(segments,slope),-radial[:,1]])
    outward/=np.linalg.norm(outward,axis=1,keepdims=True)
    def ring(radius,y,normals):
        xy=center+radial*radius;v=np.zeros((segments,8));v[:,0]=xy[:,0];v[:,2]=-xy[:,1];v[:,1]=np.asarray(y)-alt;v[:,3:6]=normals;return v
    rings=[]
    for band in range(bands+1):
        u=band/bands;radius=r0+(r1-r0)*u
        y=ground(center+radial*radius)-.03 if band==0 else base+height*u
        rings.append(ring(radius,y,outward))
    triangles=[];mats=[]
    def triangle(a,b,c,material):
        t=np.array([a,b,c]);cross=np.cross(t[1,:3]-t[0,:3],t[2,:3]-t[0,:3])
        if np.dot(cross,t[:,3:6].mean(0))<0:t=t[[0,2,1]]
        triangles.append(t);mats.append(material)
    def strip(a,b,material):
        for i in range(segments):
            j=(i+1)%segments;triangle(a[i],a[j],b[j],material);triangle(a[i],b[j],b[i],material)
    for band in range(bands):strip(rings[band],rings[band+1],band%2)
    thickness=min(.35,r1*.12);top=base+height
    rimOuter=ring(r1,top,[0,1,0]);rimInner=ring(r1-thickness,top,[0,1,0]);strip(rimOuter,rimInner,1)
    innerNormals=np.column_stack([-radial[:,0],np.zeros(segments),radial[:,1]])
    innerTop=ring(r1-thickness,top,innerNormals);innerBottom=ring(r1-thickness,top-min(4,height*.1),innerNormals);strip(innerTop,innerBottom,2)
    cap=innerBottom.copy();cap[:,3:6]=[0,1,0];middle=cap[0].copy();middle[[0,2]]=[center[0],-center[1]]
    for i in range(segments):triangle(middle,cap[i],cap[(i+1)%segments],2)
    return np.asarray(triangles),np.asarray(mats,np.uint32)


def emit(builder,groups):
    if not groups:return
    mids=np.array(materials(builder.materials),np.uint32)
    for group in groups:
        xy=np.asarray(group['parts'][0]['outer'].exterior.coords)
        base=float(np.max(builder.terrain.sample(xy)))+.1
        t,m=mesh(group,base,builder.terrain.sample,builder.alt)
        builder.add(t,mids[m],'industrial-chimneys')
        builder.building_tops.append((group['parts'][0]['outer'],base+group['height']))

