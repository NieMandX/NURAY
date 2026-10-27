"""Distinguish serialized boundary rounding from real green/paving overlap."""
import numpy as np
import shapely as sh
from landscape import parts
from seam_validation import packing_error_bound, SOURCE_POSITION_TOLERANCE, MAX_SERIALIZED_POSITION_TOLERANCE


def paving_coverage(expected, actual, precision=1e-5):
    """Audit resolved paving, not microscopic tails of the green complement.

    The expected paving is derived by subtracting raised/discarded planting
    from the source lawn. Overlay rounding can leave isolated or attached
    one-grid-wide remnants in that complement, outside the source path cuts.
    Apply the existing ten-grid-unit support rule to EXPECTED area first.
    Never apply it to the missing geometry: that would hide narrow real gaps
    in a wide path. Intersect with the original expectation so the analytical
    width probe cannot add any new expected area. Meshes remain unchanged.
    """
    from passage_space import stable_area
    missing=expected.difference(actual.buffer(.001))
    result=dict(rawMissingM2=float(missing.area),uncoveredPavingAreaM2=float(missing.area),
                minResolvedWidthM=10*precision,unsupportedExpectedMissingM2=0.)
    if missing.area>=.001:
        supported=stable_area(expected,precision).intersection(expected)
        resolved_missing=missing.intersection(supported)
        result.update(uncoveredPavingAreaM2=float(resolved_missing.area),
                      unsupportedExpectedMissingM2=float(missing.difference(supported).area))
    result['passed']=result['uncoveredPavingAreaM2']<.001
    return result


def overlap_precision(overlap, expected_green, origin):
    """Only permit overlap next to the independently prescribed green boundary.

    Canonical positions undergo one Float32 rounding (half an ULP per axis).
    Local coordinate magnitudes bound that rounding for each overlap component.
    A narrow overlap in the interior is still an error, regardless of width.
    The spatial index changes cost only; nearby complete boundary segments are
    buffered by the same measured tolerance as the full boundary would be.
    """
    polygons=np.asarray(parts(overlap),dtype=object)
    result=dict(rawOverlapM2=float(overlap.area),interiorOverlapM2=0.,
                maxBoundaryToleranceM=SOURCE_POSITION_TOLERANCE,
                maxAllowedToleranceM=MAX_SERIALIZED_POSITION_TOLERANCE,
                components=len(polygons),precisionPassed=True,passed=True)
    if not len(polygons):return result
    bounds=sh.bounds(polygons)
    local=np.stack((bounds[:,:2],bounds[:,2:]),axis=1)-np.asarray(origin)[:2]
    tolerance=SOURCE_POSITION_TOLERANCE+.5*packing_error_bound(local)
    result['maxBoundaryToleranceM']=float(tolerance.max())
    result['precisionPassed']=bool(np.all(tolerance<=MAX_SERIALIZED_POSITION_TOLERANCE))
    if not result['precisionPassed']:
        result.update(passed=False,interiorOverlapM2=float(overlap.area))
        return result
    # Split rings into segments so a city-sized ring does not defeat locality.
    coords,owners=sh.get_coordinates(sh.get_parts(expected_green.boundary),return_index=True)
    endpoints=np.stack((coords[:-1],coords[1:]),axis=1)[owners[:-1]==owners[1:]]
    edges=sh.linestrings(endpoints);tree=sh.STRtree(edges)
    residual=0.
    for value in np.unique(tolerance):
        selected=polygons[tolerance==value]
        hits=tree.query(selected,predicate='dwithin',distance=float(value))
        nearby=sh.union_all(edges[np.unique(hits[1])])
        residual+=sh.union_all(selected).difference(nearby.buffer(float(value))).area
    result['interiorOverlapM2']=float(residual)
    result['passed']=bool(residual<1e-7)
    return result
