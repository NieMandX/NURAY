"""Explicit additional land-use tints found in the wider Moscow capture.

These areas are terrain, not roadbeds or continuous raised lawns. Detailed
paths, planting and roads keep precedence. Swamp is not open water and must
not enter the connected-river excavation. Provider display colours are adapted
to the same restrained linear albedo used by the other source paving colours.
"""
FIRST_MATERIAL = 32
FAMILY = 'land-use-cover'
RULES = {
    'Dacha_quarter': dict(material=32, styleId='762651', surface='garden-allotments'),
    'Swamp_place': dict(material=33, styleId='868613', surface='wetland-terrain'),
    'Skiing_trails_place': dict(material=34, styleId='525135', surface='ski-terrain'),
}


def materials():
    rows = [('Дачная территория · зелёное покрытие', 'D3ED9D'),
            ('Заболоченная территория', 'DEEEF1'),
            ('Горнолыжная территория', 'FFFFFF')]
    result = []
    for name, rgb in rows:
        srgb = [int(rgb[k:k+2], 16) / 255 for k in (0, 2, 4)]
        color = [(.46 * (v / 12.92 if v <= .04045 else ((v + .055) / 1.055)**2.4)) for v in srgb]
        result.append(dict(name=name, family=FAMILY, color=color, roughness=.96,
                           metallic=0, ior=1.5, kind=1, texture=None, alphaCutoff=0))
    return result
