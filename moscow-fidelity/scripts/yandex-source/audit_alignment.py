#!/usr/bin/env python3
"""Flag cross-provider plant conflicts, without moving or deleting source points."""
import argparse
from collections import Counter
import gzip
import json
import math
from pathlib import Path

import numpy as np
from pyproj import Transformer
import shapely as sh
from shapely.geometry import Polygon


def audit(root):
    supplement = root / 'supplement-2gis'
    metadata = json.loads((supplement / 'audit.json').read_text())
    plants = json.loads(gzip.decompress((supplement / 'vegetation.json.gz').read_bytes()))
    project = Transformer.from_crs('EPSG:3395', metadata['crs'], always_xy=True)
    groups = {name: [] for name in ('building', 'detailedRoad', 'water')}
    for file in sorted((root / 'decoded').glob('*.json.gz')):
        tile = json.loads(gzip.decompress(file.read_bytes()))
        for feature in tile['features']:
            layer, attrs = feature['layer'], feature['attributes']
            group = None
            if layer in ('building', 'model_a'):
                group = 'building'
            elif layer == 'hd_road_surface' and attrs.get('type') == 'road' and attrs.get('struct') in (None, 'none') and attrs.get('z_level', 0) == 0:
                group = 'detailedRoad'
            elif layer == 'hydro_a':
                group = 'water'
            if group is None:
                continue
            for polygon in feature['geometry'].get('polygons', []):
                rings = []
                for ring in polygon['vertexRings']:
                    points = np.array([[v['x'], v['y']] for v in ring]) * (math.pi * 6378137)
                    x, y = project.transform(points[:,0], points[:,1])
                    rings.append(np.column_stack([x, y]))
                if not rings or len(rings[0]) < 3:
                    continue
                geometry = sh.make_valid(Polygon(rings[0], rings[1:]))
                groups[group].append(geometry)
    points = sh.points([p['eastNorth'] for p in plants])
    conflicts = {}
    for name, polygons in groups.items():
        if not polygons:
            continue
        # This is a candidate conflict audit: the scene builder still has to
        # resolve overhangs and non-ground parts before accepting/rejecting it.
        point_indices, _ = sh.STRtree(polygons).query(points, predicate='within')
        for index in np.unique(point_indices):
            conflicts.setdefault(int(index), []).append(name)
    records = [dict(id=plants[i]['id'], sourceLayer=plants[i]['layer'], lonLat=plants[i]['lonLat'],
                    candidateConflicts=groups) for i, groups in sorted(conflicts.items())]
    report = dict(sourcePlants=len(plants), potentialConflicts=len(records),
        perGeometryType=dict(Counter(name for row in records for name in row['candidateConflicts'])),
        policy='Audit source XY against Yandex building footprints, ground HD road surfaces and water; no coordinate edits or scene acceptance implied',
        limitations=['Only detailed road polygons are checked here; line-derived minor roads require the final surface builder.',
                     'A footprint conflict may be an overhang rather than an occupied ground footprint.'],
        records=records)
    with gzip.open(supplement / 'alignment-audit.json.gz', 'wt', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, separators=(',', ':'))
    print(json.dumps({k:v for k,v in report.items() if k!='records'}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    args = parser.parse_args()
    audit(args.source)
