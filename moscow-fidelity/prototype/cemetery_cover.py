"""Cemetery land-use tint is separate from raised lawns and physical paving."""
LAYER = 'Graveyard_quarter'
MATERIAL_INDEX = 25
NAME = 'Кладбище · зелёное покрытие'
SOURCE_COLOR = '#E0E8CA'
POLICY = ('Cemetery land-use cover retains its source ownership and rank 20; '
          'explicit paths, paving, roads, water and planting take precedence. '
          'Appearance only: no additional lawn lift or perimeter curb.')


def color():
    # User-directed green PBR albedo. The provider's pale #E0E8CA tint looked
    # yellow under our lighting; retain it above as reference, not as albedo.
    # Authored green: halve sRGB HSL saturation, then darken linear albedo
    # twice by 1.5. Finally increase that result's HSL saturation by 1/3,
    # preserving its hue and lightness. Stored as linear PBR RGB.
    return [.050835359144127575, .08795252596444265, .03776051643379333]


def material():
    return dict(name=NAME, family=NAME, color=color(), roughness=.94,
                metallic=0, ior=1.5, kind=1, texture=None, alphaCutoff=0)


def owns_surface(row, owners):
    # Test final canonical ownership, not containment in a broad cemetery
    # footprint: a path inside that footprint must keep its own material.
    return row['kind'] == 'land' and row['owner'] in owners
