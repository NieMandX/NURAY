"""Height-continuous structural sheets, independent of source drawing tiers.

Merge adjacent source owners when their actual shared heights agree, but never
merge a mouth owner with a nearby, vertically separate branch that its cut
could reach. Ordinary joins far from mouths retain their continuous profile.
If such a branch reconnects farther away, retain that real joint explicitly.
"""
from collections import defaultdict
import json
import numpy as np
import shapely as sh


def lines(g):
    if g.is_empty:return []
    if g.geom_type=='LineString':return [g]
    return [p for sub in getattr(g,'geoms',[]) for p in lines(sub)]


def sheet_entries(records,footprint,precision):
    """Split a multi-owner source mouth at its actual sheet boundary."""
    result=[];boundary=footprint.boundary.buffer(precision*5)
    for record in records:
        original=sh.geometry.shape(record['mouthGeometry'])
        if boundary.covers(original):result.append(record);continue
        xy=np.asarray(original.coords)[:,:2]
        stations=np.r_[0,np.cumsum(np.linalg.norm(np.diff(xy,axis=0),axis=1))]
        values=record.get('relativeHeightsM',[0.]*len(xy))
        # The buffer is only a whole-mouth coincidence test. Clipping a partial
        # mouth to it would retain a tiny piece of the next owner's segment at
        # a bend, which has no valid inside/outside on this sheet.
        clipped=sh.intersection(original,footprint.boundary,grid_size=precision)
        for index,line in enumerate(lines(clipped)):
            if line.length<=precision*10:continue
            result.append({**record,'id':f"{record.get('id','mouth')}:sheet-part:{index}",
                'mouthGeometry':sh.geometry.mapping(line),
                'relativeHeightsM':[float(np.interp(original.project(sh.Point(p)),stations,values)) for p in line.coords]})
    return result


def joined_portal_datums(datums,originals,footprint,precision):
    """Node extended shoulder mouths at their common physical corners.

    Source heights remain fixed on the original mouths. Where only their
    shoulder extensions meet, the nearer original mouth owns the corner.
    Both incident profiles then interpolate to that single height instead of
    switching between unrelated clamped endpoint heights within micrometres.
    """
    tree=sh.STRtree([d[0] for d in datums]);nodes=defaultdict(list);events={}
    for i,(line,stations,values) in enumerate(datums):
        for j in tree.query(line,predicate='intersects'):
            j=int(j)
            if j<=i:continue
            crossing=line.intersection(datums[j][0])
            for xy in sh.get_coordinates(crossing):
                point=sh.Point(xy)
                if footprint.contains(point):continue
                key=tuple(np.round(xy,8))
                event=events.setdefault(key,dict(point=point,indices=set()))
                event['indices'].update((i,j))
    # Offsetting independently snapped source edges can put the same physical
    # corner a few micrometres apart. Resolve the whole precision-sized node,
    # not several incompatible height anchors on almost the same station.
    event_rows=list(events.values());event_tree=sh.STRtree([e['point'] for e in event_rows])
    roots=list(range(len(event_rows)))
    def root(i):
        while roots[i]!=i:roots[i]=roots[roots[i]];i=roots[i]
        return i
    for i,event in enumerate(event_rows):
        for j in event_tree.query(event['point'],predicate='dwithin',distance=precision*5):
            a,b=root(i),root(int(j))
            if a!=b:roots[max(a,b)]=min(a,b)
    clustered={}
    for i,event in enumerate(event_rows):
        combined=clustered.setdefault(root(i),dict(point=event_rows[root(i)]['point'],indices=set()))
        combined['indices'].update(event['indices'])
    for event in clustered.values():
        point=event['point'];candidates=[]
        # Resolve every incident mouth together. Pairwise winners can give
        # different heights to the same corner when three extensions meet.
        for k in sorted(event['indices']):
            curve,ss,vv=datums[k];station=curve.project(point)
            candidates.append((originals[k].distance(point),k,float(np.interp(station,ss,vv))))
        winner=min(candidates,key=lambda r:(r[0],r[1]))
        source_values=[r[2] for r in candidates if r[0]<precision*5]
        if source_values and max(source_values)-min(source_values)>.001:
            raise ValueError('Source mouths meet at incompatible heights')
        for k in sorted(event['indices']):nodes[k].append((datums[k][0].project(point),winner[2]))
    result=[]
    for i,(line,stations,values) in enumerate(datums):
        anchors=[*(zip(stations[1:-1],values[1:-1])),*nodes[i]]
        anchors.sort(key=lambda r:r[0]);merged=[]
        for station,value in anchors:
            if merged and abs(station-merged[-1][0])<precision:
                if abs(value-merged[-1][1])>.001:raise ValueError('Incompatible coincident shoulder corner heights')
                continue
            merged.append((station,value))
        ss=np.array([0.,*(r[0] for r in merged),stations[-1]])
        vv=np.array([values[0],*(r[1] for r in merged),values[-1]])
        result.append((line,ss,vv))
    return result


def structural_sheets(elevated,connections,dem,demtree,precision,z_at):
    sheets=[];synthetic=[]
    # Tiers are drawing order, not a physical separation. A continuous bridge
    # can change tiers right at a fork. Its outer contour must be built once.
    def family(s):return s.get('transport','vehicle'),json.dumps(s.get('profile',{}),sort_keys=True)
    for transport,profile_rule in sorted({family(s) for s in elevated}):
        rows=[s for s in elevated if family(s)==(transport,profile_rule)]
        by_owner=defaultdict(list)
        for r in rows:by_owner[r['owner']].append(r)
        owners=sorted(by_owner);polys=[sh.union_all([r['poly'] for r in by_owner[o]],grid_size=precision) for o in owners]
        tree=sh.STRtree(polys)
        mouth_regions=defaultdict(list)
        for record in connections or []:
            if record['kind']!='roadbed_overpass' or record.get('transport','vehicle')!=transport:continue
            # A continuous bridge-to-bridge seam becomes internal after union.
            # It cannot cut a nearby branch and needs no mouth conflict region.
            if record.get('peerKind')=='roadbed_overpass':continue
            for owner in record.get('sourceParents',[]):
                if owner in by_owner:
                    width=by_owner[owner][0].get('profile',{}).get('overhang',1.)
                    mouth_regions[owner].append(sh.geometry.shape(record['mouthGeometry']).buffer(width*3,cap_style='square'))
        local_trees={o:sh.STRtree([r['poly'] for r in rs]) for o,rs in by_owner.items()}
        conflicts={i:set() for i in range(len(owners))};adjacent=[];nearby_levels=[]
        def source_height(i,xy):
            owner=owners[i];point=sh.Point(xy);rs=by_owner[owner];rt=local_trees[owner]
            j=int(rt.nearest(point));r=rs[j]
            contact=sh.shortest_line(point,r['poly'])
            q=xy if contact.is_empty else np.asarray(contact.coords)[-1,:2]
            di=int(demtree.nearest(sh.Point(q)));dj=int(demtree.nearest(point))
            # Compare the source-relative deck height on a common terrain
            # datum; extrapolating two different DEM triangles invents a split.
            return float(z_at(r['plane'],q)-z_at(dem[di][1],q)+z_at(dem[dj][1],xy))
        for i,a in enumerate(polys):
            width=by_owner[owners[i]][0].get('profile',{}).get('overhang',1.)
            # A mouth extends 2w along its tangent and cuts 2w outward. Include
            # that diagonal reach plus the neighbour's overhang, not only the
            # 2w distance between the original asphalt boundaries.
            for j in tree.query(a.buffer(width*4+precision*10),predicate='intersects'):
                j=int(j)
                if j<=i:continue
                b=polys[j];contact=sh.intersection(a.boundary,b.boundary,grid_size=precision)
                overlap=a.intersection(b)
                # Physically stacked roads must remain separate even if a
                # ramp connects their owners elsewhere in the same network.
                incompatible=False
                if overlap.area>precision**2:
                    oa,ob=owners[i],owners[j]
                    for ai in local_trees[oa].query(overlap,predicate='intersects'):
                        ar=by_owner[oa][int(ai)]
                        for bi in local_trees[ob].query(ar['poly'],predicate='intersects'):
                            br=by_owner[ob][int(bi)];piece=ar['poly'].intersection(br['poly'])
                            if piece.area<=precision**2:continue
                            xy=sh.get_coordinates(piece)
                            if np.max(abs(z_at(ar['plane'],xy)-z_at(br['plane'],xy)))>.001:
                                incompatible=True;break
                        if incompatible:break
                if incompatible:
                    conflicts[i].add(j);conflicts[j].add(i)
                    continue
                accepted=[];height_witnesses=[];shared_mismatch=False
                # Height tests use the original terrain-noded cells. Retaining
                # their nodes also preserves the exact synthetic joint datum.
                if contact.length>precision*10:
                    oa=owners[i];ob=owners[j]
                    for ai in local_trees[oa].query(contact,predicate='intersects'):
                        ar=by_owner[oa][int(ai)];edge=contact.intersection(ar['poly'])
                        for bi in local_trees[ob].query(edge,predicate='intersects'):
                            br=by_owner[ob][int(bi)]
                            for part in lines(edge.intersection(br['poly'])):
                                xy=np.asarray(part.coords)[:,:2]
                                if part.length>precision*10:
                                    if np.max(abs(z_at(ar['plane'],xy)-z_at(br['plane'],xy)))<.001:
                                        accepted.append(part);height_witnesses.append((part,ar['plane']))
                                    else:shared_mismatch=True
                # One agreeing fragment cannot prove continuity of an entire
                # owner pair. Keep incompatible shared-edge fragments in
                # separate sheets, even when the roads reconnect elsewhere.
                # The accepted fragments below still become open sheet joints.
                if shared_mismatch:
                    conflicts[i].add(j);conflicts[j].add(i)
                if accepted:
                    common=sh.line_merge(sh.union_all(accepted,grid_size=precision))
                    adjacent.append((common.length,i,j,common,height_witnesses))
                else:
                    nearby=a.boundary.intersection(b.buffer(width*4+precision*10))
                    different=[]
                    # A single shortest line can select the far end of two
                    # parallel branches, where their heights happen to agree.
                    # Inspect the complete nearby boundary, including its nodes.
                    for xy in sh.get_coordinates(sh.segmentize(nearby,max(width*.5,.1))):
                        link=sh.shortest_line(sh.Point(xy),b)
                        if link.is_empty:continue
                        # Compare both planes at the SAME point. Comparing
                        # different closest points would mistake ordinary
                        # terrain crossfall for a different structural level.
                        midpoint=(xy+np.asarray(link.coords[-1]))*.5
                        if abs(source_height(i,midpoint)-source_height(j,midpoint))>.001:
                            different.append(xy)
                    if different:nearby_levels.append((i,j,sh.MultiPoint(different)))
        def find(i):
            while parent[i]!=i:parent[i]=parent[parent[i]];i=parent[i]
            return i
        ordered=sorted(adjacent,key=lambda e:(-e[0],owners[e[1]],owners[e[2]]))
        # A partition introduces new mouths at accepted source seams. Include
        # their reach before accepting the partition, otherwise a low cut can
        # migrate one owner upstream and hit the same high branch again.
        # Conflicts grow monotonically; ordinary interior seams stay merged.
        for iteration in range(len(nearby_levels)+2):
            changed=False
            for i,j,points in nearby_levels:
                if j in conflicts[i]:continue
                regions=mouth_regions.get(owners[i],[])+mouth_regions.get(owners[j],[])
                if regions and points.intersects(sh.union_all(regions)):
                    conflicts[i].add(j);conflicts[j].add(i);changed=True
            parent=list(range(len(owners)));members={i:{i} for i in parent}
            for _,i,j,edge,witnesses in ordered:
                a=find(i);b=find(j)
                if a==b:continue
                if any(conflicts[k].intersection(members[b]) for k in members[a]):continue
                parent[b]=a;members[a]|=members.pop(b)
            if iteration and not changed:break
            for _,i,j,edge,witnesses in adjacent:
                if find(i)==find(j):continue
                for k in (i,j):
                    width=by_owner[owners[k]][0].get('profile',{}).get('overhang',1.)
                    mouth_regions[owners[k]].append(edge.buffer(width*3,cap_style='square'))
        else:raise ValueError('Structural mouth partition did not converge')
        for indices in members.values():
            sheet_rows=[r for i in sorted(indices) for r in by_owner[owners[i]]]
            level=tuple(sorted({tier for r in sheet_rows for tier in r['tiers']}))
            sheets.append((level,transport,sheet_rows))
        joints=defaultdict(list)
        for _,i,j,edge,witnesses in adjacent:
            if find(i)!=find(j):joints[tuple(sorted((find(i),find(j))))].append((edge,witnesses))
        for (left,right),edges in sorted(joints.items()):
            # One physical joint can span many source owners. Extend its ends
            # only after merging all those fragments, otherwise overlapping
            # endpoint extensions carry different clamped height datums.
            common=sh.line_merge(sh.union_all([edge for edge,w in edges],grid_size=precision))
            height_cells=[cell for edge,w in edges for cell in w]
            height_tree=sh.STRtree([edge for edge,c in height_cells])
            for line in lines(common):
                xy=np.asarray(line.coords)[:,:2];values=[]
                for point in xy:
                    hit=demtree.query(sh.Point(point),predicate='covered_by')
                    di=int(hit[0]) if len(hit) else int(demtree.nearest(sh.Point(point)))
                    j=int(height_tree.nearest(sh.Point(point)));edge,c=height_cells[j]
                    # At a multi-owner corner, an unrelated owner can touch
                    # this node too. Use the accepted shared-edge plane that
                    # proved continuity, never a nearest owner of the sheet.
                    contact=edge.interpolate(edge.project(sh.Point(point)))
                    values.append(float(z_at(c,contact.coords[0]))-float(z_at(dem[di][1],point)))
                left_owners=sorted(owners[i] for i in members[left] if polys[i].distance(line)<precision*5)
                right_owners=sorted(owners[i] for i in members[right] if polys[i].distance(line)<precision*5)
                for source,peer in [(left_owners,right_owners),(right_owners,left_owners)]:
                    level=sorted({tier for owner in source for tier in by_owner[owner][0]['tiers']})
                    synthetic.append(dict(id=f'structural-sheet-interface:{len(synthetic)}',kind='roadbed_overpass',level=list(level),
                        transport=transport,sourceParents=source,peerParents=peer,mouthGeometry=sh.geometry.mapping(line),
                        relativeHeightsM=values,atGround=bool(max(map(abs,values),default=0)<.002),
                        datumPolicy='source-shared-edge',
                        evidence='actual source shared edge and equal absolute heights; structural sheet partition only'))
        print('OVERPASS SHEETS',transport,'owners',len(owners),'sheets',len(members),'partition joints',sum(find(i)!=find(j) for _,i,j,e,w in adjacent),flush=True)
    if connections is None and not synthetic:return sheets,None
    return sheets,[*(connections or []),*synthetic]
