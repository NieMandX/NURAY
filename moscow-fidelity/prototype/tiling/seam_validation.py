"""Check actual serialized roadway/curb faces inside repaired source passages."""
import numpy as np
import shapely as sh
from shapely.affinity import affine_transform
from shapely.geometry import shape

SOURCE_POSITION_TOLERANCE = .00005
MAX_SERIALIZED_POSITION_TOLERANCE = .001


def packing_error_bound(xy):
    """Bound two Float32 roundings: canonical export, then tile clipping.

    Each rounding moves a coordinate by at most half an ULP. Use the actual
    nearby triangle vertices, not a district-wide guessed epsilon. A format
    too coarse for the 1 mm ceiling fails rather than relaxing the ceiling.
    """
    ulps=np.max(np.spacing(np.abs(np.asarray(xy,dtype=np.float32))),axis=-2)
    return np.linalg.norm(ulps.astype(float),axis=-1)


def passage_gates(city):
    # The agreed road contour defines where a passage is meant to be. Rebuilding
    # that reference from independently rounded terrain cells can move a sharp
    # boundary and incorrectly include a legitimate lateral curb in the gate.
    # Actual packed triangles below remain the independent evidence being tested.
    flat = shape(city['groundRoadGeometry']) if 'groundRoadGeometry' in city else sh.union_all(
        [shape(s['geometry']) for s in city['surfaces'] if s['kind'] == 'roadbed_flat'],grid_size=.00001)
    inner = flat.buffer(-.001)
    ox, oy = city['originMSK'][:2]
    result = []
    for r in city['roadSeamRepairs']:
        if r['type'] != 'two-sided-road-seam':
            continue
        gate = shape(r['geometry']).buffer(.00005).intersection(inner)
        result.append((r, affine_transform(gate, [1, 0, 0, -1, -ox, oy])))
    return result


def check_passages(gates, meshes):
    """Meshes contain triangle positions in the exported local X/Y-up/Z frame.

    Do not use the builder's polygons as proof of curb absence: inspect roof
    projections and all vertical curb faces after clipping, packing and BVH
    reordering. A duplicate vertical face is counted only once geometrically.
    """
    collections = {'asphalt': [], 'raised': [], 'curbRoof': [], 'curbBottom': [], 'curbSides': []}
    rounding={k:[] for k in collections}
    for name, triangles in meshes:
        if name not in ['roadbed_flat', 'land', 'curb_top', 'curb_bottom', 'curb_front', 'curb_back']:
            continue
        xy = triangles[:, :, [0, 2]]
        errors=packing_error_bound(xy)
        if name in ['curb_front', 'curb_back']:
            pairs = np.array([[0, 1], [1, 2], [2, 0]])
            lengths = np.linalg.norm(xy[:, pairs[:, 0]]-xy[:, pairs[:, 1]], axis=2)
            longest = pairs[np.argmax(lengths, axis=1)]
            endpoints = xy[np.arange(len(xy))[:, None], longest]
            valid=lengths.max(axis=1)>1e-8
            lines = sh.linestrings(endpoints[valid])
            collections['curbSides'].extend(lines)
            rounding['curbSides'].extend(errors[valid])
        else:
            key = {'roadbed_flat': 'asphalt', 'land': 'raised', 'curb_top': 'curbRoof', 'curb_bottom':'curbBottom'}[name]
            polys = sh.polygons(xy)
            valid=sh.area(polys)>1e-12
            collections[key].extend(polys[valid])
            rounding[key].extend(errors[valid])
    trees = {k: sh.STRtree(v) for k, v in collections.items()}
    rounding={k:np.asarray(v) for k,v in rounding.items()}

    def intersect(key, gate):
        indices = trees[key].query(gate, predicate='intersects')
        if not len(indices):
            return sh.GeometryCollection()
        return sh.union_all([collections[key][i].intersection(gate) for i in indices])

    checks = []
    for repair, gate in gates:
        format_error=0. if gate.is_empty else float(packing_error_bound(np.asarray(gate.bounds).reshape(2,2)))
        for key,tree in trees.items():
            nearby=tree.query(gate.buffer(MAX_SERIALIZED_POSITION_TOLERANCE))
            if len(nearby):format_error=max(format_error,float(rounding[key][nearby].max()))
        tolerance=SOURCE_POSITION_TOLERANCE+format_error
        precision_passed=tolerance<=MAX_SERIALIZED_POSITION_TOLERANCE
        raised_geometry=intersect('raised',gate)
        roof_geometry=intersect('curbRoof',gate)
        bottom_geometry=intersect('curbBottom',gate)
        raised,roof,bottom=[g.area for g in (raised_geometry,roof_geometry,bottom_geometry)]
        raised_core,roof_core,bottom_core=[g.buffer(-tolerance).area for g in (raised_geometry,roof_geometry,bottom_geometry)]
        sides = intersect('curbSides', gate).length
        # A coverage witness may lie just outside an acute gate endpoint.
        # Clipping first discards that real nearest surface and invents a gap
        # after buffering. Keep complete nearby faces until the final test.
        asphalt_ids=trees['asphalt'].query(gate.buffer(tolerance),predicate='intersects')
        asphalt=sh.union_all([collections['asphalt'][i] for i in asphalt_ids])
        missing = gate.difference(asphalt).area
        missing_beyond_precision = gate.difference(asphalt.buffer(tolerance)).area
        # Raw areas remain diagnostic: a long sub-ULP strip can have a large
        # area. Test its resolvable width instead. Vertical barriers retain
        # their independent strict length check, regardless of this band.
        checks.append(dict(sourceParents=repair['sourceParents'],areaM2=gate.area,
                           raisedLandM2=raised,curbRoofM2=roof,curbBottomM2=bottom,curbSideM=sides,
                           raisedLandCoreM2=raised_core,curbRoofCoreM2=roof_core,curbBottomCoreM2=bottom_core,
                           positionToleranceM=tolerance,packingErrorBoundM=format_error,precisionPassed=precision_passed,
                           missingAsphaltM2=missing,missingAsphaltBeyondToleranceM2=missing_beyond_precision,
                           passed=bool(precision_passed and max(raised_core,roof_core,bottom_core)<1e-8 and sides < .001 and missing_beyond_precision < 1e-7)))
    return dict(passed=all(c['passed'] for c in checks),passages=len(checks),checks=checks,
                coreAreaToleranceM2=1e-8,sideLengthToleranceM=.001,sourcePositionToleranceM=SOURCE_POSITION_TOLERANCE,
                positionToleranceM=max((c['positionToleranceM'] for c in checks),default=SOURCE_POSITION_TOLERANCE),
                maxAllowedPositionToleranceM=MAX_SERIALIZED_POSITION_TOLERANCE,
                precisionPolicy='Source boundary tolerance plus the measured two-rounding Float32 ULP bound of nearby vertices; reject format precision worse than 1 mm; retain all raw defects and test resolvable cores; vertical barrier length is unchanged.',
                scope='serialized ground asphalt, land, curb roof, bottom and vertical sides inside source seam repairs')
