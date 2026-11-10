"""Shared ground approaches, resolved before walls, planting and tile clipping.

Only a confirmed zero-level connection creates a landing. On the structure
side the source floor keeps its real, possibly curved contour; on the ground
side a full-mouth-width apron takes precedence over boundary decorations.
"""
import numpy as np
import shapely as sh
from transitions import parts,union

APPROACH_LENGTH=1.10  # Reconstruction default, not a surveyed dimension.
POLICY=('Confirm all level-zero walking endpoints, including clipped source fragments; '
        'reserve full source-mouth width for 1.10 m on the ground side before wall/header/planting construction; '
        'keep the actual curved floor contour inside the structure; reject sub-0.1-mm boolean remnants '
        'before extrusion; generate closed solids globally and tile last. Require full-width serialized clearance.')


def stable_area(geometry,precision):
    """Do not extrude precision-width boolean remnants into tall walls.

    A floating-precision width probe detects isolated and attached remnants.
    Its generously expanded support preserves the input boundary wherever a
    real area exists, including corners; only unsupported numerical tails are
    clipped. The minimum resolved width is ten grid units (0.1 mm normally).
    """
    # GEOS fixed-precision negative buffers can collapse a legitimate closed
    # 15 cm ring at a 50 micrometre erosion. Remove only precision metadata for
    # the diagnostic probe. Do not replace the mesh with a buffered outline.
    resolved=[]
    for p in parts(sh.make_valid(geometry)):
        core=sh.set_precision(p,0).buffer(-5*precision)
        if core.is_empty:continue
        support=core.buffer(10*precision,join_style='mitre',mitre_limit=100)
        resolved.append(p if support.covers(p) else p.intersection(support))
    return union(resolved,precision)


def connected_approach(mouth,landing,precision=1e-5):
    """Only an apron reachable from its own source mouth is a ground entry.

    Subtracting a bent floor can leave a detached island near a deep portal.
    Its size is irrelevant: it must not reserve passage through a header.
    Retain every connected component, including thin and point-connected ones.
    The contact allowance is the existing five-grid-unit source boundary one.
    """
    components=parts(landing)
    if not components:return landing
    tree=sh.STRtree(components);tolerance=precision*5
    reached=set(map(int,tree.query(mouth,predicate='dwithin',distance=tolerance)))
    pending=list(reached)
    while pending:
        i=pending.pop()
        adjacent=set(map(int,tree.query(components[i],predicate='dwithin',distance=tolerance)))-reached
        reached.update(adjacent);pending.extend(adjacent)
    if len(reached)==len(components):return landing
    retained=[p for i,p in enumerate(components) if i in reached]
    # Selection must not resnap or reshape any retained source component.
    return retained[0] if len(retained)==1 else sh.MultiPolygon(retained)


def ground_approach(mouth,footprint,precision=1e-5):
    pieces=[]
    xy=np.asarray(mouth.coords)[:,:2]
    for a,b in zip(xy,xy[1:]):
        length=np.linalg.norm(b-a)
        if length<precision*5:continue
        n=np.array([-(b-a)[1],(b-a)[0]])/length;mid=(a+b)/2
        left=footprint.covers(sh.Point(mid+n*.001))
        right=footprint.covers(sh.Point(mid-n*.001))
        if left==right:raise ValueError('Confirmed ground mouth has no unique structure side')
        direction=-n if left else n
        pieces.append(sh.Polygon([a,b,b+direction*APPROACH_LENGTH,a+direction*APPROACH_LENGTH]))
    return connected_approach(mouth,union(pieces,precision).difference(footprint),precision)


def walking_reserve(connections,precision=1e-5):
    return union([connected_approach(sh.geometry.shape(c['mouthGeometry']),
                                    sh.geometry.shape(c['landingGeometry']),precision) for c in connections
                  if c.get('atGround') and c.get('peerKind')=='pedestrian_ground'
                  and c.get('landingGeometry')],precision)


def ground_landings(connections,surfaces,precision=1e-5):
    """Confirmed exposed approaches are shared by every structural builder.

    A pedestrian or railway approach often has no roadbed polygon on its
    ground side. Keep that corridor even when the neighbouring concrete is
    another mode or drawing tier. Actual heights, not tiers, decide collision.
    """
    entries=[c for c in connections or [] if c.get('atGround') and
             c.get('peerKind') in ('pedestrian_ground','railway_ground','roadbed_flat')]
    needed={owner for c in entries if not c.get('landingGeometry') for owner in c['sourceParents']}
    by_owner={}
    for s in surfaces:
        if s['owner'] in needed and s['kind'].startswith('roadbed'):
            by_owner.setdefault(s['owner'],[]).append(s['poly'])
    result=[]
    for index,c in enumerate(entries):
        mouth=sh.geometry.shape(c['mouthGeometry'])
        if c.get('landingGeometry'):
            landing=connected_approach(mouth,sh.geometry.shape(c['landingGeometry']),precision)
        else:
            floor=union([p for owner in c['sourceParents'] for p in by_owner.get(owner,[])],precision)
            if floor.is_empty:continue
            landing=ground_approach(mouth,floor,precision)
        # Keep a small construction clearance at the mouth itself. This is
        # geometry, not an audit tolerance: all serialized checks stay strict.
        # It prevents a new return face ending exactly on the open gate.
        from shapely.ops import substring
        opening=substring(mouth,.05,mouth.length-.05) if mouth.length>.1 else mouth
        landing=union([landing,opening.buffer(.003,cap_style='flat')],precision)
        offset=.12 if c.get('peerKind')=='railway_ground' else .1 if c.get('peerKind')=='pedestrian_ground' or c.get('transport')=='pedestrian' else 0.
        result.append(dict(owner='ground-approach:'+str(c.get('id',index)),poly=landing,offset=offset))
    return result


def landing_floors(landings,dem,tree,precision=1e-5):
    """Use the already fitted terrain; never flatten a sloped approach."""
    result=[]
    for landing in landings:
        for i in tree.query(landing['poly'],predicate='intersects'):
            piece=landing['poly'].intersection(dem[int(i)][0])
            if piece.area<=precision**2:continue
            result.append(dict(owner=landing['owner'],kind='ground_approach',poly=piece,
                plane=np.asarray(dem[int(i)][1])+[0,0,landing['offset']]))
    return result
