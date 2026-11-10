"""Open pedestrian bridge mouths at confirmed same-level walking connections."""
import numpy as np
import shapely as sh
from shapely.geometry import Point,LineString,Polygon,mapping
from transitions import parts,union,ENTRY_HEIGHT_TOLERANCE
from curbs import LAND_RAISE
from passage_space import ground_approach,APPROACH_LENGTH

MOUTH_NODE_ALIGNMENT=.15


class SourceWalkingAreas:
    """Resolve exposed source paving with the normal land-cover priorities."""
    def __init__(self,records,precision):
        from semantics import classify
        self.precision=precision;self.rows=[];boxes=[];self.polygons={}
        for f in records:
            if f['geometryType']!='polygon':continue
            sem=f.get('semantics') or classify(f['layer'],f['properties'],f['geometryType'])
            if sem.get('kind')!='land' or sem.get('status')!='built' or (f['properties'].get('db_tiers') or [0])!=[0]:continue
            xy=np.asarray(f['coordinates'])[:,:2]
            self.rows.append((f,sem));boxes.append(sh.box(*xy.min(0),*xy.max(0)))
        self.tree=sh.STRtree(boxes)

    def peers(self,probe):
        if probe.area<.01:return []
        selected=[]
        for index in self.tree.query(probe):
            i=int(index);f,sem=self.rows[i]
            if i not in self.polygons:
                xy=np.asarray(f['coordinates'])[:,:2]
                self.polygons[i]=union([Polygon(xy[j:j+3]) for j in range(len(xy)-2)
                                       if Polygon(xy[j:j+3]).area>1e-9],self.precision)
            p=self.polygons[i]
            if p.intersects(probe):selected.append((f,sem,p))
        remaining=probe;peers=[]
        for f,sem,p in sorted(selected,key=lambda row:(-row[1]['rank'],row[2].area,row[0]['id'])):
            piece=remaining.intersection(p)
            if piece.area<=1e-9:continue
            if sem.get('purpose')!='pedestrian':return []
            peers.append(f['id']);remaining=remaining.difference(p)
        return peers if remaining.area<1e-8 else []

def discover(candidates,records,ground_road,extent,precision,z_at,include_mixed_ground=False):
    elevated=[r for r in candidates if r.get('transport')=='pedestrian' and r['part'] in ['roadbed_overpass','roadbed_tunnel_descent']]
    # A descending pedestrian axis may still be named Pedestrian_road. Its
    # tier/end levels, not that name or a source-fragment cut flag, establish
    # the connection. A walking path can join a landing sideways; unlike a
    # railway, its tangent need not continue straight across the mouth.
    axes=[r for r in records if r['layer'].startswith('Pedestrian_road')
          and r['geometryType']=='polyline' and len(r['coordinates'])>1]
    ground_ends=[];axis_ends={};by_axis={r['id']:r for r in axes}
    for r in axes:
        p=r['properties']
        for index,key in [(0,'db_segment_level_begin'),(-1,'db_segment_level_end')]:
            if p.get(key,p.get(key.replace('level_begin','begin_level').replace('level_end','end_level'),p.get('db_segment_level')))!=0:continue
            point=Point(r['coordinates'][index][:2]);tiers=tuple(p.get('db_tiers') or [0])
            axis_ends.setdefault(tiers,[]).append((point,r['id']))
            if include_mixed_ground or tiers==(0,):ground_ends.append((point,r['id']))
        # A source path can carry a junction at an internal vertex. Only a
        # path explicitly at ground level throughout supplies such nodes;
        # an arbitrary XY crossing or an unknown-height intermediate point
        # is not evidence of a walking connection.
        if tuple(p.get('db_tiers') or [0])==(0,) and p.get('db_segment_level')==0:
            levels=[p.get('db_segment_level_'+end,p.get('db_segment_'+end+'_level',p.get('db_segment_level'))) for end in ('begin','end')]
            if levels==[0,0]:
                ground_ends.extend((Point(xy[:2]),r['id']) for xy in r['coordinates'][1:-1])
    ground_tree=sh.STRtree([p for p,rid in ground_ends])
    axis_trees={level:sh.STRtree([p for p,rid in rows]) for level,rows in axis_ends.items()}
    connections=[];interfaces=[];walking_areas=None
    for kind,level in sorted({(r['part'],tuple(r['tiers'])) for r in elevated}):
        rows=[r for r in elevated if tuple(r['tiers'])==level and r['part']==kind]
        footprint=union([r['poly'] for r in rows],precision);edges=[]
        for r in rows:
            for poly,c in r['patches']:
                for line in parts(footprint.boundary.intersection(poly.buffer(precision*2)),'LineString'):
                    for a,b in zip(line.coords,list(line.coords)[1:]):
                        if np.linalg.norm(np.asarray(b)-a)<.05 or np.max(abs(z_at(c,[a,b])))>ENTRY_HEIGHT_TOLERANCE:continue
                        edges.extend(parts(LineString([a,b]).difference(extent.boundary.buffer(precision*5)),'LineString'))
        merged=sh.line_merge(union(edges,precision)) if edges else LineString()
        for line in parts(merged,'LineString'):
            if line.length<.25:continue
            peers=set();axis_parents=set()
            # Index source endpoints instead of scanning every city path for
            # each mouth. Rectangular broad phases retain every candidate;
            # the original exact distance, tier and identity tests decide.
            tree=axis_trees.get(level)
            x0,y0,x1,y1=line.bounds
            nearby=[] if tree is None else tree.query(sh.box(x0-MOUTH_NODE_ALIGNMENT,y0-MOUTH_NODE_ALIGNMENT,x1+MOUTH_NODE_ALIGNMENT,y1+MOUTH_NODE_ALIGNMENT))
            for i in nearby:
                point,owner=axis_ends[level][int(i)]
                distance=point.distance(line)
                if distance>MOUTH_NODE_ALIGNMENT:continue
                if distance>.05:
                    # The routing node and visual mouth can differ by a few
                    # centimetres. Retain exact peer-node/level agreement and
                    # require the structural route to continue inside its own
                    # source floor before accepting this bounded alignment.
                    xy=np.asarray(by_axis[owner]['coordinates'])[:,:2]
                    if np.linalg.norm(xy[-1]-np.asarray(point.coords[0]))<np.linalg.norm(xy[0]-np.asarray(point.coords[0])):xy=xy[::-1]
                    route=LineString(xy)
                    if not footprint.covers(route.interpolate(min(1.,route.length/2))):continue
                same=[]
                for j in ground_tree.query(sh.box(point.x-.02,point.y-.02,point.x+.02,point.y+.02)):
                    q,rid=ground_ends[int(j)]
                    if q.distance(point)<.02 and (not include_mixed_ground or rid!=owner):same.append(rid)
                if not same:
                    # Some entrances terminate directly in a mapped plaza,
                    # without a second route polyline. Require the explicit
                    # level-zero structural endpoint, its inward continuation,
                    # and actual exposed pedestrian paving on the other side.
                    xy=np.asarray(by_axis[owner]['coordinates'])[:,:2]
                    if np.linalg.norm(xy[-1]-np.asarray(point.coords[0]))<np.linalg.norm(xy[0]-np.asarray(point.coords[0])):xy=xy[::-1]
                    route=LineString(xy)
                    if footprint.covers(route.interpolate(min(1.,route.length/2))):
                        if walking_areas is None:walking_areas=SourceWalkingAreas(records,precision)
                        probe=ground_approach(line,footprint,precision).intersection(point.buffer(.25))
                        same=walking_areas.peers(probe)
                if same:peers.update(same);axis_parents.add(owner)
            if not peers:continue  # A coincident XY crossing is not a connection.
            # The outward strip must actually meet non-road ground.
            strip=line.buffer(.05,cap_style='flat').difference(footprint)
            if strip.is_empty or (not include_mixed_ground and strip.intersection(ground_road).area>precision):continue
            ids=[r['id'] for r in rows if r['poly'].distance(line)<precision*5]
            iid=f'pedestrian-interface:{len(interfaces)}'
            landing=ground_approach(line,footprint,precision)
            interfaces.append(dict(id=iid,mouthGeometry=mapping(line),mouthWidthM=line.length,
                relativeHeightsM=[LAND_RAISE]*len(line.coords),atGround=True,
                ends=[dict(kind=kind,level=list(level),parents=ids),
                      dict(kind='pedestrian_ground',level=[0],parents=sorted(peers))],
                landingGeometry=mapping(landing),landingDepthM=APPROACH_LENGTH,
                maxHeightMismatchM=0.,evidence='zero-height source mouth and explicit level-zero structural endpoint; shared source walking node or exposed source pedestrian paving; outward landing on finished ground'))
            connections.append(dict(id=f'pedestrian-connection:{len(connections)}',interfaceId=iid,
                transport='pedestrian',kind=kind,level=list(level),
                mouthGeometry=mapping(line),mouthWidthM=line.length,relativeHeightsM=[LAND_RAISE]*len(line.coords),
                sourceParents=ids,peerParents=sorted(peers),axisParents=sorted(axis_parents),groundParents=[],
                peerKind='pedestrian_ground',peerLevel=[0],atGround=True,
                connectorGeometry=mapping(Polygon()),connectorAreaM2=0.,maximumSourceGapM=MOUTH_NODE_ALIGNMENT,
                landingGeometry=mapping(landing),landingDepthM=APPROACH_LENGTH,
                evidence=interfaces[-1]['evidence']))
    return connections,interfaces
