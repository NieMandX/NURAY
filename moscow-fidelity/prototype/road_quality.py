"""Measure road continuity and geometry changes independently of the height fitter."""
import json
from pathlib import Path
import numpy as np
import shapely as sh
from shapely.geometry import shape, Polygon

BASE=Path(__file__).resolve().parents[1]/'web-preview/prototype/assets'

def areal_geometry(g):
    if g.geom_type in ('Polygon','MultiPolygon'):return g
    return sh.union_all([areal_geometry(part) for part in getattr(g,'geoms',[]) if not part.is_empty]) if g.geom_type=='GeometryCollection' else Polygon()

def quality(surfaces, protected=None):
    rows=[s for s in surfaces if s['kind']=='roadbed_flat']
    cells=[(areal_geometry(shape(s['geometry']) if 'geometry' in s else s['poly']),
            s['heightPlane'] if 'heightPlane' in s else s['plane']) for s in rows]
    cells=[(g,c) for g,c in cells if not g.is_empty]
    polygons=[g for g,c in cells];planes=np.array([c for g,c in cells])
    tree=sh.STRtree(polygons)
    jumps=[];angles=[];count=0;length=0.
    for i,p in enumerate(polygons):
        for j in tree.query(p,predicate='intersects'):
            if j<=i: continue
            edge=p.boundary.intersection(polygons[j].boundary)
            pieces=[edge] if edge.geom_type=='LineString' else list(getattr(edge,'geoms',[]))
            for line in pieces:
                if line.geom_type!='LineString' or line.length<.05: continue
                xy=np.asarray(line.coords);c=planes[i]-planes[j]
                jumps.append(float(np.max(np.abs(xy@c[:2]+c[2]))))
                a=np.r_[-planes[i,:2],1.];b=np.r_[-planes[j,:2],1.]
                cosine=np.dot(a,b)/np.linalg.norm(a)/np.linalg.norm(b)
                angles.append(float(np.degrees(np.arccos(np.clip(cosine,-1,1)))))
                count+=1;length+=line.length
    slopes=np.linalg.norm(planes[:,:2],axis=1)*100
    # Cells share the canonical 10 micrometre overlay grid. Mixing precise
    # terrain intersections and snapped source vertices without specifying
    # that grid can manufacture holes in GEOS's union itself.
    footprint=sh.union_all(polygons,grid_size=.00001)
    holes=[];islands=[];numeric=[]
    for p in ([footprint] if footprint.geom_type=='Polygon' else footprint.geoms):
        for ring in p.interiors:
            hole=Polygon(ring)
            if 1e-4<hole.area<1 and hole.buffer(-.025).is_empty:
                if hole.buffer(-.00005).is_empty:
                    numeric.append(dict(areaM2=hole.area,bounds=list(hole.bounds),positionToleranceM=.00005))
                    continue
                remainder=hole.difference(protected) if protected is not None else hole
                explicit=protected is not None and hole.intersection(protected).area>0 and remainder.buffer(-.00005).is_empty
                item=dict(areaM2=hole.area,bounds=list(hole.bounds))
                if explicit:item.update(unprotectedFringeM2=remainder.area,positionToleranceM=.00005)
                (islands if explicit else holes).append(item)
    return dict(roadCells=len(polygons),sharedEdgeSegments=count,sharedEdgeLengthM=length,
        maxHeightDiscontinuityM=max(jumps,default=0),
        maxFaceAngleDeg=max(angles,default=0),p95FaceAngleDeg=float(np.percentile(angles,95)) if angles else 0,
        maxGradePercent=float(np.max(slopes)),p95GradePercent=float(np.percentile(slopes,95)),
        thinEnclosedSlits=holes,protectedThinIslands=islands,numericOverlaySlivers=numeric)


def compare(surfaces, protected=None, reference=None):
    if reference is None:
        old=json.loads((BASE/'urban-model-terrain.json').read_text())
        reference=old['surfaces']
    previous=quality(reference);current=quality(surfaces,protected)
    return dict(previous=previous,current=current,
        passed=bool(current['maxHeightDiscontinuityM']<.001 and not current['thinEnclosedSlits']
                    and current['maxFaceAngleDeg']<max(.01,previous['maxFaceAngleDeg']*.5)),
        heightToleranceM=.001,
        note='Geometric continuity and relative reduction of bending; grades are map-derived reconstruction, not road engineering verification.')


if __name__=='__main__':
    city=json.loads((BASE/'urban-model.json').read_text())
    result=compare(city['surfaces'])
    (BASE/'road-quality.json').write_text(json.dumps(result,indent=2))
    print(json.dumps(result,indent=2));assert result['passed'],result
