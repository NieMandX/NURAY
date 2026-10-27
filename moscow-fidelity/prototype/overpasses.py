"""Continuous structural profiles by physical level and transport mode.

Dimensions are requested modelling rules: 1 m overhang on each side, shoulder
tops 0.10 m above asphalt, underside 1 m below asphalt, and parapet tops 0.70 m
above asphalt / 0.20 m wide at the deck's outer edges.
Pedestrian profiles use retained map styling, independently of car dimensions.
Their source heights are offset to the sidewalk datum by the surface builder.
"""
import numpy as np
import shapely as sh
from shapely.geometry import Polygon, LineString, Point, mapping
from curbs import LAND_RAISE
from shapely.ops import substring
from spatial_mask import LinearMask,SpatialMask
from overpass_sheets import structural_sheets,sheet_entries,joined_portal_datums

OVERHANG = 1.
DEPTH = 1.
SHOULDER_RAISE = LAND_RAISE  # One 10 cm datum for ground curbs and ramp shoulders.
PARAPET_HEIGHT = .70
PARAPET_WIDTH = .20
CONCRETE = 10


def parts(g, kind='Polygon'):
    if g.is_empty: return []
    if g.geom_type == kind: return [g]
    return [p for sub in getattr(g,'geoms',[]) for p in parts(sub,kind)]


def area_union(gs,precision):
    result=sh.union_all([p for g in gs for p in parts(sh.make_valid(g))],grid_size=precision)
    # Precision overlays can retain collapsed lines beside an areal result.
    # Those have no roof/footprint and a mixed collection has no boundary API.
    if result.geom_type not in ('Polygon','MultiPolygon'):
        result=sh.union_all(parts(result),grid_size=precision)
    return Polygon() if result.is_empty else result


def build(surfaces, dem, demtree, groups, extent, precision, triangulate, z_at, plane, connections=None,prepartitioned=False,collision_floors=None):
    from coverage import uncovered_length
    elevated=[s for s in surfaces if s['kind']=='roadbed_overpass']
    floors=collision_floors if collision_floors is not None else [s for s in surfaces if s['kind'].startswith('roadbed')]
    floor_tree=sh.STRtree([s['poly'] for s in floors])
    profiles=[];side_count=0
    if prepartitioned:
        modes={r.get('transport','vehicle') for r in elevated}
        if len(modes)!=1:raise ValueError('A prepartitioned structural sheet must have one transport mode')
        transport=next(iter(modes));level=tuple(sorted({tier for r in elevated for tier in r['tiers']}))
        sheets=[(level,transport,elevated)]
    else:sheets,connections=structural_sheets(elevated,connections,dem,demtree,precision,z_at)
    for level,transport,rows in sheets:
        print('OVERPASS PROFILE',level,transport,'cells',len(rows),flush=True)
        rule=rows[0].get('profile',{})
        overhang=rule.get('overhang',OVERHANG);depth=rule.get('depth',DEPTH)
        shoulder_raise=rule.get('shoulderRaise',SHOULDER_RAISE)
        parapet_height=rule.get('parapetHeight',PARAPET_HEIGHT);parapet_width=rule.get('parapetWidth',PARAPET_WIDTH)
        concrete=rule.get('material',CONCRETE)
        footprint=area_union([s['poly'] for s in rows],precision)
        if footprint.is_empty:continue
        source_tree=sh.STRtree([s['poly'] for s in rows]);cache={};corner_adjustments=[]

        def ground_height(xy):
            pt=Point(xy);ids=demtree.query(pt,predicate='covered_by')
            i=int(ids[0]) if len(ids) else int(demtree.nearest(pt))
            return float(z_at(dem[i][1],xy))

        def source_height(xy):
            pt=Point(xy);s=rows[int(source_tree.nearest(pt))]
            contact=sh.shortest_line(pt,s['poly'])
            projected=xy if contact.is_empty else np.asarray(contact.coords)[-1,:2]
            value=float(z_at(s['plane'],projected))
            if contact.length<=precision:
                # Several source faces may own the exact same corner. Resolve
                # sub-tolerance source-height noise symmetrically, rather than
                # allowing STRtree traversal order to pick one of the faces.
                # The midpoint minimises the worst join error. Never combine
                # a spread requiring more than the existing 1 mm tolerance.
                nearest=source_tree.query_nearest(pt,all_matches=True)
                values=[]
                for j in nearest:
                    cell=rows[int(j)];link=sh.shortest_line(pt,cell['poly'])
                    q=xy if link.is_empty else np.asarray(link.coords)[-1,:2]
                    values.append(float(z_at(cell['plane'],q)))
                if len(values)>1 and max(values)-min(values)<.002:
                    resolved=(min(values)+max(values))*.5
                    corner_adjustments.append(abs(resolved-value));value=resolved
            return value,contact.length

        def source_relative_height(xy):
            point=Point(xy);s=rows[int(source_tree.nearest(point))]
            contact=sh.shortest_line(point,s['poly'])
            q=xy if contact.is_empty else np.asarray(contact.coords)[-1,:2]
            return source_height(xy)[0]-ground_height(q)

        def entry_datum(xy,index=None):
            # Source-continuous roads can meet above or below ground as well.
            # Never force a nonzero class transition down to the terrain datum.
            point=Point(xy)
            if index is None:
                indices,distances=portal_tree.query_nearest(point,return_distance=True)
                index=min(zip(map(int,indices),distances),key=lambda item:(item[1],item[0]))[0]
            line,distances,values=portal_datums[index]
            station=line.project(point)
            return ground_height(xy)+float(np.interp(station,distances,values))

        def height(xy):
            key=tuple(np.round(xy,8))
            if key not in cache:
                pt=Point(xy)
                # Constant outward continuation of edge height. Along the road,
                # the shoulder follows the source ramp, not a single flat slab.
                base,edge_distance=source_height(xy)
                nearby=portal_tree.query(pt,predicate='dwithin',distance=overhang)
                if len(nearby):
                    # At a grade mouth, the raised shoulder meets the raised
                    # ground at the very same XY height. Constant outward
                    # projection alone would suppress terrain crossfall and
                    # leave a centimetre-sized opening at the shoulder end.
                    entry_index,entry_distance=min(((int(j),portal_datums[int(j)][0].distance(pt)) for j in nearby),key=lambda item:(item[1],item[0]))
                    t=min(1.,entry_distance/overhang)
                    weight=(1-t*t*(3-2*t))*edge_distance/max(edge_distance+entry_distance,1e-12)
                    # On the mouth: the ground datum. On the asphalt edge:
                    # the exact road datum. This also handles oblique mouths,
                    # where nearest-road projection can land partway up the
                    # ramp even though the shoulder end is still at grade.
                    if weight>0:base+=weight*(entry_datum(xy,entry_index)-base)
                cache[key]=base
            return cache[key]

        # Identify transverse entry boundaries at relative ground height zero.
        # Above-grade sides crossing ground in XY are not mistaken for entries.
        portals=[];portal_datums=[];cap_masks=[];seen_portals=set();entry_lines=[];entry_records=[]
        if connections is not None:
            owners={s['owner'] for s in rows}
            entry_records=[r for r in connections if r['kind']=='roadbed_overpass' and r.get('transport','vehicle')==transport
                           and (not r.get('sourceParents') or owners.intersection(r['sourceParents']))]
            entry_records=sheet_entries(entry_records,footprint,precision)
            entry_lines=[sh.geometry.shape(r['mouthGeometry']) for r in entry_records]
        for s in rows if connections is None else []:
            for line in parts(s['poly'].boundary.intersection(footprint.boundary),'LineString'):
                xy=np.asarray(line.coords)[:,:2]
                for a,b in zip(xy,xy[1:]):
                    if np.linalg.norm(a-b)<.0001: continue
                    ids=demtree.query(Point((a+b)/2),predicate='covered_by')
                    if not len(ids): continue
                    relative=z_at(s['plane'],[a,b])-z_at(dem[int(ids[0])][1],[a,b])
                    if np.max(abs(relative))>.002: continue
                    key=tuple(sorted([tuple(np.round(a,5)),tuple(np.round(b,5))]))
                    if key in seen_portals: continue
                    seen_portals.add(key)
                    entry_lines.append(LineString([a,b]))
        for entry_index,entry in enumerate(entry_lines):
            original=np.asarray(entry.coords)[:,:2]
            xy=original.copy()
            # Extend only the ends of the complete mouth, not each noded
            # triangle fragment. This preserves both lateral shoulder edges.
            xy[0]-=(xy[1]-xy[0])/np.linalg.norm(xy[1]-xy[0])*2*overhang
            xy[-1]+=(xy[-1]-xy[-2])/np.linalg.norm(xy[-1]-xy[-2])*2*overhang
            portals.append(LineString(xy))
            values=np.asarray(entry_records[entry_index].get('relativeHeightsM',[0.]*len(original))
                              if entry_records else [0.]*len(original))
            # Retain the original nodes between the two extended shoulder ends.
            datum_xy=np.vstack([xy[0],original,xy[-1]])
            distances=np.r_[0,np.cumsum(np.linalg.norm(np.diff(datum_xy,axis=0),axis=1))]
            # The original mouth nodes remain authoritative. Outside those
            # nodes, a bent/forked slab can approach its own shoulder end at a
            # different height. Follow that actual source edge instead of
            # extending the first mouth height through the returning branch.
            source_joint=bool(entry_records and entry_records[entry_index].get('datumPolicy')=='source-shared-edge')
            ends=[source_relative_height(xy[0]),source_relative_height(xy[-1])] if source_joint else [values[0],values[-1]]
            portal_datums.append((LineString(datum_xy),distances,np.r_[ends[0],values,ends[-1]]))
            outside_signs=[]
            for index,(aa,bb) in enumerate(zip(xy,xy[1:])):
                tangent=(bb-aa)/np.linalg.norm(bb-aa);out=np.array([tangent[1],-tangent[0]])
                # Determine the outside using the original road-mouth segment.
                # Extending a short end segment beyond the shoulders can put
                # its new midpoint outside the asphalt on BOTH sides; that
                # ambiguity used to leave an unwanted transverse deck/rail.
                probe=(original[index]+original[index+1])/2
                oriented=False
                for distance in [precision*2,precision*5,max(.001,precision*10),.01,.05]:
                    plus=footprint.covers(Point(probe+out*distance))
                    minus=footprint.covers(Point(probe-out*distance))
                    if plus!=minus:
                        if plus:out=-out
                        oriented=True;break
                if not oriented:raise ValueError(('Ambiguous source road-mouth orientation; refusing an inferred transverse concrete cap',
                    entry_records[entry_index].get('id') if entry_records else None,probe.tolist(),sorted({s['owner'] for s in rows})))
                outside_signs.append(-1 if np.dot(out,[tangent[1],-tangent[0]])>0 else 1)
            if len(set(outside_signs))!=1:
                raise ValueError('Inconsistent road-mouth orientation; refusing a self-crossing concrete cut')
            # Cut one continuous outside strip, with joined corners. Separate
            # segment rectangles leave triangular gaps at a bent/noded mouth;
            # such a tiny detached roof can generate a full-height parapet.
            mouth=LineString(xy)
            outside=mouth.buffer(outside_signs[0]*2*overhang,single_sided=True,join_style='mitre')
            # Resolve overlay-grid drift along the complete mouth too.
            cap_masks.extend([outside,mouth.buffer(precision*5,cap_style='flat',join_style='mitre')])
        portal_datums=joined_portal_datums(portal_datums,entry_lines,footprint,precision)
        portal_tree=sh.STRtree(portals)
        expanded=area_union([footprint.buffer(overhang,join_style='mitre',mitre_limit=2).intersection(extent)],precision)
        extension=area_union([sh.difference(expanded,footprint,grid_size=precision)],precision)
        if cap_masks:extension=area_union([sh.difference(extension,area_union(cap_masks,precision),grid_size=precision)],precision)
        from structure_clearance import reserved_extension,attached_extension
        reservation=reserved_extension(extension,floors,floor_tree,{s['owner'] for s in rows},
            height,depth,parapet_height,triangulate,z_at,precision)
        if not reservation.is_empty:
            extension=area_union([sh.difference(extension,reservation,grid_size=precision)],precision)
        extension,discarded_extension=attached_extension(footprint,extension,precision)
        expanded=area_union([footprint,extension],precision)
        orphan_area=sum(p.area for p in parts(expanded) if p.intersection(footprint).area<precision**2)
        portal_lines=sh.union_all(portals) if portals else LineString()
        portal_tree=sh.STRtree(portals)
        lateral=expanded.boundary.difference(extent.boundary.buffer(.00005))
        if portals:lateral=lateral.difference(portal_lines.buffer(precision*10,cap_style='square'))
        parapet=area_union([lateral.buffer(parapet_width,cap_style='flat',join_style='mitre')
            .intersection(expanded).difference(footprint)],precision)
        shoulder=area_union([sh.difference(extension,parapet,grid_size=precision)],precision)
        extension_mask=SpatialMask(extension)
        shoulder_mask=SpatialMask(shoulder);parapet_mask=SpatialMask(parapet)

        # Noded common terrain cells keep neighbouring shoulder heights shared.
        # Asphalt already has exact source planes and gets its own underside.
        supports=[]
        for s in rows:
            bottom=s['plane']-np.array([0,0,depth])
            groups[('overpass_bottom',concrete)].extend([t[::-1] for t in triangulate(s['poly'],bottom)])
        for i in demtree.query(extension,predicate='intersects'):
            for p in parts(sh.intersection(extension_mask.near(dem[i][0]),dem[i][0],grid_size=precision)):
                for t in triangulate(p,np.zeros(3)):
                    t[:,2]=[height(xy) for xy in t[:,:2]]
                    c=plane(t);poly=sh.set_precision(Polygon(t[:,:2]),precision)
                    supports.append(dict(poly=poly,plane=c))
                    groups[('overpass_bottom',concrete)].append((t-np.array([0,0,depth]))[::-1])
                    # Keep all areal overlays in the same precision model.
                    # Boolean contacts may retain collapsed lines; these are
                    # not roofs and must not enter a polygon triangulation.
                    probe=poly.buffer(precision*2)
                    roof=area_union([sh.intersection(poly,shoulder_mask.near(probe),grid_size=precision)],precision)
                    guard=area_union([sh.intersection(poly,parapet_mask.near(probe),grid_size=precision)],precision)
                    groups[('overpass_shoulder',concrete)].extend(triangulate(roof,c+np.array([0,0,shoulder_raise])))
                    groups[('parapet_top',concrete)].extend(triangulate(guard,c+np.array([0,0,parapet_height])))
        all_support=rows+supports
        print('OVERPASS ROOFS',level,transport,'shoulder cells',len(supports),flush=True)
        support_tree=sh.STRtree([s['poly'] for s in all_support])

        def sides(shape,boundary,low_offset,high_offset,kind):
            nonlocal side_count
            seen=set();lines=[];vertex_heights={}
            boundary_index=LinearMask(boundary)
            def top(xy):
                key=tuple(np.round(xy,8))
                if key not in vertex_heights:
                    i=int(support_tree.nearest(Point(xy)));cell=all_support[i]
                    vertex_heights[key]=float(z_at(cell['plane'],xy))
                return vertex_heights[key]
            for poly in parts(sh.orient_polygons(shape)):
                for ring in [poly.exterior,*poly.interiors]:
                    xy=np.asarray(ring.coords)[:,:2]
                    for start,end in zip(xy,xy[1:]):
                        source_segment=LineString([start,end])
                        # This segment already belongs to the exact roof ring.
                        # Re-snapping it separately from the boundary can delete
                        # a long near-collinear interval during intersection.
                        nearby_boundary=boundary_index.near(source_segment.buffer(precision*2))
                        # Use the precision tolerance only to select intervals;
                        # all emitted vertices remain on the original roof edge.
                        # A transverse edge touching only at a corner is not a
                        # side-wall interval, even though its buffer has width.
                        tangent=(end-start)/np.linalg.norm(end-start);aligned=[]
                        for line in parts(nearby_boundary,'LineString'):
                            points=np.asarray(line.coords)[:,:2]
                            for a,b in zip(points,points[1:]):
                                length=np.linalg.norm(b-a)
                                if length>0 and abs(np.dot((b-a)/length,tangent))>.999999:
                                    aligned.append(LineString([a,b]))
                        selected=sh.union_all(aligned)
                        segment=source_segment.intersection(selected.buffer(precision*2,cap_style='flat',join_style='mitre'))
                        for seg in parts(segment,'LineString'):
                            if seg.length<.00001:continue
                            # Collect cuts using a numerical tolerance, then emit
                            # each interval once. A micron-scale offset between a
                            # clipped roof triangle and the exact perimeter must
                            # never cause metres of side wall to be omitted.
                            stops=[0.,seg.length]
                            for j in support_tree.query(seg.buffer(precision*3),predicate='intersects'):
                                cell=all_support[int(j)]
                                for piece in parts(seg.intersection(cell['poly'].buffer(precision*3)),'LineString'):
                                    stops.extend([seg.project(Point(piece.coords[0])),seg.project(Point(piece.coords[-1]))])
                            stops=sorted(set(stops))
                            for lo_pos,hi_pos in zip(stops,stops[1:]):
                                if hi_pos-lo_pos<.000001:continue
                                a=np.asarray(seg.interpolate(lo_pos).coords)[0];b=np.asarray(seg.interpolate(hi_pos).coords)[0]
                                if np.dot(b-a,end-start)<0:a,b=b,a
                                key=tuple(sorted([tuple(np.round(a,8)),tuple(np.round(b,8))]))
                                if key in seen:continue
                                seen.add(key);h=np.array([top(a),top(b)])
                                offset=high_offset(Point((a+b)/2)) if callable(high_offset) else high_offset
                                lo=h+low_offset;hi=h+offset
                                v=np.array([[*a,lo[0]],[*b,lo[1]],[*b,hi[1]],[*a,hi[0]]])
                                groups[(kind,concrete)].extend([v[[0,1,2]],v[[0,2,3]]]);side_count+=1
                                lines.append(LineString([a,b]))
            return sh.union_all(lines) if lines else LineString()

        # End faces at ground-height entries remain buried in ground. Crop edges
        # stay open for the adjacent streamed tile instead of inventing a wall.
        deck_edges=expanded.boundary.difference(extent.boundary.buffer(.00005))
        # Core end faces stop at asphalt. Shoulder end/outer faces reach the
        # raised concrete roof. The inner riser closes its 10 cm road-facing
        # step, so raising a roof can never leave an open shell or a crack.
        emitted_sides=sides(expanded,deck_edges,-depth,
            lambda p: shoulder_raise if extension_mask.near(p.buffer(precision*2)).distance(p)<precision else 0,'overpass_side')
        riser_edges=sh.intersection(extension.boundary,footprint.boundary,grid_size=precision)
        riser_edges=riser_edges.difference(extent.boundary.buffer(.00005))
        riser_edges=sh.union_all(parts(riser_edges,'LineString'),grid_size=precision)
        if shoulder_raise==0:riser_edges=LineString()
        emitted_risers=sides(extension,riser_edges,0,shoulder_raise,'overpass_riser')
        para_edges=parapet.boundary.difference(extent.boundary.buffer(.00005))
        emitted_parapets=sides(parapet,para_edges,shoulder_raise,parapet_height,'parapet_side')
        # Geometry witnesses: verify joins against original source asphalt and
        # each emitted cell, rather than trusting the profile parameters alone.
        tree=sh.STRtree([s['poly'] for s in supports]);joins=[]
        for s in rows:
            for j in tree.query(s['poly'],predicate='intersects'):
                other=supports[int(j)]
                for line in parts(s['poly'].intersection(other['poly']),'LineString'):
                    xy=np.asarray(line.coords)[:,:2]
                    step=z_at(other['plane'],xy)+shoulder_raise-z_at(s['plane'],xy)
                    joins.extend(abs(step-shoulder_raise))
        missing_sides=uncovered_length(deck_edges,emitted_sides,.00005)
        missing_parapets=uncovered_length(para_edges,emitted_parapets,.00005)
        missing_risers=uncovered_length(riser_edges,emitted_risers,.00005)
        gates=[substring(line,.05,line.length-.05).buffer(.001,cap_style='flat')
               for line in entry_lines if line.length>.10]
        entry_gate=sh.union_all(gates) if gates else Polygon()
        blocked_entry=extension.intersection(entry_gate).area
        blocked_riser=riser_edges.intersection(entry_gate).length
        ground_entries=expanded.boundary.intersection(portal_lines.buffer(precision*10)).difference(footprint.buffer(precision*10))
        ground_entries=sh.union_all([line for line in parts(ground_entries,'LineString') if line.length>precision*10])
        ground_joins=[];ground_join_witness=None
        for line in parts(ground_entries,'LineString'):
            for j in tree.query(line.buffer(precision*3),predicate='intersects'):
                cell=supports[int(j)]
                for piece in parts(line.intersection(cell['poly'].buffer(precision*3)),'LineString'):
                    for di in demtree.query(piece,predicate='intersects'):
                        for edge in parts(piece.intersection(dem[int(di)][0]),'LineString'):
                            # The tolerance buffer finds neighbouring faces;
                            # heights must be sampled on the actual face. A
                            # thin triangle's plane is unsafe to extrapolate
                            # even a few micrometres beyond its boundary.
                            xy=np.array([np.asarray(sh.shortest_line(Point(p),cell['poly']).coords)[-1,:2]
                                if not cell['poly'].covers(Point(p)) else p for p in edge.coords])
                            expected=np.asarray([entry_datum(point) for point in xy]);actual=z_at(cell['plane'],xy)
                            errors=abs(actual-expected);ground_joins.extend(errors)
                            k=int(np.argmax(errors))
                            if ground_join_witness is None or errors[k]>ground_join_witness['errorM']:
                                point=Point(xy[k]);pi=int(portal_tree.nearest(point))
                                ground_join_witness=dict(errorM=float(errors[k]),xy=xy[k].tolist(),
                                    actualM=float(actual[k]),expectedM=float(expected[k]),
                                    portal=entry_records[pi].get('id') if entry_records else pi,
                                    supportGeometry=mapping(cell['poly']))
        profiles.append(dict(transport=transport,styleId=rule.get('styleId'),level=list(level),deckDepthM=depth,sideOverhangM=overhang,
            reservedNeighbourFloorAreaM2=reservation.area,
            discardedUnsupportedExtensionM2=discarded_extension,
            extensionClearancePolicy='source exposed floors take priority over synthetic extensions when their local one-metre corridor intersects the concrete height envelope; source slabs unchanged; not engineering clearance',
            parapetHeightM=parapet_height,parapetWidthM=parapet_width,
            shoulderRaiseM=shoulder_raise,parapetTopAboveRoadM=parapet_height,
            parapetHeightAboveShoulderM=parapet_height-shoulder_raise,
            heightReference='source asphalt; shoulder mouth follows the connected road height, including nonzero relative levels',
            mouthDirectionReference='original unextended source mouth; opposite inside/outside probes must agree',
            mouthCutToleranceM=precision*5,
            mouthCutPolicy='one joined outside strip per structural sheet; nearby separate-height branches cannot share a profile; source-continuous sheet joins stay open',
            detachedConcreteAreaM2=orphan_area,
            asphaltAreaM2=footprint.area,shoulderAreaM2=extension.area,parapetAreaM2=parapet.area,
            groundEntrySegments=sum(r.get('atGround',True) for r in entry_records) if entry_records else len(portals),
            openInterfaceSegments=len(portals),groundEntryGeometry=mapping(portal_lines),
            asphaltGeometry=mapping(footprint),deckGeometry=mapping(expanded),parapetGeometry=mapping(parapet),
            shoulderGeometry=mapping(shoulder),shoulderRiserGeometry=mapping(riser_edges),
            groundShoulderConnectionGeometry=mapping(ground_entries),
            sourceParents=sorted({s['owner'] for s in rows}),
            extensionHeightCells=[dict(geometry=mapping(s['poly']),heightPlane=s['plane'].tolist()) for s in supports],
            maxAsphaltShoulderHeightMismatchM=max(joins,default=0),
            maxShoulderStepErrorM=max(joins,default=0),
            maxSourceCornerResolutionM=max(corner_adjustments,default=0),
            maxGroundShoulderJoinErrorM=max(ground_joins,default=0),
            groundJoinWitness=ground_join_witness,
            raisedConcreteInEntryPassageM2=blocked_entry,shoulderRiserInEntryPassageM=blocked_riser,
            uncoveredDeckSidesM=missing_sides,uncoveredParapetSidesM=missing_parapets,uncoveredShoulderRisersM=missing_risers,
            passed=bool(max(joins,default=0)<.001 and max(ground_joins,default=0)<.001 and missing_sides<.001 and missing_parapets<.001 and missing_risers<.001 and blocked_entry<.0001 and blocked_riser<.001 and orphan_area<precision**2),
            evidence=rule.get('evidence','user-defined automotive profile; map heights, not surveyed dimensions')))
    return profiles,side_count
