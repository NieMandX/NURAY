"""Real source regressions for returning and consecutive shoulder mouths."""
from pathlib import Path
from collections import defaultdict
import json
import numpy as np
import shapely as sh
from shapely.affinity import affine_transform
from overpasses import build
from build import triangulate,z_at,plane,GRID

cases=json.loads((Path(__file__).parent/'fixtures/overpass-extended-mouth-heights.json').read_text())
for case in cases:
    for degrees in (0,31):
        angle=np.radians(degrees)
        rotation=np.array([[np.cos(angle),-np.sin(angle)],[np.sin(angle),np.cos(angle)]])
        centre=np.mean(np.asarray(case['extent']).reshape(2,2),axis=0)
        offset=np.zeros(2) if not degrees else np.array([37.,-19.])-rotation@centre
        transform=[*rotation[0],*rotation[1],*offset]
        def geometry(g,precision):
            return sh.set_precision(affine_transform(sh.geometry.shape(g),transform),precision,mode='pointwise')
        def coefficient(c):
            slope=rotation@np.asarray(c[:2]);return np.r_[slope,c[2]-slope@offset]
        def row(r):
            return {**{k:v for k,v in r.items() if k not in ('geometry','precision','plane')},
                    'poly':geometry(r['geometry'],r['precision']),'plane':coefficient(r['plane'])}
        rows=[row(r) for r in case['surfaces']]
        if degrees:rows.reverse()
        floors=[row(r) for r in case['floors']]
        dem=[(geometry(r['geometry'],r['precision']),coefficient(r['plane'])) for r in case['dem']]
        connections=[{**r,'mouthGeometry':sh.geometry.mapping(affine_transform(sh.geometry.shape(r['mouthGeometry']),transform))}
                     for r in case['connections']]
        extent=affine_transform(sh.box(*case['extent']),transform)
        profiles,_=build(rows,dem,sh.STRtree([p for p,c in dem]),defaultdict(list),extent,GRID,
            triangulate,z_at,plane,connections,prepartitioned=True,collision_floors=floors)
        assert len(profiles)==1
        p=profiles[0]
        assert p['passed'],(case['name'],degrees,p)
        assert p['maxAsphaltShoulderHeightMismatchM']<.001
        assert p['maxGroundShoulderJoinErrorM']<.001
        assert p['raisedConcreteInEntryPassageM2']<.0001
        assert p['uncoveredDeckSidesM']<.001 and p['uncoveredParapetSidesM']<.001
        print('Extended-mouth regression passed:',case['name'],degrees,
              p['maxAsphaltShoulderHeightMismatchM'],p['maxGroundShoulderJoinErrorM'])
