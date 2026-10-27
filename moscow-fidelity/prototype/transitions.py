"""Road mouths are connections between physical levels, not land boundaries."""
from itertools import combinations
import numpy as np
import shapely as sh
from shapely.geometry import Polygon,LineString,Point,mapping

MAX_JOIN_GAP = .50
ENTRY_HEIGHT_TOLERANCE = .002


def parts(g,kind='Polygon'):
    if g.is_empty:return []
    if g.geom_type==kind:return [g]
    return [p for sub in getattr(g,'geoms',[]) for p in parts(sub,kind)]


def union(gs,precision):
    return sh.union_all(gs,grid_size=precision) if gs else Polygon()


def shared_interfaces(candidates, extent, precision, z_at):
    """Source topology across road classes/tiers, independent of emitted solids.

    A common boundary is a connection only when the road interiors are on
    opposite sides and both source height fields agree along the entire edge.
    XY crossings, point contacts and storage cuts cannot establish a connection.
    No coordinate-specific exception or road-class pairing is used.
    """
    roads=[r for r in candidates if r['kind']=='road']
    grouped=[]
    for kind,level in sorted({(r['part'],tuple(r['tiers'])) for r in roads}):
        rows=[r for r in roads if r['part']==kind and tuple(r['tiers'])==level]
        patches=[(sh.set_precision(p,precision),np.zeros(3) if kind=='roadbed_flat' else c,r['id'])
                 for r in rows for p,c in r['patches']]
        grouped.append(dict(kind=kind,level=list(level),rows=rows,
            poly=union([r['poly'] for r in rows],precision),patches=patches,
            tree=sh.STRtree([p for p,c,owner in patches])))
    result=[]
    for a,b in combinations(grouped,2):
        if a['kind']==b['kind']=='roadbed_flat':continue
        common=sh.intersection(a['poly'].boundary,b['poly'].boundary,grid_size=precision)
        common=common.difference(extent.boundary.buffer(precision*5))
        accepted=[]
        for line in parts(common,'LineString'):
            # Node at every source height patch, not only the footprint corners.
            for i in a['tree'].query(line,predicate='intersects'):
                ap,ac,_=a['patches'][int(i)]
                edge=sh.intersection(line,ap,grid_size=precision)
                for j in b['tree'].query(edge,predicate='intersects'):
                    bp,bc,_=b['patches'][int(j)]
                    for piece in parts(sh.intersection(edge,bp,grid_size=precision),'LineString'):
                        xy=np.asarray(piece.coords)[:,:2]
                        if np.max(abs(z_at(ac,xy)-z_at(bc,xy)))>ENTRY_HEIGHT_TOLERANCE:continue
                        for aa,bb in zip(xy,xy[1:]):
                            length=np.linalg.norm(bb-aa)
                            if length<precision*5:continue
                            normal=np.array([-(bb-aa)[1],(bb-aa)[0]])/length
                            midpoint=(aa+bb)/2
                            left=Point(midpoint+normal*.001);right=Point(midpoint-normal*.001)
                            sides=(a['poly'].covers(left),a['poly'].covers(right),
                                   b['poly'].covers(left),b['poly'].covers(right))
                            if sides in [(True,False,False,True),(False,True,True,False)]:
                                accepted.append(LineString([aa,bb]))
        merged=sh.line_merge(union(accepted,precision)) if accepted else LineString()
        for line in parts(merged,'LineString'):
            if line.length<.25:continue
            heights=[];parents=[]
            for group in [a,b]:
                hs=[];ids=set()
                for xy in np.asarray(line.coords)[:,:2]:
                    indices=group['tree'].query(Point(xy).buffer(precision*5),predicate='intersects')
                    vals=[float(z_at(group['patches'][int(i)][1],xy)) for i in indices]
                    if not vals or max(vals)-min(vals)>ENTRY_HEIGHT_TOLERANCE:
                        raise ValueError('Ambiguous source heights at road interface')
                    hs.append(sum(vals)/len(vals))
                    ids.update(group['patches'][int(i)][2] for i in indices)
                heights.append(hs);parents.append(sorted(ids))
            height=(np.asarray(heights[0])+heights[1])/2
            result.append(dict(id=f'road-interface:{len(result)}',mouthGeometry=mapping(line),
                mouthWidthM=line.length,relativeHeightsM=height.tolist(),
                atGround=bool(np.max(abs(height))<=ENTRY_HEIGHT_TOLERANCE),
                ends=[dict(kind=g['kind'],level=g['level'],parents=ids) for g,ids in zip([a,b],parents)],
                maxHeightMismatchM=float(np.max(abs(np.asarray(heights[0])-heights[1]))),
                evidence='opposite source road interiors; shared boundary and matching relative heights'))
    return result


def interface_coverage(interfaces, connections, precision):
    """Every source interface involving a constructed ramp needs BOTH owners.

    Run independently of the accepted mouth list. A missed class transition
    must block export even when all previously found mouths pass their checks.
    """
    checks=[]
    for interface in interfaces:
        line=sh.geometry.shape(interface['mouthGeometry'])
        for end in interface['ends']:
            if end['kind'] not in ['roadbed_overpass','roadbed_tunnel_descent']:continue
            matches=[sh.geometry.shape(c['mouthGeometry']) for c in connections
                     if c['kind']==end['kind'] and c['level']==end['level']]
            covered=union(matches,precision).buffer(precision*5)
            missing=line.difference(covered).length
            checks.append(dict(interface=interface['id'],kind=end['kind'],level=end['level'],
                missingM=missing,passed=bool(missing<.001)))
    return dict(passed=all(c['passed'] for c in checks),checks=checks,
                sourceInterfaces=len(interfaces),scope='all source shared-height road interfaces, not only discovered ground mouths')


def discover(candidates,ground,extent,precision,z_at,interfaces=None):
    """Connect road classes by topology/height, then resolve small ground gaps.

    Exact source contacts work in either direction and at any relative height.
    The older zero-height ground rule is retained only for non-touching ground
    mouths (up to MAX_JOIN_GAP), with an explicit asphalt connector.
    """
    ramps=[r for r in candidates if r['kind']=='road' and r['part'] in
           ['roadbed_overpass','roadbed_tunnel_descent']]
    connections=[];connectors=[]
    # These masks do not depend on the mouth. A large city road union can take
    # seconds to buffer; repeating it for each entry makes region builds scale
    # with the product of road complexity and number of entries.
    ground_join_mask=ground.buffer(MAX_JOIN_GAP+precision*3)
    extent_edge=extent.boundary.buffer(precision*5)
    if interfaces is None:interfaces=shared_interfaces(candidates,extent,precision,z_at)
    for interface in interfaces:
        # Ground source contours may coincide with only half of a complete
        # mouth and overlap the rest. Let the ground rule below recover that
        # entire mouth; splitting it here would reintroduce independent cuts
        # at an internal node of the concrete shoulders. Coverage still audits
        # every exact ground contact in the source interface inventory.
        if any(end['kind']=='roadbed_flat' for end in interface['ends']):continue
        for index,end in enumerate(interface['ends']):
            if end['kind'] not in ['roadbed_overpass','roadbed_tunnel_descent']:continue
            peer=interface['ends'][1-index]
            connections.append(dict(id=f'grade-connection:{len(connections)}',
                interfaceId=interface['id'],kind=end['kind'],level=end['level'],
                mouthGeometry=interface['mouthGeometry'],mouthWidthM=interface['mouthWidthM'],
                relativeHeightsM=interface['relativeHeightsM'],atGround=interface['atGround'],
                sourceParents=end['parents'],peerParents=peer['parents'],peerKind=peer['kind'],peerLevel=peer['level'],
                groundParents=peer['parents'] if peer['kind']=='roadbed_flat' else [],
                connectorGeometry=mapping(Polygon()),connectorAreaM2=0.,maximumSourceGapM=0.,
                heightToleranceM=ENTRY_HEIGHT_TOLERANCE,evidence=interface['evidence']))
    for kind,level in sorted({(r['part'],tuple(r['tiers'])) for r in ramps}):
        rows=[r for r in ramps if r['part']==kind and tuple(r['tiers'])==level]
        footprint=union([r['poly'] for r in rows],precision)
        footprint_boundary=footprint.boundary
        edges=[]
        for r in rows:
            for poly,c in r['patches']:
                edge=footprint_boundary.intersection(poly.buffer(precision*2))
                for line in parts(edge,'LineString'):
                    xy=np.asarray(line.coords)[:,:2]
                    # An exterior polyline can contain both the transverse
                    # zero-height mouth and rising/falling lateral edges.
                    for a,b in zip(xy,xy[1:]):
                        if np.linalg.norm(b-a)<.05 or np.max(abs(z_at(c,[a,b])))>ENTRY_HEIGHT_TOLERANCE:continue
                        segment=LineString([a,b]).difference(extent_edge)
                        if segment.length>.05:edges.extend(parts(segment,'LineString'))
        known=union([sh.geometry.shape(c['mouthGeometry']) for c in connections
                     if c['kind']==kind and tuple(c['level'])==level],precision)
        edges=[e.difference(known.buffer(precision*5)) for e in edges]
        merged=sh.line_merge(sh.union_all(edges,grid_size=precision)) if edges else LineString()
        for line in parts(merged,'LineString'):
            if line.length<.25:continue
            # A whole transverse mouth must be near the ground carriageway.
            if line.difference(ground_join_mask).length>.001:continue
            ids=[r['id'] for r in rows if r['poly'].distance(line)<precision*5]
            parents=[r['id'] for r in candidates if r['kind']=='road' and r['part']=='roadbed_flat'
                     and r['poly'].distance(line)<=MAX_JOIN_GAP+precision*3]
            if not parents:continue
            patches=[]
            coords=np.asarray(line.coords)[:,:2]
            for a,b in zip(coords,coords[1:]):
                n=max(1,int(np.ceil(np.linalg.norm(b-a))))
                samples=np.linspace(a,b,n+1)
                for aa,bb in zip(samples,samples[1:]):
                    contacts=[]
                    for xy in [aa,bb]:
                        p=Point(xy);nearest=sh.shortest_line(p,ground)
                        contacts.append(xy if nearest.is_empty else np.asarray(nearest.coords)[-1,:2])
                    patch=sh.make_valid(Polygon([aa,bb,contacts[1],contacts[0]]))
                    patches.extend(parts(patch.difference(ground).difference(footprint)))
            patch=sh.set_precision(union(patches,precision),precision)
            connection=dict(id=f'grade-connection:{len(connections)}',kind=kind,level=list(level),
                mouthGeometry=mapping(line),mouthWidthM=line.length,sourceParents=ids,
                groundParents=parents,peerParents=parents,peerKind='roadbed_flat',peerLevel=None,
                atGround=True,relativeHeightsM=[0.]*len(line.coords),
                connectorGeometry=mapping(patch),connectorAreaM2=patch.area,
                maximumSourceGapM=MAX_JOIN_GAP,heightToleranceM=ENTRY_HEIGHT_TOLERANCE,
                evidence='source zero-relative-height mouth adjacent to ground road; no XY-only overpass connection')
            connections.append(connection)
            if patch.area>1e-9:connectors.append((connection,patch))
    # A broad zero-height edge can contain separate carriageways with a median
    # between them. The whole-mouth proximity heuristic must not discard the
    # exact source contacts on either side merely because the median is land.
    # Prefer the complete mouths already found; recover only uncovered source
    # interfaces, preserving their full noded width and source provenance.
    for interface in interfaces:
        flat=[e for e in interface['ends'] if e['kind']=='roadbed_flat']
        if not flat:continue
        peer=flat[0];end=next(e for e in interface['ends'] if e is not peer)
        if end['kind'] not in ['roadbed_overpass','roadbed_tunnel_descent']:continue
        line=sh.geometry.shape(interface['mouthGeometry'])
        known=union([sh.geometry.shape(c['mouthGeometry']) for c in connections
                     if c['kind']==end['kind'] and c['level']==end['level']],precision)
        if line.difference(known.buffer(precision*5)).length<.001:continue
        connections.append(dict(id=f'grade-connection:{len(connections)}',interfaceId=interface['id'],
            kind=end['kind'],level=end['level'],mouthGeometry=interface['mouthGeometry'],mouthWidthM=line.length,
            relativeHeightsM=interface['relativeHeightsM'],atGround=interface['atGround'],
            sourceParents=end['parents'],peerParents=peer['parents'],groundParents=peer['parents'],
            peerKind=peer['kind'],peerLevel=peer['level'],connectorGeometry=mapping(Polygon()),connectorAreaM2=0.,
            maximumSourceGapM=0.,heightToleranceM=ENTRY_HEIGHT_TOLERANCE,
            evidence=interface['evidence']+'; separate source-confirmed carriageway mouth'))
    return connections,connectors


def below(g,c,limit):
    """Clip a polygon by the affine height inequality a*x+b*y+d <= limit."""
    if g.is_empty:return g
    normal=np.array(c[:2],copy=True);size=float(np.linalg.norm(normal))
    if size<1e-12:return g if c[2]<=limit else Polygon()
    x0,y0,x1,y1=g.bounds;center=np.array([(x0+x1)/2,(y0+y1)/2])
    normal/=size;tangent=np.array([-normal[1],normal[0]])
    contact=center-normal*((np.dot(c[:2],center)+c[2]-limit)/size)
    radius=max(x1-x0,y1-y0,1)+np.linalg.norm(contact-center)+1
    cutter=Polygon([contact+tangent*radius,contact-tangent*radius,
                    contact-tangent*radius-normal*radius*2,contact+tangent*radius-normal*radius*2])
    return g.intersection(cutter)


def terrain_cut(profiles,surfaces,dem,demtree,connections,raise_m,depth_m,precision):
    """Remove raised ground where a connected ramp slab occupies that surface.

    The underside's clearance decides where ground resumes under the bridge.
    Consequently high spans preserve their ground; no fixed-length trench is
    guessed. Asphalt and concrete shoulder cells use the same test.
    """
    cuts=[];low_groups={};profile_groups={}
    for profile in profiles:
        parents=set(profile['sourceParents'])
        # Rail ribbons share the raised ground/ballast datum (+.12 m).
        # Their ground support remains below the track, unlike a car road
        # whose zero-height asphalt would be blocked by raised pavement.
        key=profile.get('transport','vehicle')
        profile_groups[key]=profile
        rows=[s for s in surfaces if s['kind']=='roadbed_overpass'
              and s['owner'] in parents
              and s.get('transport','vehicle')==profile.get('transport','vehicle')]
        supports=rows+[dict(poly=sh.geometry.shape(s['geometry']),plane=np.asarray(s['heightPlane']))
                       for s in profile['extensionHeightCells']]
        low=[]
        for s in supports:
            for i in demtree.query(s['poly'],predicate='intersects'):
                piece=s['poly'].intersection(dem[int(i)][0])
                clipped=below(piece,s['plane']-dem[int(i)][1],raise_m+profile.get('deckDepthM',depth_m))
                if clipped.area>1e-9:low.extend(parts(clipped))
        low_groups.setdefault(key,[]).extend(low)
    # Structural sheets can be split at an elevated source-continuous joint.
    # Their ground cut remains connected across that joint. Derive low solids
    # from each sheet's own height/depth first, then join the planar cut; high
    # neighbouring decks never enter this low-volume union.
    for key,low in low_groups.items():
        transport=key
        mouths=[sh.geometry.shape(r['mouthGeometry']) for r in connections
                if r['kind']=='roadbed_overpass' and r.get('atGround',True)
                and not r.get('retainGroundSupport',False) and r.get('transport','vehicle')==transport]
        if not mouths:continue
        for p in parts(union(low,precision)):
            if any(p.distance(line)<precision*5 for line in mouths):cuts.append(p)
    return sh.set_precision(union(cuts,precision),precision)
