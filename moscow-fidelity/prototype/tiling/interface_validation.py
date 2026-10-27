"""Check free passage volumes derived from source interfaces, not generated mouths."""
import numpy as np
import shapely as sh
from shapely.geometry import shape
from shapely.ops import substring
from seam_validation import packing_error_bound,SOURCE_POSITION_TOLERANCE,MAX_SERIALIZED_POSITION_TOLERANCE

BARRIERS={'land','curb_top','curb_bottom','curb_front','curb_back',
          'green_curb_top','green_curb_side','pedestrian_path','railway_apron',
          'overpass_shoulder','overpass_riser','overpass_side','overpass_bottom',
          'parapet_top','parapet_side','inferred-walls','tunnel_wall_top','tunnel_wall_bottom','tunnel_wall_side',
          'portal_guard_top','portal_guard_bottom','portal_guard_side'}

def parts(g,kind='LineString'):
    if g.is_empty:return []
    if g.geom_type==kind:return [g]
    return [p for sub in getattr(g,'geoms',[]) for p in parts(sub,kind)]


def passage_volumes(city):
    """Local X/Y-up/Z half spaces: n.dot(position)+d >= 0.

    Use the source interface inventory even if a constructed connection was
    omitted. The narrow witness is inset from real side rails and extends from
    2 cm to 75 cm above the connected road, so roofs at other levels are not
    incorrectly treated as obstructions. Each terrain cell supplies its plane.
    """
    surfaces=[s for s in city['surfaces'] if s['kind'].startswith('roadbed')]
    polygons=[shape(s['geometry']) for s in surfaces];tree=sh.STRtree(polygons)
    ox,oy,oz=city['originMSK'];result=[]
    for interface in city['roadInterfaces']:
        line=shape(interface['mouthGeometry']);line=substring(line,.05,line.length-.05)
        end=interface['ends'][0];volumes=[]
        for i in tree.query(line.buffer(.00005),predicate='intersects'):
            surface=surfaces[int(i)]
            if surface['kind']!=end['kind'] or surface['tiers']!=end['level']:continue
            if end.get('parents') and surface.get('owner') not in end['parents']:continue
            a,b,c=surface['heightPlane'];height=np.array([a,-b,a*ox+b*oy+c-oz+interface.get('surfaceOffsetM',0.)])
            common=sh.intersection(line,polygons[int(i)],grid_size=.00001)
            for piece in parts(common):
                xy=np.asarray(piece.coords)
                local=(xy-np.array([ox,oy]))*np.array([1,-1])
                for aa,bb in zip(local,local[1:]):
                    length=np.linalg.norm(bb-aa)
                    if length<.00005:continue
                    tangent=(bb-aa)/length;normal=np.array([-tangent[1],tangent[0]])
                    middle=(aa+bb)/2
                    planes=[]
                    for direction,origin in [(tangent,aa),(-tangent,bb),(normal,middle-normal*.001),(-normal,middle+normal*.001)]:
                        planes.append([direction[0],0,direction[1],-np.dot(direction,origin)])
                    planes.extend([[-height[0],1,-height[1],-height[2]-.02],
                                   [height[0],-1,height[1],height[2]+.75]])
                    volumes.append((sh.LineString([aa,bb]).buffer(.001,cap_style='flat'),np.array(planes)))
        if not volumes:raise AssertionError(f"No road height witness for {interface['id']}")
        result.append((interface,volumes))
    return result


def clipped_polygon(triangle,planes):
    polygon=np.asarray(triangle)
    for plane in planes:
        if len(polygon)<3:return np.empty((0,3))
        out=[];prev=polygon[-1];dp=float(prev@plane[:3]+plane[3])
        for cur in polygon:
            dc=float(cur@plane[:3]+plane[3])
            if (dc>=0)!=(dp>=0):out.append(prev+(cur-prev)*(dp/(dp-dc)))
            if dc>=0:out.append(cur)
            prev,dp=cur,dc
        polygon=np.asarray(out)
    return polygon


def clipped_area(triangle,planes):
    polygon=clipped_polygon(triangle,planes)
    if len(polygon)<3:return 0.
    return float(np.linalg.norm(np.cross(polygon[1:-1]-polygon[0],polygon[2:]-polygon[0]),axis=1).sum()/2)


def contact_core(cells,contacts,tolerance):
    """Resolve contacts against the *union* of the witness cells.

    Roundoff at an external gate corner must not include a neighbouring wall.
    Eroding each cell separately would instead create blind internal seams.
    Horizontal remnants are merged before their width test, so tessellation
    cannot make a real barrier disappear. Vertical faces keep the area test.
    """
    core=sh.union_all([gate for gate,_ in cells]).buffer(-tolerance)
    horizontal={};vertical=[];blocked={}
    for name,triangle,polygon in contacts:
        normal=np.cross(triangle[1]-triangle[0],triangle[2]-triangle[0])
        length=np.linalg.norm(normal)
        if length==0:continue
        if abs(normal[1])>=length*.5:
            horizontal.setdefault(name,[]).append(sh.Polygon(polygon[:,[0,2]]).intersection(core))
        else:vertical.append((name,polygon))
    for name,polys in horizontal.items():
        # At this orientation 3D area is at most twice projected area.
        area=2*sh.union_all(polys).buffer(-tolerance).area
        if area>1e-10:blocked[name]=area
    if vertical and not core.is_empty:
        from build import triangulate
        gates=[]
        for triangle in triangulate(core,np.zeros(3)):
            xy=triangle[:,:2];centre=xy.mean(0);planes=[]
            for a,b in zip(xy,np.roll(xy,-1,axis=0)):
                n=np.array([-(b-a)[1],(b-a)[0]]);n/=np.linalg.norm(n)
                if (centre-a)@n<0:n=-n
                planes.append([n[0],0,n[1],-n@a])
            gates.append((sh.Polygon(xy),np.asarray(planes)))
        tree=sh.STRtree([g for g,_ in gates])
        for name,polygon in vertical:
            xy=polygon[:,[0,2]];box=sh.box(*(xy.min(0)-1e-8),*(xy.max(0)+1e-8))
            for index in tree.query(box,predicate='intersects'):
                area=clipped_area(polygon,gates[int(index)][1])
                if area>1e-10:blocked[name]=blocked.get(name,0.)+area
    if vertical and sum(blocked.values())<.00001:
        # A real cap can lie exactly on an approach-volume end plane. Keep
        # that inclusive boundary test: only sub-millimetre corner contacts
        # may be resolved by the uncertainty band, never a spanning wall.
        # Connect fragments across material and triangulation boundaries.
        hulls=[sh.MultiPoint(p[:,[0,2]]).convex_hull for _,p in vertical]
        tree=sh.STRtree(hulls);parent=list(range(len(hulls)))
        def root(i):
            while parent[i]!=i:parent[i]=parent[parent[i]];i=parent[i]
            return i
        for i,hull in enumerate(hulls):
            for j in tree.query(hull.buffer(1e-8),predicate='intersects'):
                a,b=root(i),root(int(j))
                if a!=b:parent[b]=a
        components={}
        for i in range(len(hulls)):components.setdefault(root(i),[]).append(i)
        for ids in components.values():
            xy=np.concatenate([vertical[i][1][:,[0,2]] for i in ids])
            if np.linalg.norm(np.ptp(xy,axis=0))<MAX_SERIALIZED_POSITION_TOLERANCE:continue
            for i in ids:
                name,p=vertical[i]
                area=float(np.linalg.norm(np.cross(p[1:-1]-p[0],p[2:]-p[0]),axis=1).sum()/2)
                blocked[name]=blocked.get(name,0.)+area
    return blocked


def check_interfaces(volumes,meshes):
    faces=[];names=[];boxes=[]
    witness_tree=sh.STRtree([gate for _,cells in volumes for gate,_ in cells])
    for name,triangles in meshes:
        if name not in BARRIERS:continue
        triangles=np.asarray(triangles)
        if not len(triangles):continue
        xy=triangles[:,:,[0,2]];lo=xy.min(axis=1);hi=xy.max(axis=1)
        bounds=sh.box(lo[:,0]-.000001,lo[:,1]-.000001,hi[:,0]+.000001,hi[:,1]+.000001)
        # Conservative bounding-box query, before allocating per-face Python
        # objects for an entire city. The exact gate test below is unchanged.
        selected=np.unique(witness_tree.query(bounds)[0])
        for index in selected:
            t=triangles[index]
            faces.append(t);names.append(name)
            # Pad zero-width projections of vertical faces for the spatial index.
            boxes.append(bounds[index])
    faces=np.asarray(faces);tree=sh.STRtree(boxes)
    checks=[]
    for interface,cells in volumes:
        blocked={};contacts=[]
        format_error=max((float(packing_error_bound(np.asarray(g.bounds).reshape(2,2))) for g,_ in cells),default=0.)
        for gate,planes in cells:
            for index in tree.query(gate,predicate='intersects'):
                i=int(index);area=clipped_area(faces[i],planes)
                if area>1e-10:
                    blocked[names[i]]=blocked.get(names[i],0.)+area
                    contacts.append((names[i],faces[i],clipped_polygon(faces[i],planes)))
                    format_error=max(format_error,float(packing_error_bound(faces[i])))
        tolerance=SOURCE_POSITION_TOLERANCE+format_error
        precision_passed=tolerance<=MAX_SERIALIZED_POSITION_TOLERANCE
        resolved=contact_core(cells,contacts,tolerance) if sum(blocked.values())>=.00001 else blocked
        checks.append(dict(interface=interface['id'],kinds=[e['kind'] for e in interface['ends']],
                           widthM=interface['mouthWidthM'],heightCells=len(cells),
                           blockingFaceAreaM2=sum(blocked.values()),blockingKinds=blocked,
                           resolvedBlockingFaceAreaM2=sum(resolved.values()),resolvedBlockingKinds=resolved,
                           positionToleranceM=tolerance,precisionPassed=precision_passed,
                           passed=bool(precision_passed and sum(resolved.values())<.00001)))
    return dict(passed=all(c['passed'] for c in checks),interfaces=len(checks),checks=checks,
                heightRangeAboveRoadM=[.02,.75],halfWidthM=.001,areaToleranceM2=.00001,
                maxAllowedPositionToleranceM=MAX_SERIALIZED_POSITION_TOLERANCE,
                precisionPolicy='Measured Float32 rounding bound plus 50 micrometres; external gate boundary only, merged horizontal remnant width, strict vertical face area; reject precision worse than 1 mm.',
                scope='actual serialized concrete/land faces inside free passages at every source road interface')
