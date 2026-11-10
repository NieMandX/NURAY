"""Refresh source-confirmed walking mouths before constructing their solids."""
import hashlib,json
import numpy as np
import shapely as sh
from prepare_passage_clearance import discover_ground
from transitions import interface_coverage


def refresh_connections(city):
    connections,interfaces=discover_ground(city)
    old=[c for c in city['gradeConnections'] if c.get('peerKind')=='pedestrian_ground']
    ids={c['id'] for c in old}
    city['gradeConnections']=[c for c in city['gradeConnections'] if c.get('peerKind')!='pedestrian_ground']+connections
    city['roadInterfaces']=[r for r in city['roadInterfaces'] if not any(e['kind']=='pedestrian_ground' for e in r['ends'])]+interfaces
    city['relationships']=[r for r in city['relationships'] if not (r.get('type')=='grade-connection' and r.get('owner') in ids)]
    city['relationships'].extend(dict(type='grade-connection',owner=c['id'],parents=c['sourceParents']+c['peerParents'],
        evidence=c['evidence'],connectorAreaM2=0.) for c in connections)
    coverage=interface_coverage(city['roadInterfaces'],city['gradeConnections'],1e-5)
    assert coverage['passed'],coverage
    return old,connections,coverage


def geometric_key(connection):
    # Ordinal IDs and evidence wording are not geometry dependencies.
    keys=('kind','peerKind','transport','level','sourceParents','peerParents','mouthGeometry',
          'landingGeometry','connectorGeometry','relativeHeightsM','atGround','datumPolicy')
    return json.dumps({k:connection[k] for k in keys if k in connection},sort_keys=True,separators=(',',':'))


def connection_digest(connections):
    return hashlib.sha256('\n'.join(sorted(map(geometric_key,connections))).encode()).hexdigest()


def affected_profiles(profiles,old,new):
    before={geometric_key(c):c for c in old};after={geometric_key(c):c for c in new}
    changed=[c for key,c in before.items() if key not in after]+[c for key,c in after.items() if key not in before]
    parents={owner for c in changed for owner in c['sourceParents']}
    # Include concrete beside a newly exposed landing, at every physical level.
    # The structural builder then uses real heights to keep elevated crossings.
    reach=max((p['sideOverhangM']*4 for p in profiles),default=4.)+.0001
    regions=[sh.geometry.shape(c[k]).buffer(reach) for c in changed
             for k in ('mouthGeometry','landingGeometry') if c.get(k)]
    region=sh.union_all(regions)
    selected={i for i,p in enumerate(profiles) if parents.intersection(p['sourceParents']) or
              sh.geometry.shape(p['asphaltGeometry']).intersects(region)}
    # An owner can span several physically separated sheets. Keep its complete
    # source membership so sheet partitioning never sees a truncated owner.
    while True:
        owners={o for i in selected for o in profiles[i]['sourceParents']}
        expanded=selected|{i for i,p in enumerate(profiles) if owners.intersection(p['sourceParents'])}
        if expanded==selected:break
        selected=expanded
    return sorted(selected),changed


def position_keys(words):
    """Orientation-independent exact Float32 triangle positions, no XY guesses."""
    xyz=np.ascontiguousarray(words[:,:,:3],dtype='<u4')
    # +/- zero are the same position after GLB serialization.
    xyz[(xyz&np.uint32(0x7fffffff))==0]=0
    vertices=xyz.view('V12').reshape(-1,3)
    return np.sort(vertices,axis=1).copy().view('V36').reshape(-1)


def replacement_mask(words,expected):
    return np.isin(position_keys(words),expected)


def serialized_words(faces,origin,material):
    from transport_ground import triangle_words
    words=triangle_words(faces,origin,material)
    xyz=words.view('<f4')[:,:,:3]
    # Exactly the existing packer's Float32 collapse predicate. Faces discarded
    # by serialization cannot occur in the canonical triangle inventory.
    keep=np.linalg.norm(np.cross(xyz[:,1]-xyz[:,0],xyz[:,2]-xyz[:,0]),axis=1)>1e-9
    return words[keep]
