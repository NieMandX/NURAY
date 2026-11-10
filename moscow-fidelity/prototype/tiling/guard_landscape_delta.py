"""Conservative semantic change envelope, without re-unioning shared masks.

A fixed-grid union of a whole city can change its rounding when one operand
changes. Comparing two such unions invents distant changes to identical
operands. Instead, union each operand's difference and subtract only areas
proved protected in both versions. Every real change is inside this envelope.
"""
import shapely as sh
from transitions import parts
from passage_space import connected_approach


def change_envelope(pairs):
    changed=[];common=[];different=0
    for before,after in pairs:
        if before.equals(after):
            common.extend(parts(before));continue
        different+=1
        changed.append(before.symmetric_difference(after))
        common.extend(parts(before.intersection(after)))
    if not changed:return sh.Polygon(),dict(changedOperands=0,rawAreaM2=0,sharedAreaM2=0)
    raw=sh.union_all(changed)
    tree=sh.STRtree(common)
    hits=tree.query(raw,predicate='intersects')
    shared=sh.union_all([common[int(i)] for i in hits])
    result=raw.difference(shared)
    return result,dict(changedOperands=different,rawAreaM2=raw.area,
                       sharedAreaM2=raw.intersection(shared).area)


def guard_reserve_envelope(city,walls):
    before=city['tunnelWalls']['groups'];after=walls['groups']
    assert len(before)==len(after),'Retaining groups changed: require full landscape repartition'
    pairs=[]
    for a,b in zip(before,after):
        assert (a.get('transport'),a.get('level'),a.get('sourceStyleId'))==(b.get('transport'),b.get('level'),b.get('sourceStyleId'))
        for key in ('bandGeometry','portalHeaders'):
            ga=a[key] if key=='bandGeometry' else a[key]['bandGeometry']
            gb=b[key] if key=='bandGeometry' else b[key]['bandGeometry']
            pairs.append((sh.geometry.shape(ga).buffer(.15),sh.geometry.shape(gb).buffer(.15)))
    for c in city['gradeConnections']:
        if not (c.get('atGround') and c.get('peerKind')=='pedestrian_ground' and c.get('landingGeometry')):continue
        original=sh.geometry.shape(c['landingGeometry'])
        selected=connected_approach(sh.geometry.shape(c['mouthGeometry']),original)
        pairs.append((original,selected))
    # Other road/rail reserve operands are identical and need not be subtracted:
    # omitting their shared protection only makes the envelope more conservative.
    return change_envelope(pairs)
