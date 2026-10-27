"""Audit passage floors by physical height as well as source surface class."""
import numpy as np
import shapely as sh
from transitions import below

def physical_gate(gate,floors,peers,connector=None):
    """A bent mouth's buffer can extend outside both carriageways.

    Audit the actual connected floor area, including an explicit source-gap
    connector. Lateral concrete outside that area is not a crossing barrier.
    Do not buffer the support or relax the obstruction/height tolerances.
    The separate full 3D interface audit still checks approach volumes.
    """
    pieces=[s['poly'] for s in (*floors,*peers)]
    if connector is not None:pieces.append(sh.geometry.shape(connector))
    return gate.intersection(sh.union_all(pieces)) if pieces else gate

def is_landing(surface, connection):
    peer=connection['peerKind']
    if peer not in ('pedestrian_ground','railway_ground'):
        return surface['kind']==peer and (connection['peerLevel'] is None or surface['tiers']==connection['peerLevel'])
    if surface.get('owner') in connection['sourceParents']:
        return False
    if surface['kind'] in ('land','curb_top'):
        return surface['tiers']==[0]
    if peer=='railway_ground':
        return surface['kind']=='roadbed_flat' and surface['tiers']==[0]
    # 2GIS also represents terrain-level walking landings as the flat part of
    # a staircase or underpass. Tier zero alone is insufficient: retain the
    # pedestrian purpose and check the actual height at every mouth sample.
    return (surface['kind'].startswith('roadbed') and surface.get('transport')=='pedestrian') or (surface['kind']=='roadbed_flat' and surface['tiers']==[0])

def landing_offset(surface,connection,land_raise):
    # This offset is added to the passage floor before comparing with the
    # landing. Walking geometry already includes the raised sidewalk datum;
    # convert it DOWN when the only landing witness is the underlying asphalt.
    if connection['peerKind']=='pedestrian_ground' and surface['kind']=='roadbed_flat' and surface.get('transport')!='pedestrian':return -land_raise
    return land_raise if connection['peerKind']=='railway_ground' and surface['kind'] in ('land','curb_top') else 0.

def obstruction_area(gate, covers, floors, tolerance=.003):
    """A coplanar walking landing is not a raised obstruction.

    Restrict each height plane to its own cell's small gate neighbourhood;
    extrapolating a distant sloping descent would create false clearances.
    Solids above the floor remain subject to the serialized 3D volume audit.
    """
    blocked=[]
    for cover in covers:
        piece=cover['poly'].intersection(gate)
        if piece.area<1e-12:continue
        clear=[]
        for floor in floors:
            local=piece.intersection(floor['poly'].buffer(.002))
            if local.area<1e-12:continue
            # below() retains points where the first affine field <= limit.
            clear.append(below(local,np.asarray(cover['plane'])-floor['plane'],tolerance))
        blocked.append(piece.difference(sh.union_all(clear) if clear else sh.Polygon()))
    return sh.union_all(blocked).area if blocked else 0.
