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
    return union(pieces,precision).difference(footprint)


def walking_reserve(connections,precision=1e-5):
    return union([sh.geometry.shape(c['landingGeometry']) for c in connections
                  if c.get('atGround') and c.get('peerKind')=='pedestrian_ground'
                  and c.get('landingGeometry')],precision)
