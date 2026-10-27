"""Ground pedestrian network and raised green cover, before transport tiling.

The source provides centre lines and land classes, not surveyed path widths.
Widths, the 10 cm step and the 15 cm inset edging are reconstruction rules.
No source object IDs, crop coordinates or transport tile boundaries enter them.
"""
from collections import Counter
import numpy as np
import shapely as sh
from spatial_mask import SpatialMask, ComponentMask
from passage_space import stable_area

GREEN_RAISE = .10
GREEN_CURB_WIDTH = .15
NUMERIC_CRACK_WIDTH = .0001  # 0.1 mm, far below the source coordinate step.
PATH_WIDTHS = {'Pedestrian_road': 2., 'Pedestrian_road_park_path': 3.,
               'Pedestrian_road_park_footpath': 1.2, 'Pedestrian_road_stairs': 2.}
GREEN_VARIANTS = {
    'Internal_lawn': ('Газон · луговой', [.085, .16, .058]),
    'Internal_forest_quarter': ('Зелёная зона · древесный покров', [.069, .133, .052]),
    'Forest_quarter': ('Зелёная зона · лес', [.062, .119, .050]),
    'Flowerbed_quarter': ('Зелёная зона · цветники', [.113, .183, .066]),
    'Immersive_park_polygon_green': ('Газон · парк', [.094, .172, .063]),
}

def parts(g, kind='Polygon'):
    if g.is_empty: return []
    if g.geom_type == kind: return [g]
    return [p for sub in getattr(g, 'geoms', []) for p in parts(sub, kind)]

def area_only(g, precision=1e-5):
    """Normalize a footprint without giving boundary-only contacts any width.

    Clipped ribbons and fixed-grid unions can contain detached lines/points.
    GEOS fixed-precision overlays reject those mixed-dimensional collections.
    Extract area both before and after union; keep the existing precision.
    """
    polygons=parts(g)
    if not polygons:return sh.Polygon()
    snapped=sh.set_precision(polygons,precision)
    polygons=parts(sh.union_all(snapped,grid_size=precision))
    if not polygons:return sh.Polygon()
    merged=polygons[0] if len(polygons)==1 else sh.MultiPolygon(polygons)
    return sh.set_precision(merged,precision)

def physical_green(g, precision=1e-5):
    """Keep resolved area before a microscopic boolean tail becomes a wall.

    Use the same floating-width probe as transport curbs. It preserves the
    original boundary wherever real area supports it; it does not round off
    the whole lawn or expand into a path. Widths below ten grid steps are
    numerical leftovers, not independently extruded planting islands.
    """
    return area_only(stable_area(g,precision),precision)

def ground_path(f):
    p = f['properties']
    return (f['geometryType'] == 'polyline' and f['layer'] in PATH_WIDTHS
            and all(x == 0 for x in (p.get('db_tiers') or [0]))
            and all(p.get(k, 0) == 0 for k in
                    ('db_segment_level', 'db_segment_begin_level', 'db_segment_end_level')))

def plan(features, green, walk, extent, protected, precision=1e-5, rail_apron=None):
    green=area_only(green,precision);walk=area_only(walk,precision)
    protected=area_only(protected,precision);extent=area_only(extent,precision)
    rail_apron=area_only(rail_apron if rail_apron is not None else sh.Polygon(),precision)
    protected=area_only(sh.union_all([protected,rail_apron]),precision)
    source_green=green
    # Old independently intersected terrain cells contain a few micrometre
    # slits. A 15 cm border around such a slit creates a very visible false
    # concrete stripe. Close only sub-0.1 mm cracks, BEFORE real paths/cuts.
    closed=green.buffer(NUMERIC_CRACK_WIDTH/2,join_style='mitre',mitre_limit=2).buffer(
        -NUMERIC_CRACK_WIDTH/2,join_style='mitre',mitre_limit=2)
    green=area_only(sh.union_all([green,closed]).intersection(extent).difference(walk),precision)
    filled=area_only(green.difference(source_green),precision)
    paths=[]; source=[]; skipped=Counter()
    # Existing detailed paving polygons have precedence over guessed widths.
    covered_walk=walk.buffer(.05)
    walk_mask=SpatialMask(covered_walk);green_mask=SpatialMask(green)
    for f in features:
        if f['layer'] not in PATH_WIDTHS: continue
        if not ground_path(f):
            skipped['other-vertical-level']+=1; continue
        xy=np.asarray(f['coordinates'])[:,:2]
        if len(xy)<2: continue
        line=sh.LineString(xy)
        local_walk=walk_mask.near(line)
        uncovered=line.difference(local_walk)
        ribbon=uncovered.buffer(PATH_WIDTHS[f['layer']]/2, quad_segs=4,
                                cap_style='round', join_style='round').intersection(extent)
        paths.append(ribbon)
        source.append(dict(source=f['id'],layer=f['layer'],widthM=PATH_WIDTHS[f['layer']],
                           sourceLengthM=line.intersection(extent).length,
                           alreadyPavedLengthM=line.intersection(local_walk).length,
                           convertedGreenAreaM2=ribbon.intersection(green_mask.near(ribbon)).area))
    paths=area_only(sh.union_all(paths, grid_size=precision),precision)
    cut=area_only(sh.union_all([paths, protected], grid_size=precision),precision)
    raw_raised=area_only(sh.difference(green, cut, grid_size=precision),precision)
    raised=physical_green(raw_raised,precision)
    discarded=area_only(raw_raised.difference(raised),precision)
    # Inset into green: edging must not consume the pedestrian clear width.
    # One union prevents internal borders between green classes/features.
    band=area_only(raised.difference(raised.buffer(-GREEN_CURB_WIDTH, join_style='mitre', mitre_limit=2)),precision)
    band=physical_green(band.difference(extent.boundary.buffer(GREEN_CURB_WIDTH+precision*5)),precision)
    raised_parts=parts(raised);band_parts=parts(band)
    for g in (raised,band,cut):sh.prepare(g)
    return dict(raised=raised,band=band,paths=paths,cut=cut,precision=precision,filled=filled,discarded=discarded,
                raisedPredicate=ComponentMask(raised),bandPredicate=ComponentMask(band),cutPredicate=ComponentMask(cut),
                railApron=rail_apron,railApronMask=SpatialMask(rail_apron),
                cutMask=SpatialMask(cut),raisedMask=SpatialMask(raised),bandMask=SpatialMask(band),
                raisedParts=raised_parts,raisedTree=sh.STRtree(raised_parts),
                bandParts=band_parts,bandTree=sh.STRtree(band_parts)),dict(
        version=3,railApronGeometry=sh.geometry.mapping(rail_apron),
        railApronPolicy='Dark concrete at finished ground height across confirmed full-width railway mouths and low bridge emergence, source height <= 0.202 m. Preserve planting below high spans.',
        greenRaiseM=GREEN_RAISE,curbWidthM=GREEN_CURB_WIDTH,pathWidthsM=PATH_WIDTHS,
        sourcePaths=source,skipped=dict(skipped),sourceGreenAreaM2=source_green.area,
        numericClosure=dict(maxCrackWidthM=NUMERIC_CRACK_WIDTH,filledAreaM2=filled.area,
            policy='Close numerical cracks in green cover before paths; preserve explicit paving and all subsequent protected corridors.'),
        numericCleanup=dict(minResolvedWidthM=10*precision,discardedAreaM2=discarded.area,
            policy='Remove unsupported precision-width polygon remnants before green edging and side extrusion; retain original supported boundaries. Discarded remnants are not pedestrian paths.'),
        raisedAreaM2=raised.area,newPathAreaM2=green.intersection(paths).area,
        reservedAreaM2=area_only(green.intersection(protected),precision).difference(paths).area,curbTopAreaM2=band.area,
        policy='Ground source paths first; detailed paving polygons retain priority. Union green cover, subtract paths and protected ground interfaces, inset edging, raise by 0.10 m; clip transport tiles last. No borders at class, source-feature or crop seams.',
        widthEvidence='Explicit metre defaults; source line styles use display widths, not measured path widths.')

def split_cell(poly, plane, layout):
    """Partition a source terrain cell without a second independent height field."""
    # A floating overlay against a fixed-grid union can turn micrometre terrain
    # cell seams into false paving strips. All operands use the same precision.
    poly=sh.set_precision(poly,layout['precision'])
    if poly.is_empty or poly.area<1e-9:return
    paved=poly.intersection(layout['cutMask'].near(poly)) if layout.get('cutPredicate',layout['cut']).intersects(poly) else sh.Polygon()
    apron=layout.get('railApron',sh.Polygon())
    if not paved.is_empty and apron.intersects(paved):
        local=layout['railApronMask'].near(paved)
        yield 'railway_apron',paved.intersection(local),plane
        paved=paved.difference(local)
    yield 'path',paved,plane
    if layout.get('raisedPredicate',layout['raised']).covers(poly):elevated=poly
    else:
        # Snapping a microscopic repair may collapse it to a line/point.
        # Keep only area components before further fixed-precision overlays.
        elevated=sh.union_all(parts(poly.intersection(layout['raisedMask'].near(poly))))
    if elevated.is_empty or elevated.area<1e-9:return
    high=plane+np.array([0,0,GREEN_RAISE])
    if not layout.get('bandPredicate',layout['band']).intersects(poly):
        yield 'green',elevated,high
        return
    band=layout['bandMask'].near(poly)
    yield 'green', elevated.difference(band), high
    yield 'curb', elevated.intersection(band), high

def sides(layout, dem, tree, extent, triangulate, z_at, land_raise=.10, region=None):
    """Only the physical exterior gets a riser; inset edge has equal top levels."""
    faces=[]; seen=set()
    boundary=layout['raised'].boundary.difference(extent.boundary.buffer(.00005))
    if region is not None:boundary=boundary.intersection(region)
    lines=[]
    for ring in parts(boundary, 'LineString'):
        xy=list(ring.coords)
        lines.extend(sh.LineString([a,b]) for a,b in zip(xy,xy[1:]) if a!=b)
    for line in lines:
        for i in tree.query(line, predicate='intersects'):
            for piece in parts(line.intersection(dem[i][0]), 'LineString'):
                xy=np.asarray(piece.coords)[:,:2]
                for a,b in zip(xy,xy[1:]):
                    if np.linalg.norm(a-b)<1e-5: continue
                    key=tuple(sorted([tuple(np.round(a,5)),tuple(np.round(b,5))]))
                    if key in seen: continue
                    seen.add(key)
                    low=z_at(dem[i][1], [a,b])+land_raise
                    v=np.array([[*a,low[0]],[*b,low[1]],[*b,low[1]+GREEN_RAISE],[*a,low[0]+GREEN_RAISE]])
                    f=[v[[0,1,2]],v[[0,2,3]]]
                    faces.extend(f+[t[::-1] for t in f])
    return faces
