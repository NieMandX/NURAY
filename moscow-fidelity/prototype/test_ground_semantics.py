from semantics import classify,audit
from build import MATERIALS

rules={'Beach_place':('land-cover',24),'Neom_bike_road_area':('cycling',19),
       'Immersive_park_polygon_violet':('pedestrian',23),
       'Runway_quarter':('air-traffic',1),'Workout_place':('land-cover',1),
       'Racecourse_place':('land-cover',1)}
rows=[]
for layer,(purpose,material) in rules.items():
    s=classify(layer,{'db_road_part':'roadbed_flat'},'polygon')
    assert s['status']=='built' and s['kind']=='land' and s['purpose']==purpose
    assert s['material']==material and material<len(MATERIALS)
    rows.append(dict(id=layer,layer=layer,semantics=s))
for layer in ('Background','Supplementary_quarter','Airport_place'):
    s=classify(layer,{'db_road_part':'roadbed_flat'},'polygon')
    assert s['status']=='non-rendering' and s['material'] is None and 'kind' not in s
    rows.append(dict(id=layer,layer=layer,semantics=s))
assert audit(rows)['passed']
s=classify('Unknown_new_road',{'db_road_part':'roadbed_flat'},'polygon')
assert not audit([dict(id='unknown',layer='Unknown_new_road',semantics=s)])['passed']
print('Passed: explicit beach/cycle/sport/runway materials, map-only areas, unchanged rejection of unknown structural classes.')
