"""Moscow reconstruction rules for the mixed-provider geometry adapter.

Global domains first, tile clipping last. No city coordinates or object IDs.
Appearance evidence never replaces Yandex transport or building geometry.
"""
import collections, math
import numpy as np
import shapely as sh
from build_scene import polygons, lines, union, cdt
from landscape import GREEN_RAISE, GREEN_CURB_WIDTH, GREEN_VARIANTS, physical_green
from pedestrian_materials import RULES
from waterfront import DEPTH, bank_segments
from waterfront_finish import finished_bank, cornice_geometry, MATERIAL as GRANITE, install_texture
from waterfront_parapet import parapet_geometry, MATERIAL as PARAPET, JOINT_MATERIAL
from fence_geometry import TYPES, DEFAULT, EXTRA_MATERIALS, resolve, profile, prism
from street_library import Mesh, MATERIALS as STREET_MATERIALS
from street_placement import station_points

PEDESTRIAN_HEIGHT=.075
GREEN_HEIGHT=PEDESTRIAN_HEIGHT+GREEN_RAISE
OFFSETS=dict(road=.035,ped=PEDESTRIAN_HEIGHT,rail=.025,island=.15,parking=.035,
             water=-.12,cemetery=GREEN_HEIGHT,grass=GREEN_HEIGHT,sand=0,default=0)

def append_material(b,m):
    for i,v in enumerate(b.materials):
        if v==m:return i
    b.materials.append(dict(m));return len(b.materials)-1

def connected_water(water,extent):
    """Source water is connected before roads/crop ownership cut its skin."""
    pieces=list(polygons(sh.set_precision(water,1e-5)))
    selected=[p for p in pieces if p.distance(extent.boundary)<.03]
    return union(selected),dict(components=len(pieces),connectedComponents=len(selected),isolatedComponents=len(pieces)-len(selected))

def ground_offset(b,xy):
    pts=sh.points(np.asarray(xy));out=np.zeros(len(pts))
    for k,g in b.finished.items():
        if k in OFFSETS:out[sh.covers(g,pts)]=OFFSETS[k]
    if hasattr(b,'road_curb'):out[sh.covers(b.road_curb,pts)]=.135
    return out

def render_surface(b,g,material,offset):
    # Shared paving patterns use metre UVs; the legacy adapter used 10 m UVs.
    metric=b.materials[material].get('family','').startswith('pedestrian-')
    old=b.add
    if metric:
        def add(t,*args,**kwargs):
            t=t.copy();t[:,:,6:8]*=10;old(t,*args,**kwargs)
        b.add=add
    try:b.surface(g,material,'land',offset=offset)
    finally:
        if metric:b.add=old

def grounds(b,evidence):
    """Replace only ground skins/green edging; keep transport, paint and roofs."""
    stats={'paving':{},'green':{},'greenRaiseAbovePavementM':GREEN_RAISE,'greenCurbWidthM':GREEN_CURB_WIDTH}
    # Inset road bands own their footprint, never a second coplanar material.
    for k in b.finished:
        if k not in ('road','water'):b.finished[k]=b.finished[k].difference(b.road_curb)
    raised=physical_green(union([b.finished['grass'],b.finished['cemetery']]))
    band=physical_green(raised.difference(raised.buffer(-GREEN_CURB_WIDTH,join_style='mitre',mitre_limit=2)))
    band=physical_green(band.difference(b.circle.boundary.buffer(GREEN_CURB_WIDTH+.00005)))
    b.green_band=band
    stats['greenCurbAreaM2']=band.area
    # Unspecified surface keeps its approved neutral paving; don't fabricate
    # asphalt, wood, gravel or stone where neither provider identifies it.
    ped=b.finished['ped'];remaining=ped
    for layer,rule in RULES.items():
        part=remaining.intersection(evidence['areas'].get(layer,sh.Polygon()))
        render_surface(b,part,b.material(rule['material']),PEDESTRIAN_HEIGHT)
        remaining=remaining.difference(part);stats['paving'][rule['kind']]=part.area
        print('PAVING',rule['kind'],round(part.area,2),flush=True)
    render_surface(b,remaining,b.material(7),PEDESTRIAN_HEIGHT);stats['paving']['unspecified']=remaining.area
    grass=b.finished['grass'].difference(band);remaining=grass
    # More specific overlays precede woodland; borders follow their union.
    order=['Flowerbed_quarter','Immersive_park_polygon_green','Internal_lawn','Forest_quarter','Internal_forest_quarter']
    for layer in order:
        g=evidence['areas'].get(layer,sh.Polygon())
        if layer=='Forest_quarter':g=g.union(evidence['areas'].get('Suburban_forest_quarter',sh.Polygon()))
        part=remaining.intersection(g);name,color=GREEN_VARIANTS[layer]
        material=append_material(b,{**b.materials[b.material(2)],'name':name,'color':color,'family':'green-'+layer})
        render_surface(b,part,material,GREEN_HEIGHT);remaining=remaining.difference(part);stats['green'][layer]=part.area
        print('GREEN',layer,round(part.area,2),flush=True)
    render_surface(b,remaining,b.material(2),GREEN_HEIGHT);stats['green']['unspecified']=remaining.area
    render_surface(b,b.finished['cemetery'].difference(band),b.material(25),GREEN_HEIGHT)
    render_surface(b,band,b.material(9),GREEN_HEIGHT)
    b.boundary_walls(raised,lambda xy:b.terrain.sample(xy),lambda xy:b.terrain.sample(xy)+GREEN_HEIGHT,b.material(9),'green-curbs',clip=b.circle.buffer(-.02))
    definitions=[('road',0),('rail',28),('island',9),('parking',31),('sand',29),('default',1)]
    for kind,mat in definitions:
        render_surface(b,b.finished[kind],b.material(mat),OFFSETS[kind])
        print('RETAINED GROUND',kind,flush=True)
    b.boundary_walls(b.finished['island'],b.terrain.sample,lambda xy:b.terrain.sample(xy)+.15,b.material(9),'curbs',clip=b.circle.buffer(-.02))
    render_surface(b,b.building_footprint.difference(b.holes),b.material(1),0)
    network,water_stats=connected_water(b.land.get(('water',0,'ground'),sh.Polygon()),b.circle)
    selected=b.finished['water'].intersection(network);isolated=b.finished['water'].difference(network)
    b.surface(selected,b.material(13),'water',offset=OFFSETS['water']-DEPTH)
    b.surface(isolated,b.material(13),'water',offset=OFFSETS['water'])
    b.water_selected=selected
    water_stats.update(loweredAreaM2=selected.area,preservedPondAreaM2=isolated.area,depthM=DEPTH,policy='Yandex source river network before road cuts; source channel buffers connect river arms; only components open at acquisition perimeter; isolated ponds unchanged')
    stats['water']=water_stats
    stats['pathAreaM2']=ped.area;stats['raisedAreaM2']=raised.area
    stats['greenPavingOverlapM2']=raised.intersection(ped).area
    stats['greenRoadOverlapM2']=raised.intersection(b.finished['road']).area
    assert max(stats['greenPavingOverlapM2'],stats['greenRoadOverlapM2'])<.1
    b.style_audit=stats
    print('MOSCOW SURFACES',stats,flush=True)

def waterfront(b):
    domain=b.water_selected
    if domain.is_empty:return
    a,bb,along,rings,_=bank_segments(domain,b.circle.bounds)
    # bank_segments supports rectangular scenes; this adapter has a round crop.
    real=sh.distance(sh.points((a+bb)/2),b.circle.boundary)>.025
    a,bb,along,rings=a[real],bb[real],along[real],rings[real]
    # Split at actual DEM edges so the bank bottom meets the lowered mesh,
    # including where an endpoint belongs to a different terrain triangle.
    aa=[];zz=[];us=[];rr=[]
    for p,q,u,r in zip(a,bb,along,rings):
        line=sh.LineString([p,q]);d=q-p;length=np.linalg.norm(d)
        cuts=[0.,1.]
        for i in b.terrain.tree.query(line,predicate='intersects'):
            for part in lines(line.intersection(b.terrain.polygons[i])):
                cuts.extend(float(np.clip(np.dot(np.array(v)-p,d)/(length*length),0,1)) for v in (part.coords[0],part.coords[-1]))
        cuts=np.unique(np.round(cuts,10))
        for lo,hi in zip(cuts,cuts[1:]):
            if (hi-lo)*length<1e-4:continue
            aa.append(p+d*lo);zz.append(p+d*hi);us.append(u[0]+(u[1]-u[0])*np.array([lo,hi]));rr.append(r)
    a=np.asarray(aa);bb=np.asarray(zz);along=np.asarray(us);rings=np.asarray(rr)
    base=np.column_stack([b.terrain.sample(a),b.terrain.sample(bb)])+OFFSETS['water']
    d=bb-a;normal=np.column_stack([d[:,1],-d[:,0]])/np.linalg.norm(d,axis=1)[:,None]
    offsets=ground_offset(b,(a+bb)/2+normal*.03)
    top=np.column_stack([b.terrain.sample(a),b.terrain.sample(bb)])+offsets[:,None]
    # One height at shared joins; material changes cannot tear the cornice.
    _,inv=np.unique(np.rint(np.concatenate([a,bb])/1e-5).astype(np.int64),axis=0,return_inverse=True)
    h=np.full(inv.max()+1,-np.inf);np.maximum.at(h,inv,np.r_[top[:,0],top[:,1]])
    top=np.column_stack([h[inv[:len(a)]],h[inv[len(a):]]])
    banks=dict(a=a,b=bb,base=base,top=top,chainage=along,rings=rings)
    b.textures.update(install_texture(b.full))
    mat=append_material(b,GRANITE);origin=[0,0,b.alt]
    b.add(finished_bank(banks,origin),mat,'waterfront-granite')
    trim,trimstats=cornice_geometry(banks,origin,domain);b.add(trim,mat,'waterfront-cornice')
    bridges=union([g for (kind,level,mode),g in b.land.items() if mode=='deck' and level>=0]).buffer(.5)
    keep=~sh.intersects(bridges,sh.linestrings(np.stack([a,bb],axis=1)))
    pb={k:v[keep] for k,v in banks.items()}
    parapet,joint,parastats=parapet_geometry(pb,origin,domain,b.circle.bounds)
    pmat=append_material(b,PARAPET);jmat=append_material(b,JOINT_MATERIAL)
    b.add(parapet,np.where(joint,jmat,pmat),'waterfront-parapet')
    b.style_audit['water'].update(bankLengthM=float(np.linalg.norm(d,axis=1).sum()),bankSegments=len(a),cornice=trimstats,parapet=parastats,bridgeOpenParapetSegments=int((~keep).sum()))
    b.water_banks=banks
    print('MOSCOW WATERFRONT',b.style_audit['water'],flush=True)

def ribbon_centerlines(g):
    """Medial graph of a thin source ribbon from its triangulation dual.

    Internal triangle-edge midpoints preserve branches/closed loops. Terminal
    caps stop half a ribbon width short; no outline is mistaken for two fences.
    """
    for p in polygons(g):
        tris=cdt(p);edges=collections.defaultdict(list)
        for i,t in enumerate(tris):
            for j in range(3):
                a,b=t[j],t[(j+1)%3];key=tuple(sorted((tuple(a),tuple(b))))
                edges[key].append(i)
        links=collections.defaultdict(list)
        for edge,owners in edges.items():
            if len(owners)==2:
                midpoint=np.mean(edge,axis=0)
                for owner in owners:links[owner].append(midpoint)
        segments=[]
        for i,pts in links.items():
            if len(pts)==2:segments.append(sh.LineString(pts))
            elif len(pts)==3:
                center=np.mean(pts,axis=0);segments.extend(sh.LineString([q,center]) for q in pts)
        if not segments:
            # A single quad still represents one span, not an outline.
            rect=np.asarray(p.minimum_rotated_rectangle.exterior.coords)[:4];d=np.roll(rect,-1,axis=0)-rect;j=np.argmax(np.linalg.norm(d,axis=1));segments=[sh.LineString([(rect[j]+rect[(j-1)%4])/2,(rect[(j+1)%4]+rect[(j+2)%4])/2])]
        for line in lines(sh.line_merge(sh.union_all(segments))):
            # .03 m is below source ribbon width; keep sharp direction changes.
            q=line.simplify(.03)
            if q.length>.1:yield q

def fences(b,evidence,*,survey=None,ground=None):
    mats=[append_material(b,m) for m in STREET_MATERIALS+EXTRA_MATERIALS]
    typed=[r for r in evidence['fences'] if r['properties'].get('db_fence_type') in TYPES]
    tree=sh.STRtree([r['line'] for r in typed]);stats=collections.Counter();witness={};evidence_rows=[]
    mesh=Mesh();seen=set()
    unsupported=0.;survey_rows=[]
    for feature_index,(f,g,l) in enumerate(b.fences):
        if feature_index%100==0:print('FENCE FEATURES',feature_index,'/',len(b.fences),flush=True)
        for line_index,line in enumerate(ribbon_centerlines(g)):
            # Explicit overlapping and parallel source evidence only. A fence
            # around a neighbouring parcel cannot give this span a false type.
            pieces=[];rest=line
            for i in tree.query(line,predicate='dwithin',distance=1.5):
                r=typed[i];near=r['line'];overlap=rest.intersection(near.buffer(1.5,cap_style='flat'))
                for part in lines(overlap):
                    if part.length<2:continue
                    p,q=part.interpolate(.2,normalized=True),part.interpolate(.8,normalized=True)
                    d=np.array(q.coords[0])-p.coords[0];s=near.project(part.interpolate(.5,normalized=True));a=near.interpolate(max(0,s-.5));c=near.interpolate(min(near.length,s+.5));v=np.array(c.coords[0])-a.coords[0]
                    if abs(d@v)<.94*np.linalg.norm(d)*np.linalg.norm(v):continue
                    spec=resolve({'properties':r['properties'],'sourceRecordId':str(f.get('id'))},evidence['fenceRules'])
                    pieces.append((part,spec));rest=rest.difference(part)
                    evidence_rows.append(dict(yandexId=str(f.get('id')),sourceTile=r['sourceTile'],sourceCode=spec['sourceCode'],matchedLengthM=part.length))
            spec=dict(sourceCode=None,family=DEFAULT[2],heightM=DEFAULT[3],spacingM=DEFAULT[4],material=DEFAULT[5])
            pieces.extend((p,spec) for p in lines(rest))
            if survey:
                from survey_fences import source_key,overlay_pieces
                record=survey.get((source_key(f,g,l),line_index))
                if record:
                    np.testing.assert_allclose(np.asarray(line.coords),record['points'],atol=1e-9)
                    pieces=overlay_pieces(line,pieces,record)
            for part,spec in pieces:
                part=part.difference(b.finished['water'].union(b.holes))
                for span in lines(part):
                    # Exact terrain intersections already split at every real
                    # height-plane change. An extra 2 m grid only adds closed
                    # internal rail caps and triangles without changing shape.
                    coords=np.asarray((span if ground is not None else sh.segmentize(span,2.)).coords);heights=b.terrain.sample(coords)+ground_offset(b,coords)-b.alt
                    render=coords*[1,-1];code=str(spec['sourceCode']);stats['length:'+code]+=span.length;stats['parts:'+code]+=1
                    for a,c,ha,hc in zip(render[:-1],render[1:],heights[:-1],heights[1:]):
                        if ground is None:profile(mesh,a,c,ha,hc,spec)
                        else:
                            from fence_geometry import contact_intervals
                            aa,cc=np.array([a[0],0,a[1]]),np.array([c[0],0,c[1]])
                            intervals=contact_intervals(aa,cc,ground)
                            unsupported+=max(0.,1-sum(v-u for u,v,*_ in intervals))*np.linalg.norm(c-a)
                            for u,v,h0,h1,idx,offset in intervals:
                                p,q=a+(c-a)*u,a+(c-a)*v
                                if np.linalg.norm(q-p)<1e-5:continue
                                profile(mesh,p,q,h0,h1,spec)
                                if spec['family']=='wire':
                                    for y in np.arange(.35,spec['heightM']-.2,.25):prism(mesh,p,q,h0,h1,y,y+.008,.008,spec['material'])
                    # Stations use original ribbon chainage, not tile boundaries.
                    phase=line.project(sh.Point(span.coords[0]));spacing=spec['spacingM'];stations=[] if spec['family']=='hedge' else [(s,q,'post') for s,q in station_points(render,spacing,phase)]
                    if spec['family'] in ('wood','metal','wire'):
                        step=spacing/round(spacing/(.17 if spec['family']=='wood' else .15));stations.extend((s,q,'picket') for s,q in station_points(render,step,phase))
                    if spec['family']!='hedge':stations.extend([(0,render[0],'post'),(span.length,render[-1],'post')])
                    stations.sort(key=lambda p:p[2]!='post')
                    for s,q,kind in stations:
                        key=(code,*np.round(q,5))
                        if key in seen:continue
                        seen.add(key);xy=np.array(q)*[1,-1];height=float(b.terrain.sample([xy])[0]+ground_offset(b,[xy])[0]-b.alt)
                        a=np.array(span.interpolate(max(0,s-.01)).coords[0]);c=np.array(span.interpolate(min(span.length,s+.01)).coords[0]);d=(c-a)*[1,-1];d/=max(np.linalg.norm(d),1e-10)
                        if ground is not None:
                            normal=np.array([-d[1],d[0]])*.025;hit=None
                            for offset in [np.zeros(2),normal,-normal]:
                                hit=ground.ground(*(np.asarray(q)+offset))
                                if hit is not None:break
                            if hit is None:continue
                            height=hit['height']
                        width=(.19 if spec['family']=='solid' else .10 if spec['family']=='wood' else .065) if kind=='post' else (.12 if spec['family']=='wood' else .026)
                        if kind=='picket' and spec['family']=='wire':width=.008
                        prism(mesh,q-d*width/2,q+d*width/2,height,height,-.02 if kind=='post' else .06,spec['heightM'],width if kind=='post' else .045 if spec['family']=='wood' else width,spec['material'])
                    if spec.get('surveyHandles'):
                        survey_rows.append(dict(sourceId=source_key(f,g,l),lineIndex=line_index,handles=spec['surveyHandles'],family=code,lengthM=span.length))
                    if code not in witness and span.length>8:
                        q=span.interpolate(.5,normalized=True);witness[code]=dict(yaw=-.6,pitch=.48,distance=26,target=[q.x,float(b.terrain.sample([[q.x,q.y]])[0]-b.alt)+.7,-q.y])
                    if len(mesh.faces)>90000:
                        t,m=mesh.arrays(consume=True);b.add(t,np.asarray(mats)[m],'street-fences')
    if mesh.faces:
        t,m=mesh.arrays(consume=True);b.add(t,np.asarray(mats)[m],'street-fences')
    b.style_audit['fences']={'stats':dict(stats),'sourceMatches':evidence_rows,'surveyMatches':survey_rows,'unsupportedFinishedGroundM':float(unsupported),'witnessViews':witness,'supportedCodes':{str(k):v[1] for k,v in TYPES.items()},'unknownPolicy':'neutral two-rail display; material not invented; source Yandex ribbon medial graph retained'}
    print('MOSCOW FENCES',dict(stats),flush=True)
