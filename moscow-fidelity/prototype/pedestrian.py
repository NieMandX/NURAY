"""Open pedestrian bridge mouths at confirmed same-level walking connections."""
import numpy as np
import shapely as sh
from shapely.geometry import Point,LineString,Polygon,mapping
from transitions import parts,union,ENTRY_HEIGHT_TOLERANCE
from curbs import LAND_RAISE
from passage_space import ground_approach,APPROACH_LENGTH

def discover(candidates,records,ground_road,extent,precision,z_at,include_mixed_ground=False):
    elevated=[r for r in candidates if r.get('transport')=='pedestrian' and r['part'] in ['roadbed_overpass','roadbed_tunnel_descent']]
    # A descending pedestrian axis may still be named Pedestrian_road. Its
    # tier/end levels, not that name or a source-fragment cut flag, establish
    # the connection. A walking path can join a landing sideways; unlike a
    # railway, its tangent need not continue straight across the mouth.
    axes=[r for r in records if r['layer'].startswith('Pedestrian_road')
          and r['geometryType']=='polyline' and len(r['coordinates'])>1]
    ground_axes=[r for r in axes if include_mixed_ground or (r['properties'].get('db_tiers') or [0])==[0]]
    ground_ends=[]
    for r in ground_axes:
        p=r['properties']
        for index,cut,level in [(0,'beginningIsCut','db_segment_level_begin'),(-1,'endingIsCut','db_segment_level_end')]:
            if p.get(level,p.get(level.replace('level_begin','begin_level').replace('level_end','end_level'),p.get('db_segment_level')))!=0:continue
            ground_ends.append((Point(r['coordinates'][index][:2]),r['id']))
    connections=[];interfaces=[]
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
            for axis in axes:
                if tuple(axis['properties'].get('db_tiers') or [0])!=level:continue
                p=axis['properties']
                for index,cut,lev in [(0,'beginningIsCut','db_segment_level_begin'),(-1,'endingIsCut','db_segment_level_end')]:
                    if p.get(lev,p.get(lev.replace('level_begin','begin_level').replace('level_end','end_level'),p.get('db_segment_level')))!=0:continue
                    point=Point(axis['coordinates'][index][:2])
                    if point.distance(line)>.05:continue
                    same=[rid for q,rid in ground_ends if q.distance(point)<.02 and (not include_mixed_ground or rid!=axis['id'])]
                    if same:peers.update(same);axis_parents.add(axis['id'])
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
                maxHeightMismatchM=0.,evidence='zero-height source mouth and coincident ground/structural pedestrian endpoints at explicit level zero; outward landing on finished ground'))
            connections.append(dict(id=f'pedestrian-connection:{len(connections)}',interfaceId=iid,
                transport='pedestrian',kind=kind,level=list(level),
                mouthGeometry=mapping(line),mouthWidthM=line.length,relativeHeightsM=[LAND_RAISE]*len(line.coords),
                sourceParents=ids,peerParents=sorted(peers),axisParents=sorted(axis_parents),groundParents=[],
                peerKind='pedestrian_ground',peerLevel=[0],atGround=True,
                connectorGeometry=mapping(Polygon()),connectorAreaM2=0.,maximumSourceGapM=.05,
                landingGeometry=mapping(landing),landingDepthM=APPROACH_LENGTH,
                evidence=interfaces[-1]['evidence']))
    return connections,interfaces
