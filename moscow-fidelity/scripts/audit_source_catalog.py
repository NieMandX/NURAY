"""Inventory retained 2GIS features, style rules and resources without rendering.

Read-only with respect to source caches and city releases. Style declarations are
candidate rules, not proof of a physical object or of a rule matching a feature.
Run from any directory; dependencies are Python's standard library only.
"""
import argparse
from collections import Counter, defaultdict
import gzip
import hashlib
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'prototype'))
from source_objects import EXCLUDED_SOURCE_LAYERS
from tiling.canonical_store import load_canonical, canonical_digest
from source_config import output_path,plan_path as source_plan_path


ROTATIONS = ('db_model_rotation_angle', 'db_rotation_angle')
CONSTRUCTION = {'Road_support_column', 'Road_support_crossbar',
                'Road_support_column_overpasses', 'Road_support_crossbar_overpasses'}
PHYSICAL_REFERENCES = {'Gate', 'Barrier', 'Entrance', 'Porch',
                       'Poi_trash', 'Parking_bike', 'Parking_kick', 'Parking_baby_cart',
                       'Transport_stop', 'Transport_3d_stop', 'Descent'}
LINE_OBJECTS = {'Fence', 'Low_fence', 'Temporary_fence', 'Retaining_wall', 'Embankment'}


def read(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from strings(item)
    elif isinstance(value, dict):
        for item in value.values():
            yield from strings(item)


def layer_selectors(expr):
    """Only extract literal layers from explicit sublayer comparisons."""
    result = set()
    if not isinstance(expr, list) or not expr:
        return result
    if expr[0] in ('match', '==', 'in') and len(expr) >= 3:
        if expr[1] in (['get', 'sublayer'], ['get', 'db_sublayer']):
            if expr[0] == 'match':
                for value in expr[2:-1:2]:
                    result.update(strings(value))
            else:
                result.update(strings(expr[2]))
    for child in expr:
        if isinstance(child, list):
            result.update(layer_selectors(child))
    return result


def field_summary():
    return dict(present=0, null=0, types=Counter(), examples=[], numericMin=None,
                numericMax=None, values=Counter(), valuesTruncated=False)


def collect(table, feature):
    p = feature['properties']; layer = p.get('db_sublayer', '<missing>')
    row = table.setdefault(layer, dict(records=0, geometry=Counter(), fields={}))
    row['records'] += 1; row['geometry'][p.get('db_geometry_type', '<missing>')] += 1
    for key, value in p.items():
        stat = row['fields'].setdefault(key, field_summary()); stat['present'] += 1
        if value is None:
            stat['null'] += 1
        stat['types'][type(value).__name__] += 1
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
        if encoded in stat['values'] or len(stat['values']) < 16:
            stat['values'][encoded] += 1
        else:
            stat['valuesTruncated'] = True
        if len(stat['examples']) < 6 and value not in stat['examples']:
            stat['examples'].append(value)
        if isinstance(value, (float, int)) and not isinstance(value, bool):
            stat['numericMin'] = value if stat['numericMin'] is None else min(value, stat['numericMin'])
            stat['numericMax'] = value if stat['numericMax'] is None else max(value, stat['numericMax'])


def compact(table):
    for row in table.values():
        for stat in row['fields'].values():
            stat['values'] = [dict(value=json.loads(k), count=v) for k, v in stat['values'].items()]
    return dict(sorted(table.items()))


def evidence(rows):
    n = len(rows)
    props = [r['properties'] for r in rows]
    fields = sorted(set(k for p in props for k in p if k.startswith('db_') or k == 'id'))
    return dict(records=n, providerId=sum(p.get('id') is not None for p in props),
                sourceRotation=sum(any(p.get(k) is not None for k in ROTATIONS) for p in props),
                fields=fields,
                explicitMetricFields={k: sum(p.get(k) is not None for p in props)
                                      for k in fields if k.endswith('_m')},
                modelSizeFieldsUnitsUnverified={k: sum(p.get(k) is not None for p in props)
                                               for k in fields if k.startswith('db_model_size_')})


def additional_sources(source, city):
    """The immersive GLB channel is independent of vector template models."""
    folder = output_path(source)
    detailed = read(folder/'models.json')
    unavailable = read(folder/'unavailable_models.json')
    metadata = {}
    for path in sorted((source/'source/cache').glob('meta_*.json')):
        doc = read(path)
        metadata[path.name] = dict(sha256=sha(path), tileProperties=doc.get('tileProps'),
            enumerations=doc.get('enumerationValues'),
            version=doc.get('version'), zenithVersion=doc.get('zenithVersion'))
    return dict(
        detailedModelRecords=[{**f, 'cachedFileExists':Path(f['local_file']).is_file()} for f in detailed],
        detailedModelCount=len(detailed),
        currentDetailedModelGroups=[r for r in city['objectLayer']['buildings'] if r['category']=='landmark'],
        historicalUnavailableRequests=unavailable,
        unavailableNote='Failures from the retained download receipt; no live availability check was made.',
        metatileSchemas=metadata,
        decoderScope='Outdoor construction excludes interior plan records and information anchors. Explicit physical building classes, including Floor_plan_house and its roof, take precedence over the interior name filter. The fresh raw archive retains every decoded record.')


def audit(args):
    release = args.release.resolve(); source = args.source.resolve(); out = args.output.resolve()
    if out == release or release in out.parents or out == source or source in out.parents:
        raise ValueError('Inventory must be separate from source and release')
    out.mkdir(parents=True, exist_ok=True)
    city_path = release/'canonical/urban-model.json'; city = load_canonical(city_path)
    plan_path = source_plan_path(source); plan = read(plan_path)
    style_path = source/'source/style_flat.json'; styles = read(style_path)
    assets_path = source/'source/map_style.json'; model_assets = read(assets_path)['result']['models']
    library = read(args.library_audit)['street']['rows']
    used_tiles = sorted(set(f['source']['tile'] for f in city['features']))
    selected = {(f['source']['tile'], f['source']['index']): f for f in city['features']}
    current = {}; broad = {}; raw_selected = {}; hashes = {}; seen = set()
    keys = sorted(set('_'.join(map(str, t[:3])) for t in plan['tiles']) | set(used_tiles))
    for i, key in enumerate(keys):
        path = source/'source/cache'/f'{key}.json'
        data_bytes = path.read_bytes(); data = json.loads(data_bytes)
        hashes[key] = hashlib.sha256(data_bytes).hexdigest()
        for index, feature in enumerate(data['features']):
            collect(broad, feature)
            if (key, index) in selected:
                f = selected[(key, index)]
                if hashes[key] != f['source']['fileSha256']:
                    raise ValueError(('Source changed since release', key))
                if feature['properties'].get('db_sublayer') != f['layer']:
                    raise ValueError(('Source layer mismatch', key, index))
                collect(current, feature); seen.add((key, index)); raw_selected[f['id']] = feature
        if (i+1) % 25 == 0 or i+1 == len(keys):
            print(f'Scanned {i+1}/{len(keys)} source tiles', flush=True)
    assert seen == set(selected), ('Missing records', set(selected)-seen)

    # Preserve original filters/expressions. Never turn a style fallback rotation,
    # random size, screen icon width or default model into a source measurement.
    rules = defaultdict(list); style_only = []; resources = {}
    for s in styles:
        layers = sorted(layer_selectors(s.get('filter')))
        for layer in layers:
            rules[layer].append(s)
        if s['type'] == 'model':
            style_only.append(dict(id=s['id'], name=s.get('name'), layers=layers,
                                   selectorsKnown=bool(layers)))
    for name, data in model_assets.items():
        path = source/'source/cache'/('style_'+data['url'])
        resources[name] = dict(declaration=data, cached=path.is_file(),
                               localPath=str(path) if path.is_file() else None)
    model_layers = {layer for layer, rs in rules.items() if any(r['type']=='model' for r in rs)}
    imported_layers = {r['name'] for r in library}
    physical = (model_layers | imported_layers | CONSTRUCTION | PHYSICAL_REFERENCES | LINE_OBJECTS) - EXCLUDED_SOURCE_LAYERS
    grouped = defaultdict(list)
    for f in city['features']:
        grouped[f['layer']].append(f)
    records = []
    for f in city['features']:
        layer = f['layer']
        if layer in EXCLUDED_SOURCE_LAYERS or (layer not in physical and layer != 'Point3DEntity'):
            continue
        raw = raw_selected[f['id']]; p = raw['properties']
        if layer == 'Point3DEntity':
            decision = 'unresolved-entity-no-model-reference-in-retained-vector-record'
        elif layer in CONSTRUCTION:
            decision = 'parameterized-construction-needs-semantic-and-surface-binding'
        elif layer in LINE_OBJECTS:
            decision = 'line-construction-needs-type-height-and-tile-stitching-policy'
        elif layer in PHYSICAL_REFERENCES and not any(r['type']=='model' for r in rules[layer]):
            decision = 'physical-reference-point-insufficient-for-exact-model-placement'
        else:
            decision = 'model-candidate-check-full-filter-and-required-attributes'
        records.append(dict(sourceRecordId=f['id'], source={**f['source'], 'providerObjectId':p.get('id')},
            layer=layer, geometryType=f['geometryType'], coordinatesMSK=f['coordinates'],
            sourceGeometryWGS84=raw.get('geometry'), rawEncodedGeometry=raw.get('_raw'),
            properties=p, decision=decision,
            orientation=dict(sourceFields={k:p[k] for k in ROTATIONS if p.get(k) is not None},
                             status='source-field-present' if any(p.get(k) is not None for k in ROTATIONS) else 'unknown'),
            candidateStyleIds=[r['id'] for r in rules[layer]],
            originalSurfaceSemantics=f['semantics']))

    feature_groups = []
    vegetation_layers={r['layer'] for r in city['objectLayer']['vegetation']}
    for layer in sorted(physical | {'Point3DEntity'}):
        if layer not in broad and layer not in model_layers:
            continue
        rs = rules.get(layer, [])
        candidate_models = sorted(set(name for s in rs for name in strings(s.get('style',{}).get('modelSrc')) if name in model_assets))
        feature_groups.append(dict(layer=layer, current=evidence(grouped[layer]),
            sourceTileRecordCount=broad.get(layer,{}).get('records',0),
            libraryBatches=[r for r in library if r['name']==layer],
            styleRuleIds=[r['id'] for r in rs], styleNames=list(dict.fromkeys(r.get('name','') for r in rs)),
            candidateModels=candidate_models,
            currentRuntime=('vegetation-replaced-by-approved-library' if layer in vegetation_layers else 'not-added-as-a-separate-object-layer'),
            candidateOnly=True))
    report = dict(version=1, excludedPlacementLayers=sorted(EXCLUDED_SOURCE_LAYERS), scope=dict(release=str(release), boundsMSK=city['boundsMSK'],
        currentSelection='exact retained release feature records; line/polygon counts include source tile fragments',
        broadSelection='all decoded vector records of retained plan tiles, including their margins; not unique city objects',
        sourceTiles=len(keys), currentSourceTiles=used_tiles,
        sourceDate=(read(source/'acquisition-report.json').get('acquiredAt') if (source/'acquisition-report.json').exists() else 'retained snapshot; date unspecified')),
        provenance=dict(citySha256=canonical_digest(city_path), planSha256=sha(plan_path), stylesSha256=sha(style_path),
                        resourcesSha256=sha(assets_path), tileSha256=hashes),
        summary=dict(currentFeatures=len(selected), currentLayers=len(current), broadLayers=len(broad),
                     broadRecords=sum(x['records'] for x in broad.values()),
                     styleRules=len(styles), declaredModelResources=len(resources),
                     cachedDeclaredModelResources=sum(v['cached'] for v in resources.values()),
                     importedStreetBatches=len(library), placementRecords=len(records),
                     unresolvedPoint3DEntity=len(grouped['Point3DEntity'])),
        caveats=[
            'Declared resource and style rule counts are not counts of object types or instances.',
            'Coordinates identify a map anchor; ground-truth accuracy or exact pole position is not supplied.',
            'Source angle fields require per-style axis/sign/pivot conversion; absent angle remains unknown.',
            'Fields ending _m are explicit metre fields. db_model_size_* units are not established here.',
            'Style scales and default/fallback rotations are presentation choices, not per-object measurements.',
            'A map icon may refer to a physical object. Keep eligible semantic points without drawing icons; explicitly excluded layers are not placement candidates.',
            'Provider IDs can repeat at different points/components. Do not deduplicate by ID alone.',
            'For objects without provider IDs, coordinate/class keys are fallback identities, not persistent provider IDs.',
            'Point3DEntity has no resolved model identity here. Do not infer models by proximity to a metatile model.',
            'Existing surface-semantic deferred statuses do not describe later object/railway/landscape passes.',
        ],
        currentLayers=compact(current), broadLayers=compact(broad), physicalCandidates=feature_groups,
        sourceRulesByLayer=dict(sorted(rules.items())), modelResources=resources,
        modelRuleCoverage=style_only, runtimeObjectStats=city['objectLayer']['stats'],
        additionalSources=additional_sources(source, city))
    (out/'inventory.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    with (out/'placement-evidence.json.gz').open('wb') as file:
        with gzip.GzipFile(filename='',mode='wb',fileobj=file,mtime=0) as stream:
            stream.write(json.dumps(dict(version=1,excludedPlacementLayers=sorted(EXCLUDED_SOURCE_LAYERS),crsProj=city['crsProj'],
                coordinates='MSK XY and source relative map Z; not final terrain elevation',
                records=records),ensure_ascii=False,separators=(',',':')).encode())
    print(json.dumps(report['summary'],ensure_ascii=False),flush=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--release', type=Path, required=True)
    p.add_argument('--source', type=Path, required=True)
    p.add_argument('--library-audit', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    audit(p.parse_args())
