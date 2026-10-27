"""Rail grade mouths: source endpoint topology plus actual slab height.

Ground railways are axes, not roadbed_flat polygons. Their map Z is not an
elevation. Use explicit endpoint levels and the Transport_Roadbed height field.
Source fragment cut flags alone are not dead ends (or proof of a connection).
"""
import json
import numpy as np
import shapely as sh
from shapely.geometry import Point, LineString, Polygon, mapping
from railway_surfaces import confirmed_owners
from transitions import parts, union, ENTRY_HEIGHT_TOLERANCE

ENDPOINT_TOLERANCE = .02
MOUTH_TOLERANCE = .05
TRACK_OFFSET = .12  # .10 m ground/ballast datum + .02 m rail ribbon.
POLICY = ('Open full-width railway bridge mouths only at a zero-relative-height '
          'source slab edge with coincident ground/elevated rail endpoints, '
          'explicit level zero, and opposite inward/outward continuations. '
          'Exclude region cuts; retain side shoulders and parapets. '
          'Ground under the track is ballast support, not a road obstruction.')


def source_candidates(features, extent, precision=1e-5):
    """Reconstruct source-relative rail slabs for immutable release refinements."""
    owners={r['source'] for r in confirmed_owners(features,precision)}
    rows=[]
    for f in features:
        if f['id'] not in owners: continue
        xyz=np.asarray(f['coordinates']); patches=[]
        for i in range(len(xyz)-2):
            t=xyz[i:i+3]; a=np.column_stack((t[:,:2],np.ones(3)))
            if abs(np.linalg.det(a))<1e-8: continue
            p=sh.set_precision(sh.make_valid(Polygon(t[:,:2])),precision).intersection(extent)
            if p.area>1e-9: patches.append((p,np.linalg.solve(a,t[:,2])))
        if patches:
            rows.append(dict(id=f['id'],kind='road',part=f['properties']['db_road_part'],
                tiers=f['properties'].get('db_tiers') or [0],
                poly=union([p for p,c in patches],precision),patches=patches))
    return rows


def endpoint_level(f,index):
    p=f['properties']; end='begin' if index==0 else 'end'
    return p.get('db_segment_'+end+'_level',p.get('db_segment_level_'+end,p.get('db_segment_level')))


def discover(candidates,features,extent,precision,z_at,part='roadbed_overpass'):
    """Find bridge entries by default; descent entries use a separate ID space."""
    assert part in ('roadbed_overpass','roadbed_tunnel_descent')
    prefix='railway' if part=='roadbed_overpass' else 'railway-tunnel'
    confirmed={r['source'] for r in confirmed_owners(features,precision)}
    ramps=[r for r in candidates if r['id'] in confirmed and r['part']==part]
    rails=[f for f in features if f['layer']=='Railroad_line' and f['geometryType']=='polyline'
           and len(f['coordinates'])>1]
    ground=[f for f in rails if (f['properties'].get('db_tiers') or [0])==[0]]
    connections=[]; interfaces=[]
    for level in sorted({tuple(r['tiers']) for r in ramps}):
        rows=[r for r in ramps if tuple(r['tiers'])==level]
        footprint=union([r['poly'] for r in rows],precision); edges=[]
        for r in rows:
            for p,c in r['patches']:
                for line in parts(footprint.boundary.intersection(p.buffer(precision*2)),'LineString'):
                    for a,b in zip(line.coords,list(line.coords)[1:]):
                        if np.linalg.norm(np.array(b)-a)<.05 or np.max(abs(z_at(c,[a,b])))>ENTRY_HEIGHT_TOLERANCE: continue
                        edges.extend(parts(LineString([a,b]).difference(extent.boundary.buffer(precision*5)),'LineString'))
        merged=sh.line_merge(union(edges,precision)) if edges else LineString()
        elevated=[f for f in rails if tuple(f['properties'].get('db_tiers') or [0])==level]
        for mouth in parts(merged,'LineString'):
            if mouth.length<.25: continue
            peers=set(); axes=set(); witnesses=[]
            for rail in elevated:
                for end in (0,-1):
                    if endpoint_level(rail,end)!=0: continue
                    xy=np.asarray(rail['coordinates'])[:,:2]; point=Point(xy[end])
                    if mouth.distance(point)>MOUTH_TOLERANCE: continue
                    segment=LineString(xy if end==0 else xy[::-1])
                    inward=segment.interpolate(min(1.,segment.length/2))
                    if not footprint.contains(inward): continue
                    for other in ground:
                        for ge in (0,-1):
                            if endpoint_level(other,ge)!=0: continue
                            gxy=np.asarray(other['coordinates'])[:,:2]; gp=Point(gxy[ge])
                            if point.distance(gp)>ENDPOINT_TOLERANCE: continue
                            route=LineString(gxy if ge==0 else gxy[::-1]); out=route.interpolate(min(1.,route.length/2))
                            if footprint.buffer(precision*5).covers(out): continue
                            # Both routes must cross the mouth, not graze its side.
                            on=sh.shortest_line(point,mouth); centre=point if on.is_empty else Point(on.coords[-1])
                            s=mouth.project(centre); a=np.array(mouth.interpolate(max(0,s-.1)).coords[0]); b=np.array(mouth.interpolate(min(mouth.length,s+.1)).coords[0])
                            tangent=(b-a)/np.linalg.norm(b-a); normal=np.array([-tangent[1],tangent[0]])
                            v=np.array(inward.coords[0])-np.array(centre.coords[0]); w=np.array(out.coords[0])-np.array(centre.coords[0])
                            if np.dot(v,normal)*np.dot(w,normal)>=0: continue
                            if min(abs(v@normal)/np.linalg.norm(v),abs(w@normal)/np.linalg.norm(w))<.25: continue
                            peers.add(other['id']); axes.add(rail['id'])
                            witnesses.append(dict(axis=rail['id'],ground=other['id'],endpoint=list(point.coords[0]),
                                endpointGapM=point.distance(gp),mouthDistanceM=mouth.distance(point)))
            if not peers: continue
            parents=sorted(r['id'] for r in rows if r['poly'].distance(mouth)<precision*5)
            iid=f'{prefix}-interface:{len(interfaces)}'
            evidence='source railway endpoints share level zero and opposite slab sides; full source mouth has zero relative height'
            interfaces.append(dict(id=iid,mouthGeometry=mapping(mouth),mouthWidthM=mouth.length,
                relativeHeightsM=[0.]*len(mouth.coords),atGround=True,surfaceOffsetM=TRACK_OFFSET,
                ends=[dict(kind=part,level=list(level),parents=parents),
                      dict(kind='railway_ground',level=[0],parents=sorted(peers))],
                maxHeightMismatchM=0.,evidence=evidence,witnesses=witnesses))
            connections.append(dict(id=f'{prefix}-connection:{len(connections)}',interfaceId=iid,
                kind=part,level=list(level),purpose='railway',retainGroundSupport=True,
                mouthGeometry=mapping(mouth),mouthWidthM=mouth.length,
                relativeHeightsM=[0.]*len(mouth.coords),sourceParents=parents,peerParents=sorted(peers),
                axisParents=sorted(axes),groundParents=[],peerKind='railway_ground',peerLevel=[0],atGround=True,
                connectorGeometry=mapping(Polygon()),connectorAreaM2=0.,maximumSourceGapM=MOUTH_TOLERANCE,
                heightToleranceM=ENTRY_HEIGHT_TOLERANCE,surfaceOffsetM=TRACK_OFFSET,evidence=evidence))
    # Match the persisted registry representation (GeoJSON arrays, not tuples).
    return json.loads(json.dumps(connections)),json.loads(json.dumps(interfaces))
