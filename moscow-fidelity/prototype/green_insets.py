"""Restore explicit planting obscured by a generic pedestrian district.

Coordinates are the retained source triangle strips, never guessed from plants
or street furniture. Works before transport tiling and has no location IDs.
"""
import numpy as np
import shapely as sh
from landscape import parts, GREEN_RAISE
from semantics import GREEN

PRECISION=1e-5

def areal(g):
    return sh.union_all(parts(g),grid_size=PRECISION)

def strip_polygon(coordinates):
    xy=np.asarray(coordinates)[:,:2]
    if len(xy)<3:return sh.Polygon()
    tris=sh.polygons(np.stack((xy[:-2],xy[1:-1],xy[2:]),axis=1))
    return sh.union_all(tris[sh.area(tris)>1e-8],grid_size=PRECISION)

def recover(rows,features):
    owners={f['id']:f for f in features}
    eligible=[r for r in rows if r['kind']=='land' and not r.get('landscapeRole')
              and owners.get(r['owner'],{}).get('layer')=='Pedestrian_quarter']
    footprint=sh.union_all([r['poly'] for r in eligible],grid_size=PRECISION)
    candidates=[]
    for f in features:
        if f['geometryType']!='polygon' or f['layer'] not in GREEN:continue
        xy=np.asarray(f['coordinates'])[:,:2]
        if len(xy)<3 or not sh.box(*xy.min(0),*xy.max(0)).intersects(footprint):continue
        full=strip_polygon(f['coordinates']);p=areal(full.intersection(footprint))
        if p.area>1e-6:candidates.append((full.area,f['id'],p))
    claimed=sh.Polygon();patches=[]
    for _,owner,p in sorted(candidates,key=lambda t:(t[0],t[1])):
        p=areal(sh.difference(p,claimed,grid_size=PRECISION))
        if p.area<1e-6:continue
        patches.append((owner,p));claimed=sh.union_all([claimed,p],grid_size=PRECISION)
    tree=sh.STRtree([p for _,p in patches]);remaining=[];restored=[]
    for r in eligible:
        hits=tree.query(r['poly'],predicate='intersects');cut=sh.union_all([patches[i][1] for i in hits],grid_size=PRECISION)
        for p in parts(sh.difference(r['poly'],cut,grid_size=PRECISION)):
            if p.area>1e-9:remaining.append(dict(r,poly=p))
        for i in hits:
            owner,g=patches[i]
            for p in parts(sh.intersection(r['poly'],g,grid_size=PRECISION)):
                if p.area>1e-9:restored.append(dict(r,poly=p,owner=owner,material=2,
                    purpose='vegetation-cover',surfaceType='vegetation',styleId=None,
                    recoveredFromPedestrianQuarter=r['owner']))
    eligible_ids={r['id'] for r in eligible}
    rows=[r for r in rows if r['id'] not in eligible_ids]+remaining
    old_green=[]
    for r in rows:
        role=r.get('landscapeRole')
        if role not in {'green','curb','path','railway_apron'}:continue
        clean={k:v for k,v in r.items() if k not in {'landscapeRole','replacedGreenOwner'}}
        clean.update(kind='land',material=2,purpose='vegetation-cover',surfaceType='vegetation',
                     plane=r['plane']-np.array([0,0,GREEN_RAISE if role in {'green','curb'} else 0]))
        old_green.append(clean)
    return rows,old_green+restored,dict(sourceFeatures=len(patches),
        recoveredAreaM2=claimed.area,recoveredGeometry=sh.geometry.mapping(claimed),
        sourceOwners=[owner for owner,_ in patches])

def protected_ground(city):
    from passage_space import walking_reserve
    from railway_landscape import railway_reserve
    protected=[]
    protected.append(walking_reserve(city['gradeConnections']))
    protected.append(railway_reserve(city))
    for g in city['tunnelWalls']['groups']:
        protected.extend(sh.geometry.shape(g[k]['bandGeometry']).buffer(.15) if k else sh.geometry.shape(g['bandGeometry']).buffer(.15)
                         for k in ('','portalHeaders'))
    for r in city['roadInterfaces']:
        if any(e['kind']=='pedestrian_ground' for e in r['ends']):
            protected.append(sh.geometry.shape(r['mouthGeometry']).buffer(1.,cap_style='square'))
    for f in city['features']:
        if f['layer']=='Railroad_line' and (f['properties'].get('db_tiers') or [0])==[0] and len(f['coordinates'])>1:
            protected.append(sh.LineString(np.asarray(f['coordinates'])[:,:2]).buffer(1.85,cap_style='round'))
    return sh.union_all(protected,grid_size=PRECISION)
