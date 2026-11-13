"""Extract survey evidence locally; never silently assign a CRS or height datum.

Input is JSON from GNU LibreDWG's dwgread -O JSON command. Ground marks use
the survey INSERT location, not its displaced TEXT label or roof elevations.
The result is an inspection artefact; it does not replace the city terrain.
"""
import argparse,collections,gzip,hashlib,json
from pathlib import Path
import numpy as np

def extract(document):
    objects=document['OBJECTS'];by_id={o['handle'][-1]:o for o in objects if 'handle' in o}
    layers={o['handle'][-1]:o['name'] for o in objects if o.get('object')=='LAYER'}
    result=dict(groundMarks=[],objectTopMarks=[],trees=[],contours=[],buildings=[],roadEdges=[])
    counts=collections.Counter()
    for o in objects:
        if o.get('entmode')!=2:continue # Model space only, not symbol definitions.
        kind=o.get('entity');layer=layers.get(o.get('layer',[0])[-1],'?');counts[(layer,kind)]+=1
        row=dict(handle=o['handle'][-1],layer=layer)
        if kind=='INSERT':
            row['point']=o['ins_pt']
            if layer=='Отметки_высот330':result['groundMarks'].append(row)
            elif layer=='Отметки_высоты_по_веррху_объект':result['objectTopMarks'].append(row)
            elif layer.startswith('Деревья'):result['trees'].append(row)
        points=[]
        if kind=='POLYLINE_3D':points=[by_id[r[-1]]['point'] for r in o.get('vertex',[]) if r[-1] in by_id]
        elif kind=='LINE':points=[o['start'],o['end']]
        elif kind=='LWPOLYLINE':points=[[a,b,o.get('elevation',0)] for a,b in o['points']]
        if len(points)<2:continue
        row['points']=points
        if layer.startswith('Горизонтали_'):result['contours'].append(row)
        elif layer.startswith(('Строения_нежилые','Строения_жилые','Здания_строения','Строения_культового')):result['buildings'].append(row)
        elif layer.startswith('Проезжие_части_улиц'):result['roadEdges'].append(row)
    a=np.array([r['point'] for r in result['groundMarks']]);unique,inv=np.unique(a[:,:2],axis=0,return_inverse=True)
    lo=np.full(len(unique),np.inf);hi=-lo.copy();np.minimum.at(lo,inv,a[:,2]);np.maximum.at(hi,inv,a[:,2])
    report=dict(counts={k:len(v) for k,v in result.items()},uniqueGroundXY=len(unique),repeatedGroundXY=len(a)-len(unique),
                inconsistentGroundXY=int(np.sum(hi-lo>.02)),groundBounds=np.array([a.min(0),a.max(0)]).tolist(),
                header={k:document['HEADER'].get(k) for k in ('INSUNITS','EXTMIN','EXTMAX','UCSORG','INSBASE')},
                embeddedGeoData=any(o.get('object')=='GEODATA' for o in objects),
                coordinateStatus='Unconfirmed; numeric coordinates retained without unit conversion',
                verticalStatus='Unconfirmed; ground INSERT elevations retained; object-top elevations excluded',
                appliedToScene=False)
    result['report']=report;result['modelSpaceLayers']=[dict(layer=l,entity=e,count=c) for (l,e),c in counts.most_common()]
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('json',type=Path);p.add_argument('output',type=Path);p.add_argument('--dwg',type=Path);a=p.parse_args()
    result=extract(json.loads(a.json.read_text()))
    if a.dwg:result['report']['source']=dict(name=a.dwg.name,sha256=hashlib.sha256(a.dwg.read_bytes()).hexdigest())
    a.output.mkdir(parents=True,exist_ok=True)
    (a.output/'survey-extract.json.gz').write_bytes(gzip.compress(json.dumps(result,ensure_ascii=False).encode(),mtime=0))
    (a.output/'survey-inventory.json').write_text(json.dumps(result['report'],ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(result['report'],ensure_ascii=False,indent=2))
