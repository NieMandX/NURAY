"""Separate source purpose, vertical construction and appearance.

Explicit layer rules are versioned. An unknown layer never becomes asphalt by
containing the word 'road'. Deferred assets and unsupported surfaces are audited.
"""
from collections import Counter
from source_objects import BUILDING_LAYERS, INFORMATION_LAYERS, POLICY as PHYSICAL_POLICY
from cemetery_cover import LAYER as CEMETERY_LAYER, MATERIAL_INDEX as CEMETERY_MATERIAL
from pedestrian_materials import RULES as PEDESTRIAN_MATERIALS
from parking_cover import LAYER as PARKING_LAYER, MATERIAL_INDEX as PARKING_MATERIAL

ROAD_LAYERS={'Roadbed','Main_Roadbed','Gas_station_Roadbed','Parking_Roadbed',
             'Constructed_Roadbed','Intraquarter_Roadbed','WithMarking_Roadbed','Pocket_Roadbed',
             'Immersive_park_polygon_road'}
PEDESTRIAN_LAYERS={'Roadbed_overpasses','Roadbed_underpasses'}
GREEN={'Internal_lawn','Internal_forest_quarter','Forest_quarter','Flowerbed_quarter','Immersive_park_polygon_green'}
WALK={'Pedestrian_quarter','Immersive_park_polygon_pedestrian_asphalt',
      'Immersive_park_polygon_pedestrian_stone','Immersive_park_polygon_pedestrian_sand',
      'Immersive_park_polygon_pedestrian_gravel','Immersive_park_polygon_pedestrian_wood'}
COVER={'Administrative_quarter','Dwelling_quarter','Garage_place','Garage_quarter',
       'Neom_road_area','Platform_quarter','Sport_place','Sport_quarter',
       'Immersive_park_polygon_grey','Immersive_park_polygon_brown',
       'Private_quarter','Technical_quarter','Stadium_place',
       'Pier_quarter','Bridge_area','Immersive_park_polygon_background',
       'Workout_place','Racecourse_place'}
# Explicit source pavement classes, not water/grass inferred from their colour.
PARK_PAVING={
    'Immersive_park_polygon_blue':(14,'14930'),
    'Immersive_park_polygon_light_blue':(15,'362468'),
    'Immersive_park_polygon_red':(16,'755463'),
    'Immersive_park_polygon_orange':(17,'214439'),
    'Immersive_park_polygon_yellow':(18,'661644'),
    'Immersive_park_polygon_bike':(19,'156438'),
    'Immersive_park_polygon_football':(20,'651243'),
    'Immersive_park_polygon_tennis':(21,'121699'),
    'Immersive_park_polygon_basketball':(22,'734973'),
    'Immersive_park_polygon_violet':(23,'326654'),
}
VERTICAL={'roadbed_flat':'ground','roadbed_overpass':'elevated',
          'roadbed_tunnel_descent':'descent','roadbed_tunnel':'underground'}

def classify(layer,properties,geometry_type):
    part=properties.get('db_road_part')
    result=dict(purpose='unclassified',construction=VERTICAL.get(part,'ground'),
                sourcePart=part,tiers=properties.get('db_tiers') or [0],
                surface=None,styleId=None,material=None,status='deferred',rule='semantics-v2')
    if layer in INFORMATION_LAYERS:
        result.update(purpose='map-information',construction='not-applicable',status='non-rendering',rule=PHYSICAL_POLICY['rule'])
        return result
    if geometry_type=='polygon':
        if layer in {'Background','Supplementary_quarter','Airport_place'}:
            # A provider's default road_part also occurs on full-tile map
            # backgrounds, hidden helper regions and airport extent tints.
            # None supplies a physical road/floor. Retain it as evidence.
            result.update(purpose='map-background' if layer=='Background' else 'area-reference',
                          construction='not-applicable',status='non-rendering')
        elif layer==CEMETERY_LAYER:
            # A land-use tint, not evidence of a continuous raised lawn.
            result.update(purpose='land-cover',surface='cemetery-cover',
                          material=CEMETERY_MATERIAL,kind='land',rank=20,
                          status='built',rule='cemetery-cover-v1')
        elif layer==PARKING_LAYER:
            result.update(purpose='land-cover',surface='asphalt',
                          material=PARKING_MATERIAL,kind='land',rank=20,
                          status='built',rule='parking-material-v2')
        elif layer=='Beach_place':
            result.update(purpose='land-cover',surface='sand',styleId='346136',
                          material=24,kind='land',rank=50,status='built')
        elif layer=='Neom_bike_road_area':
            result.update(purpose='cycling',surface='cycle-paving',styleId='390543',
                          material=19,kind='land',rank=60,status='built')
        elif layer=='Runway_quarter':
            result.update(purpose='air-traffic',surface='aviation-paving',
                          material=1,kind='land',rank=60,status='built')
        elif layer in ROAD_LAYERS:
            result.update(purpose='motor-traffic',surface='asphalt',styleId='Roadbed_1',material=0,kind='road',rank=100,status='built')
        elif layer in PEDESTRIAN_LAYERS:
            underground=layer=='Roadbed_underpasses'
            result.update(purpose='pedestrian',surface='pedestrian-paving' if underground else 'light-paving',styleId='715927' if underground else '241413',material=7 if underground else 11,kind='road',rank=100,status='built')
        elif layer=='Transport_Roadbed':
            result.update(purpose='transport-unspecified',surface='light-transport-surface',styleId='881318',material=12,kind='road',rank=100,status='built')
        elif layer=='PhysicalBarrier_Roadbed':
            result.update(purpose='traffic-separator',surface='concrete',styleId='738945',material=9,kind='road',rank=100,status='built')
        elif layer in GREEN:
            result.update(purpose='vegetation-cover',surface='vegetation',material=2,kind='land',rank=40,status='built')
        elif layer in WALK:
            surface=layer.rsplit('_',1)[-1] if layer.startswith('Immersive') else 'paving-unspecified'
            # A pedestrian quarter describes the whole public space. Its
            # explicit planting polygons remain visible inside it; detailed
            # paving polygons still take precedence over planting.
            result.update(purpose='pedestrian',surface=surface,material=7,kind='land',rank=30 if layer=='Pedestrian_quarter' else 60,status='built')
            if layer in PEDESTRIAN_MATERIALS:
                appearance=PEDESTRIAN_MATERIALS[layer]
                result.update(material=appearance['material'],styleId=appearance['styleId'],rule='pedestrian-materials-v1')
        elif layer in COVER:
            result.update(purpose='land-cover',surface='cover-unspecified',material=1,kind='land',rank=0 if layer=='Administrative_quarter' else 20,status='built')
        elif layer in PARK_PAVING:
            material,style=PARK_PAVING[layer]
            result.update(purpose='pedestrian',surface='coloured-paving',styleId=style,material=material,kind='land',rank=60,status='built')
        elif layer.startswith('PolygonMarkings'):
            result.update(purpose='marking',status='legacy-marking')
        elif layer in {'Water_area','Pool'}:
            result.update(purpose='water',surface='water',material=13,kind='water',rank=80,status='built')
        elif layer in BUILDING_LAYERS:
            # Provider records may carry a default road_part even on buildings.
            # Their explicit class takes precedence; they are outside this pass.
            result.update(purpose='building',construction='not-applicable')
        elif part in VERTICAL:
            result.update(status='unsupported-surface')
        else:
            result.update(status='unknown')
    elif geometry_type=='polyline':
        if layer.startswith('LinearMarking'):result.update(purpose='marking',status='source-modifier' if layer in {'LinearMarking_Stop','LinearMarking_TramStop'} else 'legacy-marking')
        elif part in {'border_tunnel_descent','tunnel_arch'}:
            result.update(purpose='pedestrian' if layer=='Roadbed_outline_underpasses' else 'motor-traffic',construction='descent-border' if part=='border_tunnel_descent' else 'tunnel-portal',status='source-boundary')
        elif layer.startswith('Pedestrian_road'):result.update(purpose='pedestrian',status='reference-network')
        elif part or layer in {'Main_road','Other_road','Internal_road','Segmental_road'} or layer.startswith('Oneway_'):result.update(purpose='transport-reference',status='reference-network')
    elif layer.startswith('PointMarkings'):result.update(purpose='marking',status='legacy-marking')
    return result

def audit(records):
    counts=Counter();unknown=[];deferred=Counter();purposes=Counter()
    for r in records:
        s=r['semantics'];counts[s['status']]+=1;purposes[s['purpose']]+=1
        if s['status'] in {'unknown','unsupported-surface'}:unknown.append(dict(id=r['id'],layer=r['layer'],**s))
        if s['status']=='deferred':deferred[r['layer']]+=1
    return dict(version=2,counts=dict(counts),purposes=dict(purposes),unknown=unknown,
                deferredLayers=dict(deferred),passed=not any(r['status']=='unsupported-surface' for r in unknown),
                policy='unknown/deferred recorded; unsupported structural surfaces block export; water and physical paving are explicit classes; no substring-to-asphalt fallback')
