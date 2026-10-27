"""Parking asphalt is lighter than roads, with unchanged land ownership."""
from copy import deepcopy

LAYER = 'Parking_area'
MATERIAL_INDEX = 31  # Fresh ground build; incremental releases append instead.
BRIGHTNESS = 1.3
FAMILY = 'parking-asphalt'
POLICY = ('Parking_area uses road asphalt PBR settings with linear albedo x 1.3. '
          'Keep land ownership, rank 20 and heights; '
          'detailed paths, planting, roadbeds and markings retain precedence.')


def material(road):
    result = deepcopy(road)
    result.update(name='Парковки · светлый асфальт', family=FAMILY,
                  color=[min(1., float(v)*BRIGHTNESS) for v in road['color']])
    return result


def owns_surface(row, owners):
    return row['kind'] == 'land' and row['owner'] in owners
