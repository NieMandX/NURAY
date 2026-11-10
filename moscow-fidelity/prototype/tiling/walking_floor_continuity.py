"""Source height witnesses where a ground landing meets a rising walking slab.

Drawing tiers need not agree at a physically continuous landing. The visual
floor edges can also differ slightly from routing nodes. Accept only a shared
zero-height edge, opposing source interiors and the established source mouth
alignment bound; an unrelated/high XY crossing supplies no floor witness.
"""
import numpy as np
import shapely as sh
from transitions import parts, ENTRY_HEIGHT_TOLERANCE
from pedestrian import MOUTH_NODE_ALIGNMENT
from build import z_at


class WalkingFloorContinuity:
    def __init__(self, rows):
        self.rows = [r for r in rows if r['transport'] == 'pedestrian'
                     and r['part'] in ('roadbed_overpass', 'roadbed_tunnel_descent')]
        self.tree = sh.STRtree([r['poly'] for r in self.rows])

    def owners(self, mouth, source, existing):
        result = set()
        near = mouth.buffer(MOUTH_NODE_ALIGNMENT, cap_style='flat')
        mouth_segments = [(np.asarray(a), np.asarray(b))
                          for a, b in zip(mouth.coords, list(mouth.coords)[1:])]
        for index in self.tree.query(near, predicate='intersects'):
            row = self.rows[int(index)]
            if row['id'] in existing:
                continue
            for patch, plane in row['patches']:
                for ring in (patch.exterior, *patch.interiors):
                    xy = np.asarray(ring.coords)[:, :2]
                    for a, b in zip(xy, xy[1:]):
                        length = np.linalg.norm(b - a)
                        if length < .25 or np.max(abs(z_at(plane, [a, b]))) > ENTRY_HEIGHT_TOLERANCE:
                            continue
                        edge = sh.LineString([a, b])
                        parallel = [sh.LineString([x, y]).buffer(MOUTH_NODE_ALIGNMENT, cap_style='flat')
                                    for x, y in mouth_segments if np.linalg.norm(y-x) > 1e-8
                                    and abs(np.dot(b-a, y-x))/(length*np.linalg.norm(y-x)) > .98]
                        if not parallel:
                            continue
                        # Only a real outside edge, not an internal strip seam.
                        normal = np.array([-(b-a)[1], (b-a)[0]]) / length
                        for contact in parts(edge.intersection(sh.union_all(parallel)), 'LineString'):
                            if contact.length < .25:
                                continue
                            midpoint = np.asarray(contact.interpolate(.5, normalized=True).coords[0])
                            probe = MOUTH_NODE_ALIGNMENT + .05
                            left, right = sh.Point(midpoint + normal*probe), sh.Point(midpoint - normal*probe)
                            opposing = ((row['poly'].covers(left) and source.covers(right))
                                        or (row['poly'].covers(right) and source.covers(left)))
                            if opposing:
                                result.add(row['id'])
        return result
