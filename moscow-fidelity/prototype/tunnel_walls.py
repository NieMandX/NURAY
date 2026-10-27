"""Retaining walls using verified source descent borders and open portals.

Source contours specify location and relative floor heights. Wall thickness and
wall width comes from map display styles; guard height is a project rule.
Missing contours retain a thin derived lining and are explicitly reported.
"""
import numpy as np
import shapely as sh
from collections import defaultdict
from shapely.geometry import Point,LineString,Polygon,mapping
from transitions import parts,union
from curbs import LAND_RAISE
from coverage import uncovered_length
from portal_guards import build_headers, parallel_to_source
from passage_space import walking_reserve,stable_area

POSITION_TOLERANCE=.05
HEIGHT_TOLERANCE=.02
GUARD_HEIGHT=1.0

def build(surfaces,records,dem,demtree,groups,extent,precision,connections,styles,triangulate,z_at,plane):
    descents=[s for s in surfaces if s['kind']=='roadbed_tunnel_descent']
    road_owners=defaultdict(list)
    for index,surface in enumerate(surfaces):
        if surface['kind'].startswith('roadbed'):
            road_owners[surface['owner']].append(index)
    reports=[];count=0
    for mode,level in sorted({(s.get('transport','vehicle'),tuple(s['tiers'])) for s in descents}):
        rows=[s for s in descents if s.get('transport','vehicle')==mode and tuple(s['tiers'])==level]
        footprint=union([s['poly'] for s in rows],precision)
        tunnels=union([s['poly'] for s in surfaces if s['kind']=='roadbed_tunnel' and s.get('transport','vehicle')==mode and tuple(s['tiers'])==level],precision)
        owners={s['owner'] for s in rows}
        entries=[c for c in connections if c['kind']=='roadbed_tunnel_descent' and owners.intersection(c['sourceParents'])]
        mouths=[sh.geometry.shape(c['mouthGeometry']) for c in entries]
        source=[r for r in records if r['properties'].get('db_road_part')=='border_tunnel_descent' and
                (r['layer']=='Roadbed_outline_underpasses')==(mode=='pedestrian') and tuple(r['properties'].get('db_tiers') or [0])==level]
        arches=[r for r in records if r['properties'].get('db_road_part')=='tunnel_arch' and (r['layer']=='Roadbed_outline_underpasses')==(mode=='pedestrian')]
        portals=[LineString(np.asarray(r['coordinates'])[:,:2]) for r in arches if len(r['coordinates'])>1]
        usable=footprint.boundary.difference(extent.boundary.buffer(precision*5)).difference(tunnels.buffer(precision*5))
        if mouths:usable=usable.difference(union(mouths,precision).buffer(precision*5))
        if portals:
            portal_edges=[]
            for portal in portals:
                for part in parts(footprint.boundary.intersection(portal.buffer(POSITION_TOLERANCE,cap_style='flat')),'LineString'):
                    for a,b in zip(part.coords,list(part.coords)[1:]):
                        segment=LineString([a,b])
                        if parallel_to_source(segment,portal):portal_edges.append(segment)
            # Remove the transverse opening itself. Removing its whole XY
            # tolerance buffer would shorten both side walls and leave 5 cm
            # gaps where they should meet the header.
            usable=usable.difference(union(portal_edges,precision))
        floor_tree=sh.STRtree([r['poly'] for r in rows])
        def floor(xy):
            point=Point(xy);r=rows[int(floor_tree.nearest(point))]
            contact=sh.shortest_line(point,r['poly'])
            projected=xy if contact.is_empty else np.asarray(contact.coords)[-1,:2]
            return float(z_at(r['plane'],projected))
        source_lines=[LineString(np.asarray(r['coordinates'])[:,:2]) for r in source]
        source_tree=sh.STRtree(source_lines)
        verified=[];matched=set();uncertain=[];height_errors=[];rejected_turns=0
        for r in rows:
            for edge in parts(usable.intersection(r['poly'].buffer(precision*2)),'LineString'):
                for a,b in zip(edge.coords,list(edge.coords)[1:]):
                    line=LineString([a,b])
                    if line.length<precision*5:continue
                    for i in source_tree.query(line.buffer(POSITION_TOLERANCE),predicate='intersects'):
                        i=int(i);src=source[i];sl=source_lines[i]
                        # Compare source floor height, not merely XY proximity.
                        overlap=line.intersection(sl.buffer(POSITION_TOLERANCE,cap_style='flat'))
                        for part in parts(overlap,'LineString'):
                            # A proximity buffer also catches up to 5 cm of a
                            # transverse end. Buffering that tiny return by the
                            # full wall width creates an erroneous concrete ear.
                            if not parallel_to_source(part,sl):
                                rejected_turns+=1;continue
                            xyz=np.asarray(src['coordinates']);d=np.r_[0,np.cumsum(np.linalg.norm(np.diff(xyz[:,:2],axis=0),axis=1))]
                            errors=[]
                            for xy in np.asarray(part.coords)[:,:2]:
                                point=Point(xy);ids=demtree.query(point,predicate='covered_by')
                                di=int(ids[0]) if len(ids) else int(demtree.nearest(point))
                                relative=float(z_at(r['plane']-dem[di][1],xy))-(LAND_RAISE if mode=='pedestrian' else 0)
                                errors.append(abs(relative-np.interp(sl.project(point),d,xyz[:,2])))
                            if max(errors,default=0)>HEIGHT_TOLERANCE:continue
                            verified.append(part);matched.add(src['id']);height_errors.extend(errors)
        confirmed=union(verified,precision)
        missing=usable.difference(confirmed.buffer(precision*5))
        style_id='13970' if mode=='pedestrian' else '77780';rule=styles['rules'][style_id]['style']
        width=rule['borderWidth'];guard=GUARD_HEIGHT;material=6
        bands=[]
        # Each source side is buffered only towards the land. No loop is closed
        # across a mouth, a tunnel arch, or a storage/region cut.
        merged=sh.line_merge(confirmed)
        for line in parts(merged,'LineString'):
            xy=np.asarray(line.coords);signs=[]
            for a,b in zip(xy,xy[1:]):
                length=np.linalg.norm(b-a)
                if length<precision*5:continue
                n=np.array([-(b-a)[1],(b-a)[0]])/length;mid=(a+b)/2
                inside_left=footprint.covers(Point(mid+n*.001))
                inside_right=footprint.covers(Point(mid-n*.001))
                if inside_left==inside_right:continue
                signs.append(-1 if inside_left else 1)
            if signs and len(set(signs))==1:
                bands.append(line.buffer(signs[0]*width,single_sided=True,join_style='mitre'))
            elif signs:uncertain.append(dict(reason='inconsistent outside along source border',geometry=mapping(line)))
        # The passage can widen or turn on the other side of a shared mouth.
        # A wall outside this descent alone could then obstruct its peer. Use
        # both confirmed floors locally; unrelated crossings at other heights
        # must not punch holes in retaining walls.
        peer_clearances=[]
        for entry,mouth in zip(entries,mouths):
            neighbourhood=mouth.buffer(width*2,cap_style='square')
            # Same source-owner selection and original surface order, without
            # rescanning every terrain cell for every tunnel entrance.
            peers=sorted({i for owner in entry.get('peerParents',[]) for i in road_owners.get(owner,[])})
            peer_clearances.extend(surfaces[i]['poly'].intersection(neighbourhood) for i in peers)
        # Every explicitly ground-level approach uses the same surrounding
        # terrain datum, regardless of the structure's source drawing tier.
        # Elevated/underground continuations never enter walking_reserve.
        landings=walking_reserve(connections,precision) if mode=='pedestrian' else Polygon()
        corridor=union([footprint,*peer_clearances,landings],precision)
        band=union(bands,precision).difference(corridor).intersection(extent)
        # Roundoff can leave fragments of a source border detached from its floor.
        band=stable_area(union([p for p in parts(band) if p.distance(footprint)<precision*5],precision),precision)
        support=[]
        for i in demtree.query(band,predicate='intersects'):
            i=int(i);piece=band.intersection(dem[i][0]);terrain=dem[i][1]+[0,0,LAND_RAISE]
            for t in triangulate(piece,np.zeros(3)):
                xy=t[:,:2];low=np.array([floor(p) for p in xy])-.10
                # The upper guard is measured from the surrounding sidewalk,
                # not from a projected nearby ramp floor. Use the shared plane
                # directly, also avoiding ill-conditioned fits on tiny cells.
                top=terrain+[0,0,guard]
                if np.any(z_at(top,xy)-low<.1):
                    raise ValueError('Descent floor is above its surrounding guard')
                poly=sh.set_precision(Polygon(xy),precision);bottom=plane(np.column_stack([xy,low]))
                support.append(dict(poly=poly,top=top,bottom=bottom))
                groups[('tunnel_wall_top',material)].extend(triangulate(poly,top))
                groups[('tunnel_wall_bottom',material)].extend(t[::-1] for t in triangulate(poly,bottom))
        support_tree=sh.STRtree([s['poly'] for s in support]);emitted=[];vertex_heights={}
        perimeter=band.boundary.difference(extent.boundary.buffer(precision*5))
        def heights(xy):
            key=tuple(np.round(xy,8))
            if key not in vertex_heights:
                s=support[int(support_tree.nearest(Point(xy)))]
                vertex_heights[key]=(float(z_at(s['bottom'],xy)),float(z_at(s['top'],xy)))
            return vertex_heights[key]
        # The polygon perimeter is authoritative. Snapping independently
        # triangulated cells can move their edges by microns, so exact line
        # intersection would omit long legitimate wall sides. Node the true
        # perimeter against nearby height cells, then emit every interval once.
        for chain in parts(perimeter,'LineString'):
            xy=list(chain.coords)
            for a,b in zip(xy,xy[1:]):
                edge=LineString([a,b])
                if edge.length<precision:continue
                stops=[0.,edge.length]
                for i in support_tree.query(edge.buffer(precision*3),predicate='intersects'):
                    for segment in parts(edge.intersection(support[int(i)]['poly'].buffer(precision*3)),'LineString'):
                        stops.extend([edge.project(Point(segment.coords[0])),edge.project(Point(segment.coords[-1]))])
                stops=sorted(set(stops))
                for lo,hi in zip(stops,stops[1:]):
                    if hi-lo<precision/10:continue
                    aa=np.asarray(edge.interpolate(lo).coords)[0];bb=np.asarray(edge.interpolate(hi).coords)[0]
                    al,ah=heights(aa);bl,bh=heights(bb)
                    v=np.array([[*aa,al],[*bb,bl],[*bb,bh],[*aa,ah]])
                    faces=[v[[0,1,2]],v[[0,2,3]]]
                    groups[('tunnel_wall_side',material)].extend(faces+[f[::-1] for f in faces]);count+=1
                    emitted.append(LineString([aa,bb]))
        # Retain a thin lining when no source border exists; never silently
        # extrapolate source guardrails to an unconfirmed transverse boundary.
        for r in rows:
            for edge in parts(missing.intersection(r['poly']),'LineString'):
                for di in demtree.query(edge,predicate='intersects'):
                    for part in parts(edge.intersection(dem[int(di)][0]),'LineString'):
                        for a,b in zip(part.coords,list(part.coords)[1:]):
                            low=z_at(r['plane'],[a,b]);high=z_at(dem[int(di)][1],[a,b])+LAND_RAISE
                            if max(high-low)<.05:continue
                            high=np.maximum(low,high);v=np.array([[*a,low[0]],[*b,low[1]],[*b,high[1]],[*a,high[0]]])
                            faces=[v[[0,1,2]],v[[0,2,3]]]
                            groups[('inferred-walls',material)].extend(faces+[f[::-1] for f in faces]);count+=1
        gap=uncovered_length(perimeter,union(emitted,precision),precision*5)
        headers=build_headers(footprint,arches,band,floor,dem,demtree,groups,extent,
                              precision,width,guard,triangulate,z_at,plane,landings)
        reports.append(dict(transport=mode,level=list(level),sourceStyleId=style_id,widthM=width,guardAboveLandM=guard,
            rejectedTransverseMatches=rejected_turns,portalHeaders=headers,
            sourceBorderFeatures=len(source),matchedSourceBorders=sorted(matched),
            unmatchedSourceBorders=[r['id'] for r in source if r['id'] not in matched],
            sourcePortalFeatures=[r['id'] for r in arches],sourceMatchedBoundaryM=confirmed.length,
            fallbackBoundaryM=missing.length,uncoveredSolidSidesM=gap,maxSourceHeightMismatchM=max(height_errors,default=0),
            uncertainty=uncertain,bandGeometry=mapping(band),
            passed=bool(gap<.001 and not uncertain and headers['passed']),
            evidence='verified source border position/tier/relative floor; style width; project guard height 1 m; top follows raised surrounding terrain; bottom follows source floor'))
    return count,dict(ruleVersion=4,passed=all(r['passed'] for r in reports),groups=reports,
                      policy='parallel source-supported side walls and deep portal headers with 1 m guards above raised surrounding land; short fascia below ground, open ground-level entries; all retaining concrete uses material 6; missing source sides retain explicitly inferred thin lining')
