"""Kutuzovskaya surface-model experiment. Read sources; write only this prototype.

Rebuild: PYTHONPATH=/Users/niemandx/AI_Modeling/moscow_10x10/python_libs <python> build.py
No source .blend, production exporter, or published assets are modified.
"""
from pathlib import Path
from collections import defaultdict, Counter
import json, math, gzip, hashlib, struct, time
import numpy as np
import shapely as sh
from shapely.geometry import Polygon, LineString, box, mapping
from shapely.strtree import STRtree
from shapely.ops import substring
from pyproj import CRS, Transformer
from source_config import load_plan
from terrain import conforming_dem
from profiles import RoadHeightModel, repair_junction_gaps
from road_seams import reconcile as reconcile_road_seams, protected_geometry as road_seam_protection
from road_quality import compare as road_quality
from curbs import LAND_RAISE, CURB_WIDTH, CURB_MATERIAL, band as curb_band_geometry, solid_sides, source_evidence
from overpasses import build as build_overpasses, DEPTH
from transitions import discover as discover_connections, terrain_cut, shared_interfaces, interface_coverage
from source_styles import load as load_source_style, PEDESTRIAN_LAYER, PEDESTRIAN_MATERIAL, MARKING_RULES, marking_geometry, pedestrian_profile
from pedestrian import discover as discover_pedestrian_connections
from railway_transitions import discover as discover_railway_connections, POLICY as RAILWAY_ENTRY_POLICY
from semantics import classify, audit as audit_semantics
from source_objects import EXCLUDED_SOURCE_LAYERS, exterior_record
from tunnel_walls import build as build_tunnel_walls
from paint_domain import accepts as accepts_paint, POLICY as PAINT_POLICY
from spatial_mask import SpatialMask,LinearMask

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SOURCE = Path('/Users/niemandx/AI_Modeling/moscow_10x10')
DIAG = ROOT / 'diagnostics/kutuzovskaya'
WEB = ROOT / 'web-preview/prototype'
DATA = WEB / 'assets'
B = [1950., 7920., 2300., 8220.]
ORIGIN = np.array([2125., 8070., 145.])
GRID = 0.00001  # 10 micrometres for deterministic XY overlays; not source accuracy.
PAINT_GAP = .003
EXTENT = box(*B)
TILE_KEYS = [f'{x}_{y}_15' for x in [19799,19800] for y in [22521,22522]]
records, surfaces, relationships, unresolved = [], [], [], []
groups = defaultdict(list)
old_groups = defaultdict(list)
shading_flags = defaultdict(list)
_surface_id_counter = None
source_style = None
source_owners = {}
style_checks = []
MATERIALS = [
    ('Асфальт', [.045,.051,.056], .93),
    ('Территория / покрытие', [.24,.245,.215], .91),
    ('Газон', [.085,.16,.058], .96),
    ('Разметка — белая', [.96,.96,.96], .55),
    ('Разметка — жёлтая', [1.,.93,.045], .55),
    ('Разметка — синяя', [.0844,.2961,.7758], .55),
    ('Стены спуска · восстановленные', [.23,.25,.25], .84),
    ('Пешеходное покрытие', [.32,.31,.28], .88),
    ('Неопределённая территория', [.18,.21,.14], .95),
    ('Бордюр · бетон', [.38,.39,.37], .86),
    ('Эстакада · бетон', [.29,.30,.28], .88),
    ('Пешеходный переход · светлое покрытие', [.72,.72,.72], .88),
    ('Транспортное полотно · светлое покрытие', [.62,.62,.62], .88),
    ('Вода', [.008,.034,.042], .105),
]
# Current 2GIS pavement colours, converted to restrained linear PBR albedo.
for _label,_hex in [('Площадка · синяя','A1B9E8'),('Площадка · голубая','ABE5ED'),
                    ('Площадка · красная','F8CAC3'),('Площадка · оранжевая','F8DBB0'),
                    ('Площадка · жёлтая','F5EDA3'),('Велодорожка','C4B1BF'),
                    ('Площадка · футбол','B8DB80'),('Площадка · теннис','D3EDAF'),
                    ('Площадка · баскетбол','FFA01C'),('Площадка · фиолетовая','AFA7E7'),
                    ('Пляж · песок','FFF5CF')]:
    _srgb=np.array([int(_hex[i:i+2],16)/255 for i in (0,2,4)])
    _linear=np.where(_srgb<=.04045,_srgb/12.92,((_srgb+.055)/1.055)**2.4)
    MATERIALS.append((_label,(_linear*.46).tolist(),.88))

from cemetery_cover import NAME as CEMETERY_NAME, color as cemetery_color, MATERIAL_INDEX as CEMETERY_MATERIAL
assert len(MATERIALS) == CEMETERY_MATERIAL
MATERIALS.append((CEMETERY_NAME,cemetery_color(),.94))
from pedestrian_materials import FIRST_MATERIAL as PEDESTRIAN_FIRST, materials as pedestrian_materials, make_textures as pedestrian_textures
assert len(MATERIALS) == PEDESTRIAN_FIRST
MATERIALS.extend((m['name'],m['color'],m['roughness']) for m in pedestrian_materials(MATERIALS[0][1]))
from parking_cover import MATERIAL_INDEX as PARKING_MATERIAL, material as parking_material
assert len(MATERIALS) == PARKING_MATERIAL
_parking = parking_material(dict(color=MATERIALS[0][1], roughness=MATERIALS[0][2]))
MATERIALS.append((_parking['name'], _parking['color'], _parking['roughness']))

def parts(g, typ='Polygon'):
    if g.is_empty: return []
    if g.geom_type == typ: return [g]
    return [p for sub in getattr(g, 'geoms', []) for p in parts(sub, typ)]

def clean(g):
    return sh.set_precision(sh.make_valid(g), GRID)

def union(gs):
    gs = [g for g in gs if not g.is_empty]
    return sh.union_all(gs, grid_size=GRID) if gs else Polygon()

def plane(tri):
    # Solve in a frame at the first vertex. Absolute map coordinates make the
    # homogeneous 3x3 solve unstable for narrow clipped wall triangles.
    tri=np.asarray(tri,dtype=float)
    a,b=tri[1:,:2]-tri[0,:2];dz=tri[1:,2]-tri[0,2]
    determinant=a[0]*b[1]-a[1]*b[0]
    if determinant==0:raise ValueError(('A zero-area triangle has no height plane',tri.tolist()))
    slope=np.array([(dz[0]*b[1]-dz[1]*a[1])/determinant,
                    (a[0]*dz[1]-b[0]*dz[0])/determinant])
    return np.r_[slope,tri[0,2]-slope@tri[0,:2]]

def z_at(c, xy):
    return np.asarray(xy) @ np.asarray(c)[:2] + c[2]

def triangulate(g, c):
    out = []
    for p in parts(g):
        if p.area < 1e-10: continue
        triangles=[p] if not p.interiors and len(p.exterior.coords)==4 else sh.get_parts(sh.constrained_delaunay_triangles(p))
        for t in triangles:
            xy = np.asarray(t.exterior.coords)[:3,:2]
            a,b=xy[1:]-xy[0];signed_area=a[0]*b[1]-a[1]*b[0]
            # CDT can return zero-area faces next to extremely narrow clipped
            # pieces. They have no surface and cannot define a height plane.
            if signed_area==0:continue
            if signed_area<0: xy = xy[::-1]
            out.append(np.column_stack((xy, z_at(c,xy))))
    return out

def add_surface(g, c, owner, material, kind, tiers):
    global _surface_id_counter
    if g.is_empty or g.area < 1e-9: return
    if not surfaces:_surface_id_counter=0
    elif _surface_id_counter is None:
        _surface_id_counter=max(int(s['id'].rsplit(':',1)[1]) for s in surfaces)+1
    for poly in parts(g):
        if poly.area < 1e-9: continue
        sid = f'surface:{_surface_id_counter}';_surface_id_counter+=1
        surfaces.append(dict(id=sid, poly=poly, plane=np.asarray(c), owner=owner,
                             material=material, kind=kind, tiers=tiers,
                             **source_owners.get(owner,{})))
        triangles=triangulate(poly,c)
        groups[(kind,material)].extend(triangles)
        shading_flags[(kind,material)].extend([kind=='roadbed_flat']*len(triangles))

def source_data():
    global source_style
    source_style=load_source_style(SOURCE/'source/style_flat.json')
    plan=load_plan(SOURCE)
    proj=Transformer.from_crs('EPSG:4326',CRS.from_proj4(plan['crs_proj']),always_xy=True)
    model=json.loads((DIAG/'corrected/manifest.json').read_text())
    if not box(*model['bounds']).covers(EXTENT):
        raise ValueError('Region exceeds retained legacy marking coverage; extract more source markings before expanding')
    candidates=[]
    for key in TILE_KEYS:
        path=SOURCE/'source/cache'/f'{key}.json'
        raw_bytes=path.read_bytes();source_hash=hashlib.sha256(raw_bytes).hexdigest()
        d=json.loads(raw_bytes);info=d['tile_info']
        for idx,f in enumerate(d['features']):
            p=f['properties'];r=f['_raw'];layer=p['db_sublayer']
            if not exterior_record(p):continue
            if not r.get('x'):continue
            wx=info['offset'][0]+np.array(r['x'])*info['size']/32768
            wy=info['offset'][1]+np.array(r['y'])*info['size']/32768
            lon=wx/2**32*360;lat=np.degrees(np.arctan(np.sinh(wy/2**32*2*math.pi)))
            x,y=proj.transform(lon,lat)
            if max(x)<B[0] or min(x)>B[2] or max(y)<B[1] or min(y)>B[3]:continue
            z=np.asarray(r.get('signed_z',np.asarray(r.get('z',np.zeros(len(x))))*32))/(2**32/(2*math.pi*6378137)/np.cos(np.radians(lat)))
            xyz=np.column_stack((x,y,z));typ=p['db_geometry_type']
            rid=f'2gis:{key}:{idx}'
            record=dict(id=rid,layer=layer,geometryType=typ,source=dict(tile=key,index=idx,objectId=p.get('id'),fileSha256=source_hash),
                properties={k:v for k,v in p.items() if k.startswith('db_') or k in ['id','beginningIsCut','endingIsCut','componentDistanceStart','componentDistanceEnd']},
                coordinates=xyz.tolist(),evidence='source')
            record['source']['coordinateStepM']=float(info['size']/32768/(2**32/(2*math.pi*6378137)/np.cos(np.radians(np.mean(lat)))))
            records.append(record)
            semantic=classify(layer,p,typ);record['semantics']=semantic
            if typ!='polygon' or semantic['status']!='built':continue
            kind,material,rank=(semantic[k] for k in ['kind','material','rank'])
            ts=[];polys=[]
            for i in range(len(xyz)-2):
                t=xyz[i:i+3]
                if abs(np.linalg.det(np.column_stack((t[:,:2],np.ones(3)))))<1e-8:continue
                g=clean(Polygon(t[:,:2])).intersection(EXTENT)
                if g.area>1e-9:ts.append((g,plane(t)));polys.append(g)
            if not ts:continue
            metadata=dict(purpose=semantic['purpose'],construction=semantic['construction'],surfaceType=semantic['surface'],styleId=semantic['styleId'])
            if semantic['purpose']=='pedestrian' and kind=='road':
                metadata.update(transport='pedestrian')
                if layer==PEDESTRIAN_LAYER:metadata['profile']=pedestrian_profile(source_style)
            source_owners[rid]=metadata
            candidates.append(dict(id=rid,layer=layer,kind=kind,material=material,rank=rank,**metadata,
                tiers=p.get('db_tiers') or [0],part=p.get('db_road_part','roadbed_flat'),poly=union(polys),patches=ts))
        print('SOURCE TILE',key,'records',len(records),'surfaces',len(candidates),flush=True)
    return candidates,model

def make_dem():
    global dem_report
    plan=load_plan(SOURCE)
    project=Transformer.from_crs('EPSG:4326',CRS.from_proj4(plan['crs_proj']),always_xy=True)
    triangles,dem_report=conforming_dem(SOURCE/'source/cache',TILE_KEYS,project,EXTENT)
    patches=[]
    for t in triangles:
        g=clean(Polygon(t[:,:2])).intersection(EXTENT)
        if g.area>1e-9:patches.append((g,plane(t)))
    return patches,STRtree([p[0] for p in patches])

def lift(g, relative, owner, material, kind, tiers):
    # Large background polygons contain many road/path holes. Clip terrain
    # cells against the exact neighbouring part, not all holes in a source tile.
    bounds=g.bounds
    local=SpatialMask(g) if not g.is_empty and sh.get_num_coordinates(g)>256 and max(bounds[2]-bounds[0],bounds[3]-bounds[1])>250 else None
    for i in demtree.query(g,predicate='intersects'):
        piece=(local.near(dem[i][0]) if local is not None else g).intersection(dem[i][0])
        add_surface(piece, dem[i][1]+relative,owner,material,kind,tiers)

def build_surfaces(candidates):
    global road_model,dem,demtree,slit_repairs,curb_band,curb_front,curb_report,road_seam_report,protected_road_islands
    global grade_connections, road_interfaces, interface_report, transition_cut, overpass_profiles, deck_count
    roads=[r for r in candidates if r['kind']=='road']
    opening=union([r['poly'] for r in roads if r['part']=='roadbed_tunnel_descent'])
    original_road=union([r['poly'] for r in roads if r['part']=='roadbed_flat']).difference(opening)
    protected_road_islands,_=road_seam_protection(candidates,records,original_road,GRID)
    ground_road,slit_repairs,road_seam_report=reconcile_road_seams(original_road,candidates,records,EXTENT,GRID)
    print('ROAD SEAMS INITIAL',len(slit_repairs),flush=True)
    ground_road,junction_repairs,_=repair_junction_gaps(ground_road,candidates,records,B)
    slit_repairs.extend(junction_repairs)
    # Inferred patch coordinates can carry sub-grid floating-point residue.
    # Reconcile the complete road union before deriving its physical perimeter.
    ground_road=union(parts(clean(ground_road)))
    car_candidates=[r for r in candidates if r.get('transport')!='pedestrian']
    ped_candidates=[r for r in candidates if r.get('transport')=='pedestrian']
    road_interfaces=shared_interfaces(car_candidates,EXTENT,GRID,z_at)
    print('ROAD INTERFACES',len(road_interfaces),flush=True)
    grade_connections,connectors=discover_connections(car_candidates,ground_road,EXTENT,GRID,z_at,road_interfaces)
    pedestrian_connections,pedestrian_interfaces=discover_pedestrian_connections(candidates,records,ground_road,EXTENT,GRID,z_at,include_mixed_ground=True)
    # Internal pedestrian descent/tunnel joins share a floor at the sidewalk
    # datum; they must participate in the same free-passage audit as roads.
    ped_internal=shared_interfaces(ped_candidates,EXTENT,GRID,z_at)
    ped_internal_connections,_=discover_connections(ped_candidates,Polygon(),EXTENT,GRID,z_at,ped_internal)
    for interface in ped_internal:
        interface['id']='pedestrian-'+interface['id']
        interface['relativeHeightsM']=[z+LAND_RAISE for z in interface['relativeHeightsM']]
    for connection in ped_internal_connections:
        connection['id']='pedestrian-'+connection['id'];connection['interfaceId']='pedestrian-'+connection['interfaceId']
        connection['transport']='pedestrian';connection['relativeHeightsM']=[z+LAND_RAISE for z in connection['relativeHeightsM']]
    grade_connections.extend(ped_internal_connections);road_interfaces.extend(ped_internal)
    grade_connections.extend(pedestrian_connections);road_interfaces.extend(pedestrian_interfaces)
    rail_connections,rail_interfaces=discover_railway_connections(candidates,records,EXTENT,GRID,z_at)
    grade_connections.extend(rail_connections);road_interfaces.extend(rail_interfaces)
    interface_report=interface_coverage(road_interfaces,grade_connections,GRID)
    if not interface_report['passed']:raise RuntimeError('Unclassified source road continuation; refusing to generate transverse barriers')
    ground_road=union([ground_road,*[g for r,g in connectors]])
    # A repeat audit must find no further supported seam to fill. Unknown
    # one-sided exterior corners are retained and recorded, never rounded off.
    _,remaining_seams,_=reconcile_road_seams(ground_road,candidates,records,EXTENT,GRID)
    road_seam_report['remainingRepairableSeams']=len(remaining_seams)
    road_seam_report['remainingRepairableAreaM2']=sum(r['areaM2'] for r in remaining_seams)
    road_model=RoadHeightModel(dem,records,ground_road,B)
    print('ROAD HEIGHT FIT COMPLETE',flush=True)
    dem=road_model.grid();demtree=STRtree([p for p,c in dem])
    print('ROAD MODEL',road_model.report,'SLIT REPAIRS',len(slit_repairs),flush=True)
    ordered_roads=sorted(roads,key=lambda r:(r['poly'].area,r['id']))
    road_tree=STRtree([r['poly'] for r in ordered_roads])
    road_levels=[(r['part'],tuple(r['tiers']),r.get('transport','vehicle')) for r in ordered_roads]
    for index,r in enumerate(ordered_roads):
        if index%5000==0:print('ROAD FEATURES',index,'/',len(ordered_roads),'surface cells',len(surfaces),flush=True)
        level=(r['part'],tuple(r['tiers']),r.get('transport','vehicle'))
        prior=union([ordered_roads[j]['poly'] for j in road_tree.query(r['poly']) if j<index and road_levels[j]==level])
        g=r['poly'].difference(prior)
        if r['part']=='roadbed_flat':g=g.difference(opening)
        if r['part']=='roadbed_flat':
            lift(g,np.zeros(3),r['id'],r['material'],r['part'],r['tiers'])
        else:
            for p,relative in r['patches']:
                if r.get('transport')=='pedestrian':relative=relative+np.array([0,0,LAND_RAISE])
                lift(p.intersection(g),relative,r['id'],r['material'],r['part'],r['tiers'])
    for i,repair in enumerate(slit_repairs):
        g=sh.geometry.shape(repair['geometry'])
        parents=repair.get('sourceParents')
        if parents is None:
            parents=[ordered_roads[j]['id'] for j in road_tree.query(g.buffer(GRID*3)) if ordered_roads[j]['part']=='roadbed_flat' and ordered_roads[j]['poly'].distance(g)<GRID*3]
            repair['sourceParents']=parents
        owner=f'inferred:road-slit:{i}'
        lift(g,np.zeros(3),owner,0,'roadbed_flat',repair.get('tiers',[0]))
        relationships.append(dict(type='inferred-road-contour-repair',owner=owner,parents=parents,areaM2=g.area))
    for connection,g in connectors:
        lift(g,np.zeros(3),connection['id'],0,'roadbed_flat',[0])
    for connection in grade_connections:
        relationships.append(dict(type='grade-connection',owner=connection['id'],
            parents=connection['sourceParents']+connection['peerParents'],
            evidence=connection['evidence'],connectorAreaM2=connection['connectorAreaM2']))
    if globals().get('surface_checkpoint_hook'):
        surface_checkpoint_hook(opening,ground_road,candidates)
    return complete_surfaces(opening,ground_road,candidates)

def complete_surfaces(opening,ground_road,candidates):
    """Finish structures/land from the globally fitted and tessellated roads."""
    global overpass_profiles,deck_count,transition_cut,curb_band,curb_front,curb_report
    overpass_profiles,deck_count=build_overpasses(surfaces,dem,demtree,groups,EXTENT,GRID,triangulate,z_at,plane,grade_connections)
    # Reject structural defects before the much larger land/curb overlay. The
    # fitted-surface checkpoint already precedes this stage and can be reused.
    profile_checks=[{k:v for k,v in p.items() if 'Geometry' not in k and k!='extensionHeightCells'} for p in overpass_profiles]
    (DATA/'overpass-profile-validation.json').write_text(json.dumps(profile_checks,ensure_ascii=False,indent=2))
    failed=[p for p in profile_checks if not p['passed']]
    if failed:raise ValueError(('Overpass profile validation failed before ground construction',failed))
    transition_cut=terrain_cut(overpass_profiles,surfaces,dem,demtree,grade_connections,LAND_RAISE,DEPTH,GRID)
    # Actual source water occupies its own surface. Never fill the river with
    # inferred pavement. Detailed piers override water only inside their source
    # footprint; a broad Bridge_area is not allowed to erase the river.
    water=union([r['poly'] for r in candidates if r['kind']=='water'])
    piers=union([r['poly'] for r in candidates if r['layer']=='Pier_quarter'])
    water=water.difference(union([ground_road,opening,transition_cut,piers]))
    lift(water,np.zeros(3),'source:water-union',13,'water',[0])
    occupied=union([ground_road,opening,transition_cut,water]);occupied_mask=SpatialMask(occupied)
    from passage_space import walking_reserve
    curb_band=curb_band_geometry(ground_road,union([opening,transition_cut,walking_reserve(grade_connections,GRID)]),EXTENT,GRID)
    curb_mask=SpatialMask(curb_band)
    print('GRADE CONNECTIONS',len(grade_connections),'TERRAIN CUT',transition_cut.area,flush=True)
    def raised_land(g,owner,material):
        # Overlay can leave zero-area lines beside polygons. Keep areal inputs
        # only, with the same precision model on both operands.
        g=union(parts(g))
        if g.is_empty or g.area<1e-9: return
        local_curb=curb_mask.near(g)
        lift(g.difference(local_curb),np.array([0,0,LAND_RAISE]),owner,material,'land',[0])
        first=len(surfaces)
        lift(g.intersection(local_curb),np.array([0,0,LAND_RAISE]),owner,CURB_MATERIAL,'curb_top',[0])
        for s in surfaces[first:]:
            groups[('curb_bottom',CURB_MATERIAL)].extend(
                [t[::-1] for t in triangulate(s['poly'],s['plane']-np.array([0,0,LAND_RAISE]))])
            relationships.append(dict(type='curb-on-raised-territory',parent=s['id'],sourceObject=owner,
                heightM=LAND_RAISE,widthM=CURB_WIDTH,evidence='reconstruction-rule'))
    ordered_land=sorted([c for c in candidates if c['kind']=='land'],key=lambda r:(-r['rank'],r['poly'].area,r['id']))
    land_tree=STRtree([r['poly'] for r in ordered_land])
    for index,r in enumerate(ordered_land):
        if index%5000==0:print('LAND FEATURES',index,'/',len(ordered_land),'surface cells',len(surfaces),flush=True)
        prior=union([ordered_land[j]['poly'] for j in land_tree.query(r['poly']) if j<index])
        g=r['poly'].difference(occupied_mask.near(r['poly'])).difference(prior)
        raised_land(g,r['id'],r['material'])
    missing=EXTENT.difference(union([occupied,*[r['poly'] for r in ordered_land]]))
    if missing.area>1e-6:
        unresolved.append(dict(type='unknown-land-cover',areaM2=missing.area))
        raised_land(missing,'inferred:unclassified-land',8)
    curb_front,side_count=solid_sides(curb_band,ground_road,dem,demtree,groups,z_at,EXTENT)
    curb_report=dict(heightM=LAND_RAISE,widthM=CURB_WIDTH,topAreaM2=curb_band.area,
        sideSegments=side_count,sourceEvidence=source_evidence(records),
        scope='ground roads only; curb terminates at grade connections; ramp shoulders replace it; ground remains under clear elevated spans')
    from partition_refinement import refine
    ground_road=refine(__import__(__name__),opening,ground_road,candidates)
    return opening,ground_road

def clip_triangle(t):
    vertices=list(t)
    for axis,edge,sign in [(0,B[0],1),(0,B[2],-1),(1,B[1],1),(1,B[3],-1)]:
        output=[]
        for i,a in enumerate(vertices):
            b=vertices[(i+1)%len(vertices)];da=(a[axis]-edge)*sign;db=(b[axis]-edge)*sign
            if da>=0:output.append(a)
            if (da>=0)!=(db>=0):output.append(a+(b-a)*(da/(da-db)))
        vertices=output
        if len(vertices)<3:return []
    return [np.array([vertices[0],vertices[i],vertices[i+1]]) for i in range(1,len(vertices)-1)
            if np.linalg.norm(np.cross(vertices[i]-vertices[0],vertices[i+1]-vertices[0]))>1e-9]

def legacy_material(row,mid):
    name=row['materials'][int(mid)]
    if 'yellow' in name:return 4
    if 'blue' in name:return 5
    if 'white' in name:return 3
    if 'Road_surfaces' in row['categories']:return 0
    if 'Green_areas' in row['categories']:return 2
    if 'Road_edges' in row['categories'] or 'Overpass_structure' in row['categories']:return 6
    return 1

def legacy_and_paint(model):
    from paint_binding import bind as bind_paint, SOURCE_FLOOR
    stree=STRtree([s['poly'] for s in surfaces]);paint_checks=[];bound_area=0.;total_area=0.
    for row in model['objects']:
        if row['hidden']:continue
        arr=dict(np.load(DIAG/'corrected'/row['file']));tri=arr['triangles'].astype(float)
        if row.get('heightReference')=='source-relative':
            # New snapshots retain map-relative paint until the shared region
            # height function exists; no earlier Blender terrain is involved.
            tri[:,:,2]+=road_model.height(tri[:,:,:2].reshape(-1,2)).reshape(-1,3)
        keep=(tri[:,:,0].max(1)>=B[0])&(tri[:,:,0].min(1)<=B[2])&(tri[:,:,1].max(1)>=B[1])&(tri[:,:,1].min(1)<=B[3])
        is_paint=bool(set(row['categories'])&{'Road_markings','Road_marking_symbols'})
        is_edge=bool(set(row['categories'])&{'Road_edges','Overpass_structure'})
        for ix in np.flatnonzero(keep):
            material=legacy_material(row,arr['material_indices'][ix]);t=tri[ix]
            clipped=clip_triangle(t)
            old_groups[(row['name'],material)].extend(clipped)
            if not is_paint or row['name'] in MARKING_RULES:continue
            tier=int(arr.get('2gis_tier',np.zeros(len(tri)))[ix])
            tiers=[int(v) for v in arr['source_tiers'][ix] if v!=-32768] if 'source_tiers' in arr else [tier]
            for ct in clipped:
                g=clean(Polygon(ct[:,:2]))
                if g.area<1e-9:continue
                total_area+=g.area;remaining=g
                oldc=plane(ct);p=g.representative_point();xy=np.array([p.x,p.y])
                bindings,remaining=bind_paint(g,oldc,tiers,surfaces,stree,source_floor=row.get('heightBinding')==SOURCE_FLOOR)
                for i,piece in bindings:
                    s=surfaces[i]
                    c=s['plane']+np.array([0,0,PAINT_GAP]);ts=triangulate(piece,c)
                    groups[('paint',material)].extend(ts);bound_area+=piece.area
                    shading_flags[('paint',material)].extend([s['kind']=='roadbed_flat']*len(ts))
                    pid=f"legacy:{row['name']}:{int(arr['polygon_indices'][ix])}"
                    relationships.append(dict(type='paint-on-surface',child=pid,parent=s['id'],sourceObject=s['owner'],areaM2=piece.area))
                    for tt in ts:paint_checks.append((tt,s['plane'],s['id']))
                if remaining.area>1e-6:
                    unresolved.append(dict(type='unbound-paint',object=row['name'],triangle=int(ix),tier=tier,areaM2=remaining.area))
                    # Keep the source/audit record, but unsupported paint is not geometry.
    # Rebuild modifier-bearing source lines, replacing (not overlaying) their
    # legacy straight ribbons. Transform before region/transport tile clipping.
    for record in records:
        if record['layer'] not in MARKING_RULES:continue
        geometry,proof=marking_geometry(record,source_style)
        geometry=clean(geometry).intersection(EXTENT);remaining=geometry
        total_area+=geometry.area
        tiers=record['properties'].get('db_tiers') or [0]
        ids=[int(i) for i in stree.query(geometry,predicate='intersects')
             if accepts_paint(surfaces[int(i)]) and
             set(tiers)&set(surfaces[int(i)]['tiers'])]
        for i in sorted(ids,key=lambda i:surfaces[i]['id']):
            s=surfaces[i];piece=remaining.intersection(s['poly'])
            if piece.area<1e-9:continue
            ts=triangulate(piece,s['plane']+np.array([0,0,PAINT_GAP]))
            groups[('paint',4)].extend(ts);bound_area+=piece.area
            shading_flags[('paint',4)].extend([s['kind']=='roadbed_flat']*len(ts))
            paint_checks.extend((t,s['plane'],s['id']) for t in ts)
            relationships.append(dict(type='paint-on-surface',child=record['id'],parent=s['id'],sourceObject=s['owner'],styleId=proof['styleId'],areaM2=piece.area))
            remaining=remaining.difference(piece)
        # A source line outside the carriageway must be reviewed, never silently
        # replaced by a straight stripe or attached to another level.
        support=union([surfaces[i]['poly'] for i in ids])
        # Stroke corners can extend farther than half the width (miter joins).
        # Audit the source zigzag centreline itself, then clip the finite-width
        # paint at the road edge. A tooth pointing outside still fails this test.
        centreline=LineString(proof['centerline']) if proof['centerline'] else LineString()
        from source_styles import check_marking_support
        proof.update(areaM2=geometry.area,clippedAtRoadEdgeM2=remaining.area,
                     material=4,**check_marking_support(centreline,support,EXTENT,record,GRID))
        style_checks.append(proof)
    return paint_checks,total_area,bound_area

def walls(opening,ground_road):
    global wall_report
    count,wall_report=build_tunnel_walls(surfaces,records,dem,demtree,groups,EXTENT,GRID,grade_connections,source_style,triangulate,z_at,plane)
    return count

def local(t):
    q=np.asarray(t)-ORIGIN
    return q[:,:,[0,2,1]]*np.array([1,1,-1])

def export(target,geometry):
    target.mkdir(parents=True,exist_ok=True);chunks=[];gltf_meshes=[];binary=bytearray();views=[];accessors=[]
    mats=[dict(name=n,family='Road paint' if i in [3,4,5] else n,color=c,roughness=r,metallic=0,ior=1.5,kind=12 if i==13 else 1,texture=None,alphaCutoff=0) for i,(n,c,r) in enumerate(MATERIALS)]
    mats[PEDESTRIAN_FIRST:PEDESTRIAN_FIRST+5]=pedestrian_materials(MATERIALS[0][1])
    mats[PARKING_MATERIAL]=parking_material(mats[0])
    paving_textures=pedestrian_textures(target)
    # Canonical stage folders stay flat for all downstream incremental stages.
    texture_folder=(target.parent.parent if target.name=='full' else target)/'textures'
    texture_folder.mkdir(parents=True,exist_ok=True)
    for filename in paving_textures:(texture_folder/filename).write_bytes((target/filename).read_bytes())
    def glb_array(a,kind,component=5126,limits=False):
        nonlocal binary
        while len(binary)%4:binary.append(0)
        idx=len(views);views.append(dict(buffer=0,byteOffset=len(binary),byteLength=a.nbytes));binary.extend(a.tobytes())
        item=dict(bufferView=idx,componentType=component,count=len(a),type=kind)
        if limits:item.update(min=a.min(0).tolist(),max=a.max(0).tolist())
        accessors.append(item);return len(accessors)-1
    for (name,material),ts in sorted(geometry.items()):
        if not ts:continue
        t=local(np.asarray(ts)).astype('<f4')
        n=np.cross(t[:,1]-t[:,0],t[:,2]-t[:,0]);length=np.linalg.norm(n,axis=1)
        keep=length>1e-9;t=t[keep];n=n[keep]/length[keep,None]
        if not len(t):continue
        normals=np.repeat(n[:,None,:],3,axis=1)
        if geometry is groups:
            flags=np.asarray(shading_flags.get((name,material),[False]*len(ts)),dtype=bool)[keep]
            if np.any(flags):
                world_xy=np.asarray(ts)[keep][flags,:,:2]
                gradient=road_model.smooth_gradient(world_xy.reshape(-1,2)).reshape(-1,3,2)
                smooth=np.stack([-gradient[:,:,0],np.ones(gradient.shape[:2]),gradient[:,:,1]],axis=2)
                smooth/=np.linalg.norm(smooth,axis=2,keepdims=True)
                normals[flags]=smooth
        octn=normals/np.abs(normals).sum(2,keepdims=True);xy=octn[:,:,:2].copy();neg=octn[:,:,2]<0
        xy[neg]=(1-np.abs(xy[neg][:,::-1]))*np.where(xy[neg]>=0,1,-1)
        packed=np.round(np.clip(xy,-1,1)*32767).astype('<i2').reshape(-1,2)
        v=np.zeros((len(t)*3,8),dtype='<u4');vf=v.view('<f4');vf[:,:3]=t.reshape(-1,3)
        v[:,3]=packed.copy().view('<u4').ravel();vf[:,4:6]=t[:,:,[0,2]].reshape(-1,2);v[:,6]=material|0x80000000
        verts,idx=np.unique(v,axis=0,return_inverse=True);idx=idx.astype('<u4')
        filename=f'mesh-{len(chunks):03d}.bin.gz'
        with gzip.GzipFile(filename=str(target/filename),mode='wb',mtime=0) as f:f.write(verts.tobytes());f.write(idx.tobytes())
        chunks.append(dict(id=len(chunks),name=name,category=name,file=f'/prototype/assets/{target.name}/{filename}',vertexCount=len(verts),vertexBytes=verts.nbytes,triangles=len(t),bounds=dict(min=t.min((0,1)).tolist(),max=t.max((0,1)).tolist())))
        pos=glb_array(t.reshape(-1,3),'VEC3',limits=True);normal=glb_array(normals.reshape(-1,3).astype('<f4'),'VEC3')
        uv=glb_array(t[:,:,[0,2]].reshape(-1,2).copy(),'VEC2')
        gltf_meshes.append(dict(name=name,primitives=[dict(attributes=dict(POSITION=pos,NORMAL=normal,TEXCOORD_0=uv),material=material)]))
    count=sum(c['triangles'] for c in chunks)
    manifest=dict(version=1,name=load_plan(SOURCE).get('name','Кутузовская')+' · '+target.name,extentMetres=max(B[2]-B[0],B[3]-B[1]),origin=ORIGIN.tolist(),axes='X east, Y up, Z south',chunks=chunks,
        instances=[dict(mesh=i,matrix=[1,0,0,0,0,1,0,0,0,0,1,0]) for i in range(len(chunks))],materials=mats,textures=paving_textures,
        stats=dict(uniqueTriangles=count,expandedTriangles=count,baseTriangles=count,streetInstances=0,sourceObjects=len(records)))
    (target/'scene.json').write_text(json.dumps(manifest,ensure_ascii=False,separators=(',',':')))
    gltf=dict(asset=dict(version='2.0',generator='NURAY urban surface prototype'),scene=0,scenes=[dict(nodes=list(range(len(gltf_meshes))))],
        nodes=[dict(mesh=i,name=m['name']) for i,m in enumerate(gltf_meshes)],meshes=gltf_meshes,buffers=[dict(byteLength=len(binary))],bufferViews=views,accessors=accessors,
        materials=[dict(name=m['name'],doubleSided=True,pbrMetallicRoughness=dict(baseColorFactor=m['color']+[1],metallicFactor=0,roughnessFactor=m['roughness'])) for m in mats],extras=dict(originMSK=ORIGIN.tolist(),boundsMSK=B))
    gltf['images']=[];gltf['textures']=[]
    for i,m in enumerate(mats):
        if not m.get('texture'):continue
        raw=(target/Path(m['texture']).name).read_bytes()
        while len(binary)%4:binary.append(0)
        image=len(gltf['images']);view=len(views)
        views.append(dict(buffer=0,byteOffset=len(binary),byteLength=len(raw)));binary.extend(raw)
        gltf['images'].append(dict(bufferView=view,mimeType='image/png'))
        gltf['textures'].append(dict(source=image))
        gltf['materials'][i]['pbrMetallicRoughness']['baseColorTexture']=dict(index=image)
    gltf['buffers'][0]['byteLength']=len(binary)
    j=json.dumps(gltf,separators=(',',':')).encode();j+=b' '*((-len(j))%4);binary+=b'\0'*((-len(binary))%4)
    (target/'model.glb').write_bytes(struct.pack('<4sII',b'glTF',2,12+8+len(j)+8+len(binary))+struct.pack('<I4s',len(j),b'JSON')+j+struct.pack('<I4s',len(binary),b'BIN\0')+binary)
    return dict(triangles=count,chunks=len(chunks),downloadBytes=sum(p.stat().st_size for p in target.glob('*.gz'))+(target/'scene.json').stat().st_size,glbBytes=(target/'model.glb').stat().st_size)

def validate(opening,ground_road,paint_checks):
    flat=[s for s in surfaces if s['kind']=='roadbed_flat'];land=[s for s in surfaces if s['kind'] in ['land','curb_top']]
    from validation_geometry import footprint_unions
    footprints=footprint_unions(dict(flat=[s['poly'] for s in flat],land=[s['poly'] for s in land],
        water=[s['poly'] for s in surfaces if s['kind']=='water']),union,GRID,DATA/'validation-footprints.pkl')
    fg=footprints['flat'];lg=footprints['land']
    expected=EXTENT.difference(union([opening,transition_cut]))
    from coverage import gap_core_area,uncovered_length,physical_land_boundary
    water_geometry=footprints['water']
    flat_and_land=union([fg,lg,water_geometry]);gaps=expected.difference(flat_and_land);gap=gaps.area
    # Audits query small mouths/seams. Keep the same exact polygons while
    # avoiding repeated overlays against the entire multi-kilometre city.
    flat_mask=SpatialMask(fg);land_mask=SpatialMask(lg);curb_mask=SpatialMask(curb_band)
    front_mask=LinearMask(curb_front)
    gap_core=gap_core_area(gaps,GRID*5)
    overlap_geometry=fg.intersection(lg);overlap=overlap_geometry.area
    overlap_core=gap_core_area(overlap_geometry,GRID*5)
    paint_error=max((float(np.abs(t[:,2]-z_at(c,t[:,:2])-PAINT_GAP).max()) for t,c,_ in paint_checks),default=0.)
    # Affine difference reaches its extrema at overlap polygon vertices, not centroids.
    lt=STRtree([s['poly'] for s in land]);join_errors=[];steps=[];shared_length=0.
    for a in flat:
        for ix in lt.query(a['poly'],predicate='intersects'):
            b=land[ix];inter=a['poly'].intersection(b['poly'])
            for line in parts(inter,'LineString'):
                xy=np.asarray(line.coords)[:,:2];step=z_at(b['plane'],xy)-z_at(a['plane'],xy)
                steps.extend(step);join_errors.extend(abs(step-LAND_RAISE));shared_length+=line.length
                if line.length>.001:relationships.append(dict(type='raised-road-boundary',a=a['id'],b=b['id'],lengthM=line.length,heightM=LAND_RAISE))
    from passage_space import walking_reserve
    physical_border=physical_land_boundary(ground_road,union([opening,transition_cut,walking_reserve(grade_connections,GRID)]),EXTENT,GRID*5)
    missing_curb_length=uncovered_length(physical_border,curb_front,.00005)
    curb_report.update(roadBorderLengthM=physical_border.length,frontLengthM=curb_front.length,
        uncoveredRoadBorderM=missing_curb_length,coverageToleranceM=.001,
        minRoadLandStepM=min(steps,default=0),maxRoadLandStepM=max(steps,default=0),
        maxStepDeviationM=max(join_errors,default=0))
    blocked_land=lg.intersection(transition_cut).area
    blocked_curbs=curb_band.intersection(transition_cut).area
    mouth_checks=[]
    all_roads=[s for s in surfaces if s['kind'].startswith('roadbed') or s['kind'] in ('land','curb_top')]
    road_tree=STRtree([s['poly'] for s in all_roads])
    from connection_support import is_landing,landing_offset,obstruction_area,physical_gate
    for connection in grade_connections:
        line=sh.geometry.shape(connection['mouthGeometry'])
        # A section inside the road width excludes legitimate lateral edges.
        inner=substring(line,.05,line.length-.05)
        gate=inner.buffer(.001,cap_style='flat')
        at_ground=connection.get('atGround',True)
        pedestrian=connection.get('transport')=='pedestrian' and connection['peerKind']=='pedestrian_ground'
        railway=connection.get('peerKind')=='railway_ground'
        # Same-height sidewalk is the pedestrian landing, not an obstruction.
        # Serialized free-volume checks still reject any wall ABOVE that floor.
        local=[all_roads[int(i)] for i in road_tree.query(gate.buffer(.002))]
        floors=[s for s in local if s['owner'] in connection['sourceParents'] and s['kind']==connection['kind'] and s['tiers']==connection['level']]
        peers=[s for s in local if s['owner'] in connection.get('peerParents',connection.get('groundParents',[])) and is_landing(s,connection)]
        raw_gate_area=gate.area
        gate=physical_gate(gate,floors,peers,connection.get('connectorGeometry'))
        land_area=obstruction_area(gate,[s for s in local if s['kind'] in ('land','curb_top')],floors) if at_ground and not (pedestrian or railway) else 0.
        curb_area=obstruction_area(gate,[s for s in local if s['kind']=='curb_top'],floors) if at_ground and not railway else 0.
        joins=[];sample_count=0
        for pos in np.linspace(.05,line.length-.05,max(3,int(np.ceil(line.length))+1)):
            point=line.interpolate(pos);xy=np.array([point.x,point.y])
            x,y=xy;tolerance=GRID*5
            candidates=road_tree.query(sh.box(x-tolerance,y-tolerance,x+tolerance,y+tolerance))
            nearby=[all_roads[int(i)] for i in candidates if all_roads[int(i)]['poly'].buffer(tolerance).covers(point)]
            a=[s for s in nearby if s['kind']==connection['kind'] and s['tiers']==connection['level']]
            b=[s for s in nearby if is_landing(s,connection)]
            matches=[abs(float(z_at(sa['plane'],xy)+landing_offset(sb,connection,LAND_RAISE)-z_at(sb['plane'],xy))) for sa in a for sb in b]
            if matches:joins.append(min(matches));sample_count+=1
        mouth_checks.append(dict(id=connection['id'],kind=connection['kind'],peerKind=connection['peerKind'],
            atGround=at_ground,widthM=line.length,
            checkedFloorGateAreaM2=gate.area,outsideFloorGateAreaM2=raw_gate_area-gate.area,
            raisedLandInPassageM2=land_area,curbInPassageM2=curb_area,samples=sample_count,
            maxRoadHeightMismatchM=max(joins,default=999),
            passed=bool(land_area<.0001 and curb_area<.0001 and sample_count>=3 and max(joins)<.003)))
    transition_report=dict(connections=mouth_checks,interfaceCoverage=interface_report,terrainCutAreaM2=transition_cut.area,
        raisedLandInsideCutM2=blocked_land,curbInsideCutM2=blocked_curbs,
        connectorAreaM2=sum(r['connectorAreaM2'] for r in grade_connections),
        passed=bool(interface_report['passed'] and blocked_land<.01 and blocked_curbs<.01 and all(r['passed'] for r in mouth_checks)))
    report=dict(surfaceCells=len(surfaces),roadLandOverlapM2=overlap,roadLandOverlapCoreM2=overlap_core,uncoveredGroundM2=gap,
        uncoveredGroundCoreM2=gap_core,groundPositionToleranceM=GRID*5,openingAreaM2=opening.area,
        gradeConnections=transition_report,
        roadLandSharedBoundaryM=shared_length,expectedRoadLandStepM=LAND_RAISE,
        maxRoadLandStepDeviationM=max(join_errors,default=0),curbs=curb_report,
        paintTrianglesChecked=len(paint_checks),maxPaintOffsetErrorM=paint_error,
        paintOffsetM=PAINT_GAP,areaToleranceM2=.01,heightToleranceM=.001)
    seam_checks=[]
    road_interior=ground_road.buffer(-.001)
    interior_mask=SpatialMask(road_interior)
    for repair in [r for r in slit_repairs if r['type']=='two-sided-road-seam']:
        # Exclude the true outer road edge at a seam's end, but include both old
        # crack banks. A repaired crack may not retain raised land or any curb.
        gate=sh.geometry.shape(repair['geometry']).buffer(GRID*5)
        gate=gate.intersection(interior_mask.near(gate))
        raised_geometry=land_mask.near(gate).intersection(gate);curb_geometry=curb_mask.near(gate).intersection(gate)
        raised=raised_geometry.area;curb_area=curb_geometry.area
        raised_core=gap_core_area(raised_geometry,GRID*5);curb_core=gap_core_area(curb_geometry,GRID*5)
        curb_length=front_mask.near(gate).intersection(gate).length;uncovered=gate.difference(flat_mask.near(gate)).area
        uncovered_beyond_precision=gate.difference(flat_mask.near(gate.buffer(GRID*5)).buffer(GRID*5)).area
        seam_checks.append(dict(sourceParents=repair['sourceParents'],areaM2=repair['areaM2'],
            raisedLandM2=raised,raisedLandCoreM2=raised_core,curbAreaM2=curb_area,curbCoreM2=curb_core,curbFrontM=curb_length,missingAsphaltM2=uncovered,
            missingAsphaltBeyondToleranceM2=uncovered_beyond_precision,
            passed=bool(raised_core<1e-8 and curb_core<1e-8 and curb_length<.001 and uncovered_beyond_precision<1e-7)))
    report['roadSeams']={**road_seam_report,'checks':seam_checks,
        'passed':bool(not road_seam_report['remainingRepairableSeams'] and all(r['passed'] for r in seam_checks))}
    from paint_support import audit as audit_paint_support
    paint_support=audit_paint_support(paint_checks,surfaces,GRID*5)
    report['sourceStyle']=dict(markings=style_checks,
        sourceCoveragePassed=all(c['passed'] for c in style_checks),
        sourceCoverageIssues=sum(not c['passed'] for c in style_checks),
        emittedPaint=paint_support,passed=paint_support['passed'],
        policy='Retain original source direction and modifier; emit only the intersection with confirmed asphalt of the matching tier. Record unsupported source lines as input discrepancies; never expand the road or move paint to accommodate them.')
    report['semantics']=audit_semantics(records)
    report['tunnelWalls']=wall_report
    report['passed']=bool(overlap_core<1e-8 and gap_core<1e-8 and paint_error<1e-6 and max(join_errors,default=0)<.001 and missing_curb_length<.001 and transition_report['passed'] and report['roadSeams']['passed'] and report['sourceStyle']['passed'] and report['semantics']['passed'] and wall_report['passed'])
    return report

def witness_report():
    checks=[]
    for label,xy in [('entrance-flattening',[2043.7211100260417,8066.17626953125]),('independent-triangulation',[2132.1951497395835,8064.317220052083])]:
        point=sh.Point(xy);before=defaultdict(list);after=defaultdict(list)
        for (name,mat),ts in old_groups.items():
            if name not in ['Main_Roadbed','Administrative_quarter','Neom_road_area']:continue
            for tri in ts:
                if Polygon(tri[:,:2]).covers(point):before[name].append(float(z_at(plane(tri),xy)))
        for s in surfaces:
            if s['poly'].covers(point):after[s['kind']].append(dict(z=float(z_at(s['plane'],xy)),owner=s['owner']))
        checks.append(dict(name=label,xy=xy,before=dict(before),after=dict(after),
            passed=bool('roadbed_flat' in after and 'land' not in after)))
    return checks

if __name__=='__main__':
    start=time.time();DATA.mkdir(parents=True,exist_ok=True)
    candidates,model=source_data();dem,demtree=make_dem();print('SOURCE',len(records),'CANDIDATES',len(candidates),'DEM',len(dem),flush=True)
    opening,roads=build_surfaces(candidates);print('SURFACES',len(surfaces),flush=True)
    paint_checks,total,bound=legacy_and_paint(model);print('PAINT',bound,'/',total,flush=True)
    wall_count=walls(opening,roads)
    report=validate(opening,roads,paint_checks)
    report['overpassProfiles']=[{k:v for k,v in p.items() if k not in ['asphaltGeometry','deckGeometry','parapetGeometry','extensionHeightCells','groundEntryGeometry','shoulderGeometry','shoulderRiserGeometry','groundShoulderConnectionGeometry']} for p in overpass_profiles]
    report['passed'] &= all(p['passed'] for p in overpass_profiles)
    report['witnesses']=witness_report()
    report['passed'] &= all(w['passed'] for w in report['witnesses'])
    report['roadQuality']=road_quality(surfaces,protected_road_islands)
    report['passed'] &= report['roadQuality']['passed']
    report.update(sourceFeatures=len(records),sourceTiles=sorted({r['source']['tile'] for r in records}),boundsMSK=B,terrainSeams=dem_report,
        roadProfiles=road_model.report,roadSlitRepairs=slit_repairs,
        paintAreaM2=total,boundPaintAreaM2=bound,inferredWallSegments=wall_count,inferredDeckEdgeSegments=deck_count,unresolved=unresolved,
        baseline=export(DATA/'before',old_groups),prototype=export(DATA/'after',groups),seconds=time.time()-start)
    plan=load_plan(SOURCE)
    city=dict(version=6,boundsMSK=B,originMSK=ORIGIN.tolist(),crsProj=plan['crs_proj'],sourceStyle=source_style,sourceStyleChecks=style_checks,verticalReference='2GIS relative map ground; not surveyed absolute elevations',terrainSeams=dem_report,precisionGridM=GRID,features=records,
        roadProfiles=road_model.axes,roadNodes=road_model.nodes,roadJunctions=road_model.junctions,
        roadHeightModel=road_model.report,roadHeightControlGrid=road_model.controls(),roadSlitRepairs=slit_repairs,roadSeamChecks=report['roadSeams'],
        surfaces=[{**{k:v for k,v in s.items() if k not in ['poly','plane']},'geometry':mapping(s['poly']),'heightPlane':s['plane'].tolist()} for s in surfaces],relationships=relationships,
        curbs=curb_report,curbBandGeometry=mapping(curb_band),overpassProfiles=overpass_profiles,
        roadInterfaces=road_interfaces,gradeConnections=grade_connections,transitionTerrainCutGeometry=mapping(transition_cut),
        rules=dict(surfacePartition='per physical level; flat road excludes open descents; land and curb tops partition the remaining ground',heights='shared C2 B-spline road height model; 20 m land transition to source DEM; non-road ground is raised 0.10 m; source relative road levels preserved; common 3 m tessellation',curbs='0.10 m high, 0.15 m wide solids on the land side of the unified ground-road border; no per-feature or tile-edge borders; replace legacy ground curb meshes',overpasses='source overpass ramps from relative height zero; concrete 1 m outward on each side; shoulder tops 0.10 m above asphalt with closed inner riser; underside 1 m below asphalt; parapet tops 0.70 m above asphalt / 0.20 m wide at outer edges; no transverse parapets at ground entries or crop cuts',paint=PAINT_POLICY,landPriority='pedestrian > vegetation > specific territory > administrative background',walls='derived thin lining at open descent perimeter, excluding tunnel continuation; not surveyed wall solids'),
        limitations=['Lane connectivity, measured crown/crossfall and engineering road profiles are not reconstructed. Reference-line junctions and sampled sections are derived from the map.','Paint XY/color comes from the corrected Blender extraction; parent binding is recomputed.','No buildings, trees, detailed stair treads or measured tunnel wall thickness in this crop. Overpass dimensions are reconstruction rules: 1 m side overhang, shoulder roof 0.10 m above asphalt, underside 1 m below asphalt, parapet top 0.70 m above asphalt, 0.20 m parapet width.','Raised land and curb dimensions are user-defined reconstruction rules, not source measurements. Ground curbs terminate at source-confirmed grade connections. Dropped pedestrian kerbs are not yet modelled.','Spatial surface records retain source identity; production streaming is not implemented.'])
    city['rules']['gradeConnections']='shared road boundaries with opposite interiors and equal heights establish connectivity across classes/tiers; every source interface is audited before solids; zero-relative-height ground mouths may bridge small recorded source gaps; curb stops across passage; raised ground excludes the connected ramp slab until its underside clears the raised land; high spans preserve the ground below; determine outside from the original mouth before extension, reject ambiguous orientation, cut one continuously joined outside strip across the complete noded mouth, remove precision-grid roof remnants and reject detached concrete islands; no XY-only level connection'
    city['rules']['roadContinuity']='resolve source contour gaps up to 5 cm only between opposing asphalt banks on one consistent physical level; preserve explicit land and islands; derive raised land and curbs afterward; block export if any repairable gap or barrier remains inside a repaired passage'
    city['rules']['pedestrianOverpasses']='retain source pedestrian styles 241413/609252; walking deck follows raised sidewalk datum +0.10 m; open full-width mouths at confirmed uncut same-level pedestrian endpoint connections; retain lateral rails'
    city['rules']['railwayEntries']=RAILWAY_ENTRY_POLICY
    city['rules']['paint']=PAINT_POLICY
    city['tunnelWalls']=wall_report
    city['rules']['walls']=wall_report['policy']
    city['limitations'][1]='Stop/tram-stop paint is rebuilt from source line modifiers. Other paint XY/color comes from corrected Blender extraction; parent binding is recomputed.'
    (DATA/'urban-model.json').write_text(json.dumps(city,ensure_ascii=False,separators=(',',':')))
    (DATA/'validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    np.savez_compressed(HERE/'surface-audit.npz',**{f'g{i}':np.asarray(ts) for i,ts in enumerate(groups.values()) if ts})
    print(json.dumps({k:v for k,v in report.items() if k!='unresolved'},indent=2),flush=True)
    print('UNRESOLVED',dict(Counter(r['type'] for r in unresolved)),flush=True)
