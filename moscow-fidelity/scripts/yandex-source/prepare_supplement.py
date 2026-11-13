#!/usr/bin/env python3
"""Prepare verified 2GIS terrain/plant inputs for a Yandex geometry adapter.

Keep source coordinates and semantics. No random replacement planting, no
implicit absolute-height datum, and no nearest-triangle fallback across gaps.
Use with scripts/build-region-python.sh.
"""
import argparse
from collections import Counter
import gzip
import hashlib
import json
import math
from pathlib import Path
import sys

import numpy as np
from pyproj import Transformer
import shapely as sh
from shapely.geometry import Point, box

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'prototype'))
from terrain import conforming_dem

MODEL_MAPPING = {
    'Model_tree_shrubs_point': 'bush',
    'Model_tree_deciduous_point': 'open',
    'Model_tree_deciduous_growth_point': 'growth',
    'Model_tree_deciduous_low_point': 'low',
    'Model_tree_coniferous_point': 'spruce',
    'Model_tree_deciduous_wide_crown_point': 'compact',
    'Model_tree_narrow_tall_point': 'thuja',
    'Model_tree_birch_point': 'birch',
    'Model_tree_pine_point': 'pine',
    # A source species we do not have a dedicated approved mesh for.
    'Model_tree_lilac_point': 'bush',
}


class Terrain:
    """Piecewise-linear interpolation in the original, reconciled DEM mesh."""
    def __init__(self, triangles):
        self.triangles = np.asarray(triangles, dtype=float)
        self.polygons = sh.polygons(self.triangles[:, :, :2])
        keep = sh.area(self.polygons) > 1e-8
        self.discarded_degenerate = int((~keep).sum())
        self.triangles = self.triangles[keep]
        self.polygons = self.polygons[keep]
        self.tree = sh.STRtree(self.polygons)
        self.planes = np.linalg.solve(
            np.concatenate([self.triangles[:, :, :2], np.ones((len(self.triangles), 3, 1))], axis=2),
            self.triangles[:, :, 2, None])[:, :, 0]

    def sample(self, xy):
        xy = np.asarray(xy, dtype=float).reshape(-1, 2)
        point_ix, tri_ix = self.tree.query(sh.points(xy), predicate='intersects')
        result = np.full(len(xy), np.nan)
        result[point_ix] = (self.planes[tri_ix, :2] * xy[point_ix]).sum(1) + self.planes[tri_ix, 2]
        if not np.isfinite(result).all():
            raise ValueError(f'{np.isnan(result).sum()} samples outside captured terrain')
        return result


def close_quantization_cracks(terrain, footprint):
    """Fill only sub-decimetre source cracks; retain explicit repair evidence."""
    gaps = footprint.difference(sh.union_all(terrain.polygons))
    additions = []
    for gap in sh.get_parts(gaps):
        if gap.area <= 1e-8:
            continue
        if gap.area > 1 or not gap.buffer(-0.04).is_empty:
            raise ValueError(f'DEM has a real coverage gap, area {gap.area} m²')
        for tri in sh.get_parts(sh.constrained_delaunay_triangles(gap)):
            xy = np.asarray(tri.exterior.coords)[:3]
            nearest = terrain.tree.nearest(sh.points(xy))
            distance = sh.distance(sh.points(xy), terrain.polygons[nearest])
            # Every crack vertex must already lie on a captured triangle edge.
            assert distance.max() < 1e-7, 'Crack repair would invent unsupported interior height'
            z = (terrain.planes[nearest, :2] * xy).sum(1) + terrain.planes[nearest, 2]
            additions.append(np.column_stack([xy, z]))
    if additions:
        repaired = Terrain(np.concatenate([terrain.triangles, additions]))
    else:
        repaired = terrain
    return repaired, dict(sourceGapAreaM2=gaps.area, addedTriangles=len(additions),
        policy='Fill only source cracks with area <=1 m² and inradius <=4 cm; heights from existing boundary triangles')


def prepare(root, output, radius=3000):
    plan = json.loads((root / 'plan.json').read_text())
    acquisition = json.loads((root / 'acquisition-report.json').read_text())
    keys = ['_'.join(map(str, t[:3])) for t in plan['tiles']]
    assert {tuple(t['tile'][:3]) for t in acquisition['vectorTiles']} == {tuple(t[:3]) for t in plan['tiles']}
    # Verify each persisted network response against its capture receipt.
    receipts = json.loads((root / 'sources.json').read_text())
    for item in receipts:
        assert hashlib.sha256((root / item['file']).read_bytes()).hexdigest() == item['sha256'], item['file']
    project = Transformer.from_crs('EPSG:4326', plan['crs_proj'], always_xy=True)
    footprint = Point(0, 0).buffer(radius, quad_segs=720)
    triangles, seams = conforming_dem(root / 'source/cache', keys, project, box(*plan['acquisition_bounds_msk']))
    triangles = np.asarray(triangles)
    terrain = Terrain(triangles)
    discarded_degenerate = terrain.discarded_degenerate
    terrain, crack_report = close_quantization_cracks(terrain, footprint)
    triangles = terrain.triangles
    coverage = sh.union_all(terrain.polygons)
    gaps = footprint.difference(coverage)
    gap = gaps.area
    if gap >= 1e-4:
        output.mkdir(parents=True, exist_ok=True)
        (output / 'coverage-gaps.geojson').write_text(sh.to_geojson(gaps))
    assert gap < 1e-4, f'Terrain coverage gap: {gap} square metres'
    plants, counts, duplicates = {}, Counter(), 0
    unknown, nonzero_z, has_id = Counter(), 0, 0
    for key in keys:
        data = json.loads((root / 'source/cache' / (key + '.json')).read_text())
        for feature in data['features']:
            props = feature['properties']
            layer = props.get('db_sublayer', '')
            if not layer.startswith('Model_tree_') or feature['geometry']['type'] != 'MultiPoint':
                continue
            for lon, lat, *source_z in feature['geometry']['coordinates']:
                x, north = project.transform(lon, lat)
                if math.hypot(x, north) > radius:
                    continue
                counts[layer] += 1
                source_id = props.get('id')
                has_id += bool(source_id)
                nonzero_z += bool(source_z and source_z[0])
                # Geometry-point identity, independent of source tile/order.
                identity = f'{layer}:{lon:.9f}:{lat:.9f}'
                if identity in plants:
                    duplicates += 1
                    continue
                digest = hashlib.sha256(identity.encode()).hexdigest()
                model = MODEL_MAPPING.get(layer)
                if model is None:
                    unknown[layer] += 1
                plants[identity] = dict(id='2gis-plant-' + digest[:24], source='2gis',
                    sourceId=source_id, layer=layer, lonLat=[lon, lat], eastNorth=[x, north],
                    sourceZ=source_z[0] if source_z else None, approvedModel=model,
                    approximateSpeciesMesh=layer == 'Model_tree_lilac_point',
                    yawRadians=int(digest[:8], 16) / 2**32 * 2 * math.pi,
                    scale=0.9 + int(digest[8:16], 16) / 2**32 * 0.2)
    plants = sorted(plants.values(), key=lambda p: p['id'])
    assert plants and not unknown, f'Unexpected source plant types: {dict(unknown)}'
    heights = terrain.sample([p['eastNorth'] for p in plants])
    for plant, height in zip(plants, heights):
        plant['terrainHeightM'] = float(height)
        # Final lawn/paving offset must be resolved by the surface builder.
        plant['heightPolicy'] = 'sample final surface at unchanged source XY; terrain height supplied as base'
    source_heights = triangles[:, :, 2]
    inside = sh.intersects(terrain.polygons, footprint)
    audit = dict(source='2GIS observed Kursk browser source', sourceRoot=str(root),
        centerLonLat=plan['center_wgs84'], radiusMetres=radius, crs=plan['crs_proj'],
        verticalReference=plan['vertical_reference'], sourceTiles=len(keys), verifiedNetworkFiles=len(receipts),
        terrain=dict(triangles=len(triangles), coverageGapSquareMetres=gap,
            discardedDegenerateTriangles=discarded_degenerate, quantizationCracks=crack_report,
            heightRangeM=[float(source_heights[inside].min()), float(source_heights[inside].max())],
            centerHeightM=float(terrain.sample([[0, 0]])[0]),
            seamCount=seams['seamCount'], maxSourceSeamDisagreementM=seams['maxSourceSeamDisagreementM'],
            interpolation='original DEM triangles with reconciled shared boundaries'),
        vegetation=dict(uniquePoints=len(plants), sourcePointRecords=sum(counts.values()),
            deduplicatedPoints=duplicates, sourceTypes=dict(Counter(p['layer'] for p in plants)),
            pointsWithSourceId=has_id, pointsWithNonzeroSourceZ=nonzero_z,
            approximateSpeciesMeshes=dict(Counter(p['layer'] for p in plants if p['approximateSpeciesMesh'])),
            identity='source type + geographic point hash; source ID retained if provided',
            variation='deterministic yaw and uniform 0.9..1.1 multiplier; same shared approved model',
            placement='Source XY retained. Resolve final surface height, then reject/report Yandex geometry conflicts.',
            coverage='These are mapped model instances, not an exhaustive tree inventory'),
        validation=dict(passed=True, fullTerrainCoverage=True, allPlantsHaveTerrainHeight=True,
            allTypesMapped=True, sourceChecksumsVerified=True))
    output.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(output / 'terrain.npz', triangles=triangles)
    with gzip.open(output / 'vegetation.json.gz', 'wt', encoding='utf-8') as f:
        json.dump(plants, f, ensure_ascii=False, separators=(',', ':'))
    (output / 'audit.json').write_text(json.dumps(audit, ensure_ascii=False, indent=2) + '\n')
    (output / 'terrain-seams.json').write_text(json.dumps(seams, ensure_ascii=False, separators=(',', ':')) + '\n')
    print(json.dumps(audit, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--radius', type=float, default=3000)
    args = parser.parse_args()
    prepare(args.source, args.output, args.radius)
