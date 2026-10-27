"""Validate and serialize a prepared region; shared by build and checkpoint resume."""
import json,time,hashlib
import numpy as np
import shapely as sh
from source_config import load_plan
from spatial_mask import SpatialMask
from canonical_store import save_canonical,JsonRows

def finish(b,opening,roads,paint_checks,total,bound,start,fresh_source=False):
    failed_profiles=[{k:p[k] for k in ('transport','level','maxAsphaltShoulderHeightMismatchM','maxGroundShoulderJoinErrorM',
        'uncoveredDeckSidesM','uncoveredParapetSidesM','uncoveredShoulderRisersM') if k in p}
        for p in b.overpass_profiles if not p['passed']]
    if failed_profiles:
        raise ValueError(('Overpass profile validation failed before region export',failed_profiles))
    # A resumed checkpoint may contain a NumPy boolean from dimension maths.
    b.road_model.report['sparseFit']=bool(b.road_model.report.get('sparseFit',False))
    print('REGION VALIDATION START',flush=True)
    report=b.validate(opening,roads,paint_checks)
    print('REGION GEOMETRY CHECK',report['passed'],flush=True)
    # Keep diagnostic results available while the independent road-quality
    # audit runs; this file is never accepted as a release validation report.
    (b.DATA/'geometry-validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    report['overpassProfiles']=[{k:v for k,v in p.items() if k not in ['asphaltGeometry','deckGeometry','parapetGeometry','extensionHeightCells','groundEntryGeometry','shoulderGeometry','shoulderRiserGeometry','groundShoulderConnectionGeometry']} for p in b.overpass_profiles]
    report['passed'] &= all(p['passed'] for p in b.overpass_profiles)
    raw_reference=None
    if fresh_source:
        print('REGION ROAD QUALITY REFERENCE',flush=True)
        raw_reference=[]
        road_mask=SpatialMask(roads)
        for polygon,coefficients in b.road_model.dem:
            piece=polygon.intersection(road_mask.near(polygon))
            if piece.area>1e-8:raw_reference.append(dict(kind='roadbed_flat',poly=piece,plane=coefficients))
    report['roadQuality']=b.road_quality(b.surfaces,b.protected_road_islands,reference=raw_reference);report['passed'] &= report['roadQuality']['passed']
    print('REGION ROAD QUALITY',report['roadQuality']['passed'],flush=True)
    report.update(boundsMSK=b.B,sourceFeatures=len(b.records),sourceTiles=b.TILE_KEYS,
        terrainSeams=b.dem_report,roadHeightModel=b.road_model.report,roadSlitRepairs=b.slit_repairs,
        paintAreaM2=total,boundPaintAreaM2=bound,unresolved=b.unresolved,seconds=time.time()-start)
    (b.DATA/'validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    if not report['passed']:
        raise RuntimeError('Canonical region validation failed; tile export is blocked. See validation.json')
    print('REGION EXPORT',sum(map(len,b.groups.values())),'triangles before packing',flush=True)
    stats=b.export(b.DATA/'full',b.groups)
    # Retain the exact shared terrain for incremental structure rebuilds. Runtime
    # streaming does not download this offline construction cache.
    print('REGION TERRAIN ARCHIVE',len(b.dem),'cells',flush=True)
    np.savez_compressed(b.DATA/'terrain.npz',bounds=np.asarray(b.B),
        polygons=sh.to_wkb([p for p,c in b.dem],hex=True).astype('U'),planes=np.asarray([c for p,c in b.dem]))
    # Archive semantics separately from the small runtime spatial index.
    plan=load_plan(b.SOURCE)
    acquisition_file=b.SOURCE/'acquisition-report.json'
    acquisition=json.loads(acquisition_file.read_text()) if acquisition_file.exists() else {}
    receipt_file=b.SOURCE/'sources.json'
    city=dict(version=3,name=plan.get('name','Кутузовская'),boundsMSK=b.B,originMSK=b.ORIGIN.tolist(),crsProj=plan['crs_proj'],sourceStyle=b.source_style,sourceStyleChecks=b.style_checks,transportTileSizeM=250,tunnelWalls=b.wall_report,
        verticalReference='2GIS map heights, not surveyed elevations',
        features=b.records,roadProfiles=b.road_model.axes,roadNodes=b.road_model.nodes,groundRoadGeometry=sh.geometry.mapping(roads),
        roadHeightControlGrid=b.road_model.controls(),roadInterfaces=b.road_interfaces,gradeConnections=b.grade_connections,
        surfaces=JsonRows({**{k:v for k,v in s.items() if k not in ['poly','plane']},'geometry':sh.geometry.mapping(s['poly']),'heightPlane':s['plane'].tolist()} for s in b.surfaces),
        overpassProfiles=b.overpass_profiles,relationships=b.relationships,roadSeamRepairs=b.slit_repairs,
        roadSeamChecks=report['roadSeams'],
        rules=dict(semantics='classify purpose, construction and appearance independently by explicit source layer/style; archive deferred/unknown records; reject unsupported structural surfaces',
          tunnelWalls=b.wall_report['policy'],railwayEntries=b.RAILWAY_ENTRY_POLICY,
          roadInterfaces='establish connections across source classes/tiers by common boundary, opposite interiors and equal heights before generating concrete; audit every source interface, including separate passages at divided mouths',tileBoundary='storage cut only: never add curb or wall at tile cuts',
          canonicalHeights='one shared region height model, clipped only after tessellation',
          roadContinuity='resolve supported same-level asphalt-bank gaps up to 5 cm before land and curbs; preserve explicit islands and independent land; reject exported barriers inside repaired passages',
          curbs='land +0.10 m, 0.15 m wide',overpasses='automotive: shoulders +0.10 m, 1 m wide; slab -1 m; parapet top +0.70 m, width 0.20 m',
          pedestrianOverpasses='source style 241413/609252; light walking surface; whole passage shifted +0.10 m to meet raised sidewalk; open full-width mouths confirmed by uncut same-level pedestrian endpoints; retain lateral rails; no connections inferred solely from XY proximity',
          markingModifiers='source line-to-zigzag in metres before region/tile cuts; replace legacy straight stop markings; bind to matching road tier; clip centred stroke only at its physical road edge'),
        limitations=['Road/ground/overpass prototype; buildings and vegetation instances not included.',
          'Far preview omits road paint only; no surface decimation or measured LOD error.',
          'Non-zigzag markings use the source snapshot extraction coverage; bounds outside it are rejected.',
          'Stair treads are not reconstructed; source inclines are retained. Wall styles are map display parameters, not engineering measurements.',
          'Unmatched descent boundaries retain inferred thin lining without a guessed guard; details in tunnelWalls.',
          'Road heights are reconstructed from map data, not surveyed profiles.'],
        sourceSnapshot=dict(path=str(b.SOURCE),freshAcquisition=fresh_source,
          receipt='sources.json' if receipt_file.exists() else None,
          receiptSha256=hashlib.sha256(receipt_file.read_bytes()).hexdigest() if receipt_file.exists() else None,
          acquiredAt=acquisition.get('acquiredAt')))
    print('REGION CANONICAL JSON',len(b.surfaces),'surface rows',flush=True)
    save_canonical(b.DATA/'urban-model.json',city)
    report.update(export=stats,seconds=time.time()-start)
    (b.DATA/'validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print('REGION VERIFIED',json.dumps(stats),'seconds',report['seconds'],flush=True)
