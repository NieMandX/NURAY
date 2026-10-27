"""Retained 2GIS detailed-road style adapters, with explicit provenance.

Map display colours are not measured PBR albedos. The above-ground pedestrian
display white is mapped to a light, non-emissive .72 albedo, below road paint.
Underpasses use the beige pedestrian-paving rule in semantics.py.
This deliberately supports a small audited subset, not the entire style DSL.
"""
import hashlib,json,math
import numpy as np
from shapely.geometry import LineString

PEDESTRIAN_LAYER='Roadbed_overpasses'
PEDESTRIAN_MATERIAL=11
MARKING_RULES={'LinearMarking_Stop':'LinearMarking_Stop_15',
               'LinearMarking_TramStop':'LinearMarking_TramStop_17'}

def check_marking_support(centreline,support,extent,record,precision):
    # Two independently quantized XY features can differ by one grid diagonal.
    # Keep the source curve and clip paint to the actual road; only distinguish
    # source rounding from a wrong-side tooth in the diagnostic acceptance test.
    quantum=record.get('source',{}).get('coordinateStepM',0.)
    tolerance=max(precision*10,math.sqrt(2)*quantum)
    line=centreline.intersection(extent)
    outside=line.difference(support.buffer(precision*10)).length
    unsupported=line.difference(support.buffer(tolerance)).length
    return dict(centrelineOutsideRoadM=outside,sourceCoordinateStepM=quantum,
                sourcePositionToleranceM=tolerance,centrelineBeyondSourcePrecisionM=unsupported,
                passed=bool(unsupported<.001))

def load(path):
    raw=path.read_bytes();rules={str(r['id']):r for r in json.loads(raw)}
    selected={k:rules[k] for k in ['241413','609252','715927','13970','77780','Roadbed_1','881318','738945',*MARKING_RULES.values()]}
    assert PEDESTRIAN_LAYER in json.dumps(selected['241413']['filter'])
    assert selected['241413']['style']['color'][-1]=='#F5F5F5'
    for layer,rid in MARKING_RULES.items():
        assert layer in json.dumps(selected[rid]['filter'])
        assert selected[rid]['style']['geometryModifier'][1][0]=='line-to-zigzag'
    return dict(fileSha256=hashlib.sha256(raw).hexdigest(),rules=selected,
                context='immersive roads; non-metro floor; unhovered; detailed zoom >= 17.1',
                pedestrianPbrAlbedo=[.72,.72,.72],colourPolicy='source display white mapped to light non-emissive PBR; white/yellow paint remain brighter')

def pedestrian_profile(style):
    s=style['rules']['609252']['style']
    return dict(overhang=s['borderWidth'],depth=s['thickness'],shoulderRaise=0.,
                parapetHeight=s['borderHeight'],parapetWidth=s['borderWidth'],material=PEDESTRIAN_MATERIAL,
                styleId='609252',evidence='2GIS pedestrian style dimensions; border placed outside retained walking polygon')

def zigzag(xy,step,width,stop_lines=False,begin_cut=False,end_cut=False):
    """Metre-coordinate port of 2GIS Lo/line-to-zigzag (one-sided teeth).

    Fit whole teeth to each retained source feature, before region/tile cuts.
    Preserve direction: reversing the source flips which side receives teeth.
    """
    xy=np.asarray(xy,dtype=float)
    if xy.ndim!=2 or len(xy)<2:return LineString()
    xy=xy[:,:2]
    xy=xy[np.r_[True,np.linalg.norm(np.diff(xy,axis=0),axis=1)>1e-9]]
    if len(xy)<2 or step<=0 or width==0:return LineString()
    lengths=np.linalg.norm(np.diff(xy,axis=0),axis=1);dist=np.r_[0,np.cumsum(lengths)]
    count=math.floor(dist[-1]/step)
    if not count:return LineString()  # Original produces no usable segment here.
    fitted=dist[-1]/count;pos=0.;i=0;y=xy[0].copy();out=[y.copy()]
    sign=(1 if stop_lines else -1)*np.sign(width)
    if stop_lines and not begin_cut:
        tangent=(xy[1]-xy[0])/lengths[0];normal=np.array([-tangent[1],tangent[0]])
        y=y+normal*sign*width;out.append(y.copy());pos+=fitted/2;sign=-sign
    while pos<=dist[-1]+1e-9:
        while i<len(lengths)-1 and pos>dist[i+1]:i+=1
        tangent=(xy[i+1]-xy[i])/lengths[i];normal=np.array([-tangent[1],tangent[0]])
        if sign>0:y=y+normal*sign*width+tangent*fitted/2
        else:y=xy[i]+(xy[i+1]-xy[i])*min(1.,(pos-dist[i])/lengths[i])
        if np.linalg.norm(y-out[-1])>1e-9:out.append(y.copy())
        sign=-sign;pos+=fitted/2
    if stop_lines and not end_cut:
        y=y+normal*sign*width
        if np.linalg.norm(y-out[-1])>1e-9:out.append(y.copy())
    return LineString(out) if len(out)>1 else LineString()

def marking_geometry(record,style):
    rid=MARKING_RULES[record['layer']];s=style['rules'][rid]['style'];modifier=s['geometryModifier'][1]
    assert s['width'][0]=='meters-to-pixels'
    p=record['properties']
    line=zigzag(record['coordinates'],*modifier[1:],bool(p.get('beginningIsCut')),bool(p.get('endingIsCut')))
    # Round end caps are explicit in the source style. Sharp joins retain teeth.
    return line.buffer(s['width'][1]/2,cap_style='round',join_style='mitre'),dict(
        source=record['id'],styleId=rid,modifier=modifier,widthM=s['width'][1],
        centerline=list(line.coords),sourceFeatureBeforeClipping=True)
