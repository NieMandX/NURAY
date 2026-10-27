"""Source-backed street placement. No icon-to-object inference or traffic data.

The provider supplies positions and, sometimes, orientation/type. Display-model
dimensions are defaults, not measurements. Height is sampled from final meshes.
"""
import gzip, math
from pathlib import Path
import numpy as np
import shapely as sh

MODELS = frozenset('lamppost1 lamppost2 lamppost3 lamppost4 bench1 bench2 busstation porch swing2 swing3 slide2 tabletennis workout gyms fountain1_a fountain2_a fontain1_3_a pavilion1 footballgate1 barrier boom swing trampoline'.split())
ALIASES={'objectClass':'db_object_class','sublayer':'db_sublayer','class':'db_class'}
GLOBALS={'immersiveRoadsOn':True,'_activeFloorIsMetro':False}
GROUND_NAMES={'land','roadbed_flat','pedestrian_path','railway_apron','curb_top','green_curb_top'}

def evaluate(e,p):
    if not isinstance(e,list):return e
    if not e:return []
    op=e[0]
    if not isinstance(op,str):return [evaluate(x,p) for x in e]
    if op=='get':
        k=e[1];alias=ALIASES.get(k,'db_'+k)
        return p.get(alias,p.get(k)) if not k.startswith('db_') else p.get(k)
    if op=='global':return GLOBALS[e[1]]
    if op=='zoom':return 20
    if op=='literal':return [evaluate(x,p) for x in e[1]] if isinstance(e[1],list) else e[1]
    if op=='all':return all(evaluate(x,p) for x in e[1:])
    if op=='any':return any(evaluate(x,p) for x in e[1:])
    if op=='!':return not evaluate(e[1],p)
    if op=='match':
        v=evaluate(e[1],p)
        for j in range(2,len(e)-1,2):
            if v in (e[j] if isinstance(e[j],list) else [e[j]]):return evaluate(e[j+1],p)
        return evaluate(e[-1],p)
    if op=='coalesce':
        for x in e[1:]:
            v=evaluate(x,p)
            if v is not None:return v
        return None
    if op in ('==','!=','>','>=','<','<='):
        a,b=evaluate(e[1],p),evaluate(e[2],p)
        if op=='==':return a==b
        if op=='!=':return a!=b
        if a is None or b is None:return False
        return {'>':lambda:a>b,'>=':lambda:a>=b,'<':lambda:a<b,'<=':lambda:a<=b}[op]()
    if op in ('+','-','*','/'):
        a=[evaluate(x,p) for x in e[1:]]
        if any(x is None for x in a):raise ValueError('Missing arithmetic attribute')
        if op=='+':return sum(a)
        if op=='*':return math.prod(a)
        if op=='-':return -a[0] if len(a)==1 else a[0]-a[1]
        return a[0]/a[1]
    raise ValueError('Unsupported source expression: '+str(op))

def model_rule(record,rules):
    if record['layer']=='Traffic_light':return None
    matches=[]
    for r in rules:
        s=r.get('style',{})
        if r.get('type')!='model' or s.get('visibility','visible')!='visible':continue
        if not isinstance(s.get('modelSrc'),str) or s['modelSrc'] not in MODELS:continue
        if evaluate(r.get('filter',True),record['properties']):matches.append(r)
    if len(matches)>1:raise ValueError(('Ambiguous model rules',record['sourceRecordId'],[r['id'] for r in matches]))
    return matches[0] if matches else None

def transform(rotation,scale,position):
    # Source rotation uses Z-up. GLB / renderer are Y-up; X,Y,Z scale -> X,Z,Y.
    assert abs(rotation[0])+abs(rotation[1])<1e-8
    a=math.radians(rotation[2]);c,s=math.cos(a),math.sin(a)
    linear=np.array([[c,0,s],[0,1,0],[-s,0,c]])@np.diag([scale[0],scale[2],scale[1]])
    return np.column_stack((linear,position)).ravel().tolist()

def owner(x,y,bounds,size):
    a,b,c,d=bounds
    if not(a<=x<c and b<=y<d):return None
    return f'{int((x-a)//size)}-{int((y-b)//size)}'

class SurfaceSampler:
    """Sample final, serialized geometry, excluding buildings and bridge tops.

    Strict containment, no nearest-triangle height extrapolation. Ground and deck
    surfaces have independent indexes so overlapping transport levels stay apart.
    """
    def __init__(self,root,manifest,names):
        tris=[];refs=[]
        for c in manifest['chunks']:
            if c['name'] not in names:continue
            raw=gzip.decompress((root/'canonical/full'/Path(c['file']).name).read_bytes())
            v=np.frombuffer(raw[:c['vertexBytes']],'<f4').reshape(-1,8)[:,:3].astype(float)
            ix=np.frombuffer(raw[c['vertexBytes']:],'<u4').reshape(-1,3)
            t=v[ix];xz=t[:,:,[0,2]];a=xz[:,1]-xz[:,0];b=xz[:,2]-xz[:,0];area=np.abs(a[:,0]*b[:,1]-a[:,1]*b[:,0])
            ids=np.flatnonzero(area>1e-8);tris.extend(t[ids]);refs.extend((c['id'],int(i)) for i in ids)
        self.tris=np.asarray(tris);self.refs=refs
        self.polys=sh.polygons(self.tris[:,:,[0,2]]);self.tree=sh.STRtree(self.polys)
    def hits(self,x,z):
        ids=self.tree.query(sh.Point(x,z),predicate='covered_by');out=[]
        for i in ids:
            t=self.tris[i];a,b,c=t[:,[0,2]];uv=np.linalg.solve(np.column_stack((b-a,c-a)),np.array([x,z])-a)
            h=float(t[0,1]+uv[0]*(t[1,1]-t[0,1])+uv[1]*(t[2,1]-t[0,1]))
            out.append(dict(height=h,chunk=self.refs[i][0],triangle=self.refs[i][1]))
        return out
    def ground(self,x,z):
        hits=self.hits(x,z)
        return max(hits,key=lambda r:r['height']) if hits else None
    def deck_profile(self,x,z,anchor):
        hits=self.hits(x,z)
        if hits:return min(hits,key=lambda h:abs(h['height']-anchor['height']))
        # A source cap may slightly overhang the deck. Continue the selected
        # deck plane for that cap only; never extrapolate ground placement.
        i=self.refs.index((anchor['chunk'],anchor['triangle']));t=self.tris[i]
        a,b,c=t[:,[0,2]];uv=np.linalg.solve(np.column_stack((b-a,c-a)),np.array([x,z])-a)
        return dict(height=float(t[0,1]+uv[0]*(t[1,1]-t[0,1])+uv[1]*(t[2,1]-t[0,1])),
                    chunk=anchor['chunk'],triangle=anchor['triangle'],rule='cap-overhang-plane')

def station_points(coords,spacing,phase):
    """Stations in metres along the source component, before any tile clipping."""
    line=sh.LineString(coords);length=line.length
    start=(-phase)%spacing
    for s in np.arange(start,length+1e-8,spacing):
        p=line.interpolate(float(s));yield float(s),[p.x,p.y]

def clip_segment(a,b,bounds):
    line=sh.LineString([a,b]).intersection(sh.box(*bounds))
    if line.geom_type!='LineString' or line.length<.01:return None
    return np.asarray(line.coords)[[0,-1]].tolist()
