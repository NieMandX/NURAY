"""Role-aware tunnel headers, generated before any transport tile clipping.

Source tunnel_arch gives the XY portal location, NOT a floor height. Its Z=0
must never be extruded down to the floor. The 0.5 m fascia drop is an explicit
viewer construction default; wall width/upper guard come from source styles.
"""
import numpy as np
import shapely as sh
from shapely.geometry import Point, LineString, Polygon, mapping
from transitions import parts, union
from curbs import LAND_RAISE
from passage_space import stable_area

HEADER_DROP=.5
MIN_PORTAL_DEPTH=1.
PARALLEL_COS=.99

def parallel_to_source(line,source):
    """Match the local source segment, including bends and reversed contours."""
    xy=np.asarray(line.coords)[:,:2];a,b=xy[0],xy[-1];v=b-a
    length=np.linalg.norm(v)
    if length<1e-9:return False
    mid=Point((a+b)/2);coords=np.asarray(source.coords)[:,:2]
    segments=[(p,q) for p,q in zip(coords,coords[1:]) if np.linalg.norm(q-p)>1e-9]
    if not segments:return False
    p,q=min(segments,key=lambda pq:LineString(pq).distance(mid));s=q-p
    return bool(abs(np.dot(v,s))>=PARALLEL_COS*length*np.linalg.norm(s))

def build_headers(footprint,arches,side_band,floor,dem,demtree,groups,extent,
                  precision,width,guard,triangulate,z_at,plane,landings=None):
    matched=[];lines=[];skipped=[]
    def ground(xy):
        p=Point(xy);ids=demtree.query(p,predicate='covered_by')
        i=int(ids[0]) if len(ids) else int(demtree.nearest(p))
        return float(z_at(dem[i][1],xy))+LAND_RAISE
    boundary=footprint.boundary.difference(extent.boundary.buffer(precision*5))
    for r in arches:
        source=LineString(np.asarray(r['coordinates'])[:,:2])
        for piece in parts(boundary.intersection(source.buffer(.05,cap_style='flat')),'LineString'):
            for a,b in zip(piece.coords,list(piece.coords)[1:]):
                line=LineString([a,b])
                if line.length<precision*5 or not parallel_to_source(line,source):continue
                depths=[ground(xy)-floor(xy) for xy in [a,b,line.interpolate(.5,normalized=True).coords[0]]]
                if min(depths)<MIN_PORTAL_DEPTH:
                    skipped.append(dict(source=r['id'],reason='ground-level entry / insufficient portal clearance'));continue
                lines.append(line);matched.append(r['id'])
    # Merge all source fragments first: source/storage tile edges cannot grow
    # caps or reset header construction.
    portal=sh.line_merge(union(lines,precision));bands=[];openings=[]
    for line in parts(portal,'LineString'):
        xy=np.asarray(line.coords);v=xy[-1]-xy[0];length=np.linalg.norm(v)
        if length<precision*5:continue
        n=np.array([-v[1],v[0]])/length;mid=np.asarray(line.interpolate(.5,normalized=True).coords)[0]
        left=footprint.covers(Point(mid+n*.001));right=footprint.covers(Point(mid-n*.001))
        if left==right:raise ValueError('Portal has no unambiguous descent side')
        extended=xy.copy()
        extended[0]-=(xy[1]-xy[0])/np.linalg.norm(xy[1]-xy[0])*width
        extended[-1]+=(xy[-1]-xy[-2])/np.linalg.norm(xy[-1]-xy[-2])*width
        bands.append(LineString(extended).buffer((-1 if left else 1)*width,single_sided=True,join_style='mitre'))
        openings.append(mapping(line))
    band=union(bands,precision).difference(footprint).difference(side_band).intersection(extent)
    if landings is not None:band=band.difference(landings)
    # Boolean overlays can retain collapsed lines beside valid polygons. Only
    # the areal part defines a solid header; GeometryCollection has no boundary.
    band=stable_area(band,precision)
    cells=[];clearance=[]
    for di in demtree.query(band,predicate='intersects'):
        terrain=dem[int(di)][1]+[0,0,LAND_RAISE]
        for t in triangulate(band.intersection(dem[int(di)][0]),np.zeros(3)):
            xy=t[:,:2];land=z_at(terrain,xy)
            # The corners extend into land. There a global nearest-floor query
            # can jump to a neighbouring staircase's ground-level mouth. Take
            # clearance from this portal cross-section, not unrelated land.
            floor_z=[floor(np.asarray(sh.shortest_line(Point(p),portal).coords)[-1,:2]) for p in xy]
            depth=land-np.asarray(floor_z)
            # Keep >=80% of the actual opening depth free, even on a sloping
            # terrain cell. No extrusion ever reaches the passage floor.
            low=land-np.minimum(HEADER_DROP,np.maximum(0,depth)*.2);high=land+guard
            poly=Polygon(xy);bottom=plane(np.column_stack([xy,low]));top=terrain+[0,0,guard]
            cells.append(dict(poly=poly,top=top,bottom=bottom));clearance.extend(low-(land-depth))
            groups[('portal_guard_top',6)].extend(triangulate(poly,top))
            groups[('portal_guard_bottom',6)].extend(t[::-1] for t in triangulate(poly,bottom))
    tree=sh.STRtree([c['poly'] for c in cells]);emitted=[]
    for chain in parts(band.boundary.difference(extent.boundary.buffer(precision*5)),'LineString'):
        for a,b in zip(chain.coords,list(chain.coords)[1:]):
            edge=LineString([a,b]);stops=[0.,edge.length]
            if edge.length<precision:continue
            for i in tree.query(edge.buffer(precision*3),predicate='intersects'):
                for part in parts(edge.intersection(cells[int(i)]['poly'].buffer(precision*3)),'LineString'):
                    stops.extend(edge.project(Point(p)) for p in [part.coords[0],part.coords[-1]])
            stops=sorted(set(stops))
            for lo,hi in zip(stops,stops[1:]):
                if hi-lo<precision/10:continue
                aa=np.asarray(edge.interpolate(lo).coords)[0];bb=np.asarray(edge.interpolate(hi).coords)[0]
                cell=cells[int(tree.nearest(edge.interpolate((lo+hi)/2)))]
                low=z_at(cell['bottom'],[aa,bb]);high=z_at(cell['top'],[aa,bb])
                v=np.array([[*aa,low[0]],[*bb,low[1]],[*bb,high[1]],[*aa,high[0]]])
                faces=[v[[0,1,2]],v[[0,2,3]]]
                groups[('portal_guard_side',6)].extend(faces+[f[::-1] for f in faces]);emitted.append(LineString([aa,bb]))
    from coverage import uncovered_length
    gap=uncovered_length(band.boundary.difference(extent.boundary.buffer(precision*5)),union(emitted,precision),precision*5)
    covered=union([c['poly'] for c in cells],precision)
    missing=band.difference(covered.buffer(precision*5)).area
    return dict(passed=bool(gap<.001 and missing<.0001 and (not clearance or min(clearance)>.75)),
                count=len(openings),sourceIds=sorted(set(matched)),openings=openings,
                bandGeometry=mapping(band),dropBelowLandM=HEADER_DROP,minPassageHeightM=float(min(clearance)) if clearance else None,
                uncoveredSidesM=gap,uncoveredTopM2=missing,skipped=skipped,
                evidence='source tunnel_arch plus actual descent depth; upper guard follows raised terrain, fascia <=0.5 m below land and <=20% of opening depth; ground entry stays open')
