"""Source-typed fence sections, constructed before transport-tile clipping.

Type names come from the retained 2GIS style, dimensions are NURAY defaults.
Unknown codes stay unknown; the neutral two-rail display is not a material claim.
"""
from collections import Counter
import math
import numpy as np
import shapely as sh
from street_library import Mesh
from street_placement import evaluate, station_points, clip_segment
from adaptive_foundations import ground_intervals

EXTRA_MATERIALS = [
    dict(name='Ограды · кирпич',color=[.31,.115,.065],roughness=.92,metallic=0),
    dict(name='Ограды · живая изгородь',color=[.075,.16,.035],roughness=.95,metallic=0),
]
for m in EXTRA_MATERIALS:m.update(family='street',ior=1.5,kind=1,alphaCutoff=0)

# Source code, resource, label, family, height, section spacing, material index.
TYPES = {
    0: ('fenceconcrete','Бетонное','solid',1.8,1.3,2),
    1: ('fencebrick','Кирпичное','solid',1.8,1.4,9),
    2: ('fencewood','Деревянное','wood',1.6,1.7,1),
    3: ('fencemetalhigh','Металлическое · высокое','metal',1.8,1.8,0),
    4: ('fencemetallow','Металлическое · низкое','metal',.9,1.3,0),
    5: ('fencetreehigh','Живая изгородь · высокая','hedge',1.8,2.5,10),
    6: ('fencetreelow','Живая изгородь · низкая','hedge',.8,1.5,10),
}
DEFAULT = ('fencedefault','Тип не указан','neutral',1.2,1.3,0)
POLICY = dict(version=1,typeField='db_fence_type',typeSource='retained visible 2GIS model rules',
    dimensions='NURAY display defaults, not surveyed dimensions',
    unknown='neutral two-rail display; no inferred concrete/wood/metal type',
    ground='exact upper envelope of finished ground; adjacent contact within 2.5 cm for source XY quantization only; no bridging terrain voids',
    stations='source component distance phase before transport clipping; no posts added at tile cuts')


def resolve(record, rules):
    candidates=[r for r in rules if r['type']=='model'
        and r['style'].get('visibility','visible')=='visible'
        and evaluate(r.get('filter',True),record['properties'])]
    assert len(candidates)==1, ('Ambiguous/missing fence style',record['sourceRecordId'])
    rule=candidates[0];src=rule['style']['modelSrc']
    resource=src if isinstance(src,str) else src[2]  # near-distance arm of step
    code=record['properties'].get('db_fence_type');spec=TYPES.get(code,DEFAULT)
    assert resource==spec[0], ('Unmapped fence resource',code,resource)
    return dict(sourceCode=code,typeStatus='source' if code in TYPES else ('missing' if code is None else 'unknown-code'),
        resource=resource,styleId=rule['id'],label=spec[1],family=spec[2],heightM=spec[3],spacingM=spec[4],material=spec[5])


def prism(mesh,a,b,ha,hb,low,high,width,mat):
    """Closed rectangular sweep; Y stays vertical on slopes, outward winding."""
    a,b=np.asarray(a),np.asarray(b);d=b-a;length=np.linalg.norm(d)
    if length<1e-6:return
    n=np.array([-d[1],d[0]])/length*width/2
    corners=[(a-n,ha),(b-n,hb),(b+n,hb),(a+n,ha)]
    v=np.array([[p[0],h+y,p[1]] for p,h in corners for y in [low,high]])
    quads=v[np.array([(0,2,3,1),(2,4,5,3),(4,6,7,5),(6,0,1,7),(1,3,5,7),(6,4,2,0)])[:,::-1]]
    mesh.face_batch(quads[:,[0,1,2,0,2,3],:].reshape(-1,3,3),mat)


def profile(mesh,a,b,ha,hb,spec):
    h,mat,family=spec['heightM'],spec['material'],spec['family']
    if family=='solid':
        prism(mesh,a,b,ha,hb,-.02,h-.07,.16 if mat==2 else .24,mat)
        prism(mesh,a,b,ha,hb,h-.07,h,.22 if mat==2 else .30,2)
    elif family=='hedge':
        # A bevelled, solid clipped hedge rather than a metal barrier.
        d=np.asarray(b)-a;n=np.array([-d[1],d[0]])/np.linalg.norm(d)
        w=.48 if h>1 else .30
        ring=[(-w,-.02),(-w,.65*h),(-.7*w,h),(.7*w,h),(w,.65*h),(w,-.02)]
        one=np.array([[a[0]+n[0]*x,ha+y,a[1]+n[1]*x] for x,y in ring])
        two=np.array([[b[0]+n[0]*x,hb+y,b[1]+n[1]*x] for x,y in ring])
        for i in range(len(ring)):
            j=(i+1)%len(ring);mesh.quad([one[j],two[j],two[i],one[i]],mat)
        for i in range(1,len(ring)-1):
            mesh.face([one[0],one[i+1],one[i]],mat);mesh.face([two[0],two[i],two[i+1]],mat)
    else:
        w=.07 if family=='wood' else .045
        for y in [.23,h-.18]:prism(mesh,a,b,ha,hb,y,y+w,w,mat)


def contact_intervals(a,b,ground):
    intervals=[(*r,[0.,0.]) for r in ground_intervals(a,b,ground)]
    d=(b-a)[[0,2]];normal=np.array([-d[1],d[0]])/np.linalg.norm(d)*.025
    for offset in [normal,-normal]:
        covered=sh.union_all([sh.LineString([[u,0],[v,0]]) for u,v,*_ in intervals])
        missing=sh.LineString([[0,0],[1,0]]).difference(covered)
        if missing.is_empty:break
        aa,bb=a.copy(),b.copy();aa[[0,2]]+=offset;bb[[0,2]]+=offset
        for u,v,h0,h1,idx in ground_intervals(aa,bb,ground):
            for gap in sh.get_parts(missing):
                lo,hi=max(u,gap.bounds[0]),min(v,gap.bounds[2])
                if hi-lo<=1e-10:continue
                height=lambda s:h0+(h1-h0)*(s-u)/(v-u)
                intervals.append((lo,hi,height(lo),height(hi),idx,offset.tolist()))
    return sorted(intervals,key=lambda r:r[0])


def build(records,city,ground,rules):
    mesh=Mesh();objects=[];account=[];posts=set();segments=set();witness=[]
    ox,oy,_=city['originMSK'];bounds=city['boundsMSK'];box=[bounds[0]-ox,oy-bounds[3],bounds[2]-ox,oy-bounds[1]]
    fence_records=[r for r in records if r['layer']=='Fence']
    for index,r in enumerate(fence_records):
        if index and index%500==0:print('FENCE RECORDS',index,'/',len(fence_records),flush=True)
        spec=resolve(r,rules);code=spec['sourceCode'];p=r['properties']
        coords=np.array([[q[0]-ox,oy-q[1]] for q in r['coordinatesMSK']]);line=sh.LineString(coords)
        phase=p.get('componentDistanceStart',0)*r['source']['coordinateStepM']
        start=len(mesh.faces);unbound=0.;contacts=[];uprights=[]
        for a,b in zip(coords,coords[1:]):
            if np.linalg.norm(b-a)<.01:continue
            cut=clip_segment(a,b,box)
            if cut is None:continue
            a,b=np.array(cut);key=(code,tuple(sorted((tuple(np.round(a,6)),tuple(np.round(b,6))))))
            if key in segments:continue
            segments.add(key)
            aa,bb=np.array([a[0],0,a[1]]),np.array([b[0],0,b[1]])
            intervals=contact_intervals(aa,bb,ground)
            unbound+=max(0.,1-sum(v-u for u,v,*_ in intervals))*float(np.linalg.norm(b-a))
            for u,v,h0,h1,idx,offset in intervals:
                q0,q1=np.round([a+(b-a)*u,a+(b-a)*v],10)
                if np.linalg.norm(q1-q0)<1e-5:continue
                before=len(mesh.faces);profile(mesh,q0,q1,h0,h1,spec)
                contacts.append(dict(a=q0.tolist(),b=q1.tolist(),heights=[h0,h1],ground=list(ground.refs[idx]),groundOffsetM=offset,first=before-start,count=len(mesh.faces)-before))
        if spec['family']!='hedge':
            stations=[(s,q,'post') for s,q in station_points(coords,spec['spacingM'],phase)]
            if spec['family'] in ('metal','wood'):
                # Subdivision of the same global section phase: no reset at a tile.
                steps=round(spec['spacingM']/(.15 if spec['family']=='metal' else .17))
                stations.extend((s,q,'picket') for s,q in station_points(coords,spec['spacingM']/steps,phase))
            distance=0.
            for i,q in enumerate(coords):
                if i:distance+=float(np.linalg.norm(q-coords[i-1]))
                if (i==0 and p.get('beginningIsCut')) or (i==len(coords)-1 and p.get('endingIsCut')):continue
                stations.append((distance,q,'post'))
            # Main posts win over coincident pickets, including bends/endpoints.
            stations.sort(key=lambda x:x[2]!='post')
            for s,q,kind in stations:
                q=np.asarray(q)
                if not(box[0]<=q[0]<=box[2] and box[1]<=q[1]<=box[3]):continue
                key=(code,*np.round(q,5))
                if key in posts:continue
                before=line.interpolate(max(0,s-.005));after=line.interpolate(min(line.length,s+.005))
                tangent=np.array([after.x-before.x,after.y-before.y]);norm=np.linalg.norm(tangent)
                if norm<1e-8:continue
                tangent/=norm;normal=np.array([-tangent[1],tangent[0]])*.025
                hit=None;offset=np.zeros(2)
                for offset in [np.zeros(2),normal,-normal]:
                    hit=ground.ground(*(q+offset))
                    if hit:break
                if hit is None:continue
                posts.add(key)
                h=spec['heightM'];mat=spec['material'];family=spec['family']
                width=(.19 if family=='solid' else .10 if family=='wood' else .065) if kind=='post' else (.12 if family=='wood' else .026)
                thick=width if kind=='post' else (.045 if family=='wood' else width)
                lo=-.02 if kind=='post' else .06;hi=h+(.045 if kind=='post' else 0)
                first=len(mesh.faces);prism(mesh,q-tangent*width/2,q+tangent*width/2,hit['height'],hit['height'],lo,hi,thick,mat)
                uprights.append(dict(stationM=s,kind=kind,point=q.tolist(),height=hit['height'],groundOffsetM=offset.tolist(),widthM=width,first=first-start,count=len(mesh.faces)-first))
        count=len(mesh.faces)-start
        if count:
            objects.append(dict(id='street:'+r['sourceRecordId'],sourceRecordId=r['sourceRecordId'],source=r['source'],layer='Fence',
                sourceCoordinates=r['coordinatesMSK'],type=code,classification=spec,heightM=spec['heightM'],heightStatus='display-default',
                spacingM=spec['spacingM'],phaseM=phase,trianglesBeforeClipping=count,unsupportedGroundM=unbound,
                geometryRange=dict(first=start,count=count),groundProfile=contacts,uprights=uprights))
            account.append(dict(sourceRecordId=r['sourceRecordId'],status='placed',count=1))
            if code in TYPES and not any(w['key']==f'fence:{code}' for w in witness) and contacts:
                c=max(contacts,key=lambda c:np.linalg.norm(np.array(c['b'])-c['a']));a,b=np.array(c['a']),np.array(c['b']);q=(a+b)/2;d=b-a
                n=np.array([-d[1],d[0]])/np.linalg.norm(d);eye=n+.35*d/np.linalg.norm(d)
                witness.append(dict(label='Ограждение · '+spec['label'].lower(),key=f'fence:{code}',camera=dict(yaw=math.atan2(eye[0],eye[1]),pitch=.65,distance=18,target=[q[0],sum(c['heights'])/2+spec['heightM']/2,q[1]])))
        else:account.append(dict(sourceRecordId=r['sourceRecordId'],status='deferred',reason='no containing ground for source line'))
    stats=dict(records=len(fence_records),placed=len(objects),
        byType=dict(Counter(str(o['type']) for o in objects)),triangles=len(mesh.faces),unsupportedGroundM=sum(o['unsupportedGroundM'] for o in objects))
    return mesh,objects,account,witness,stats
