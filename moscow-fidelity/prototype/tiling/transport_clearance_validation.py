"""Source-derived wide clearance checks for vehicle and pedestrian structures.

The old interface plane remains useful, but cannot detect a cap placed outside
it. Audit both approaches and entire exposed descents against serialized faces.
Source topology supplies the expected corridor; generated barriers cannot shrink
it. This is an obstruction regression check, not a transport clearance standard.
"""
import json
import sys
from collections import Counter
from pathlib import Path
import numpy as np
import shapely as sh
from shapely.geometry import Polygon,LineString,shape,mapping
from shapely.ops import substring
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from semantics import classify
from transitions import shared_interfaces,discover,parts,union
from pedestrian import discover as pedestrian_connections
from build import z_at
from curbs import LAND_RAISE
from railway_surfaces import confirmed_owners
from railway_tunnel_validation import volume_cells
from interface_validation import check_interfaces,clipped_polygon,BARRIERS
from prepare_railway_entries import load_terrain,near_passages,meshes
from portal_guards import parallel_to_source

PRECISION=1e-5
DEPTH=1.05
INSET=.05

def source_terminal_evidence(poly,rows,arches,extent):
    """A displayed portal can end without a retained buried tunnel mesh.

    Zero relative height supplies ground-contact evidence; tunnel_arch supplies
    a deep portal independently of the inferred walls. Neither invents a route
    or changes the generated passage geometry.
    """
    boundary=poly.boundary.difference(extent.boundary.buffer(PRECISION*5))
    ground=[];deep=[];source_ids=set();all_heights=[]
    for row in rows:
        for patch,coefficients in row['patches']:
            for face in parts(patch.intersection(poly)):
                all_heights.extend(z_at(coefficients,np.asarray(face.exterior.coords)[:,:2]))
                for ring in face.interiors:
                    all_heights.extend(z_at(coefficients,np.asarray(ring.coords)[:,:2]))
            for edge in parts(boundary.intersection(patch.buffer(PRECISION*2)),'LineString'):
                for a,b in zip(edge.coords,list(edge.coords)[1:]):
                    line=LineString([a,b]);heights=z_at(coefficients,[a,b])
                    if line.length<.05:continue
                    if np.max(np.abs(heights))<.002:ground.append(line)
                    if np.max(heights)>-1:continue
                    for rid,arch in arches:
                        if not line.intersects(arch.buffer(.05,cap_style='flat')):continue
                        for contact in parts(line.intersection(arch.buffer(.05,cap_style='flat')),'LineString'):
                            if parallel_to_source(contact,arch):deep.append(contact);source_ids.add(rid)
    return dict(groundLevelBoundaryM=union(ground,PRECISION).length,
                sourcePortalBoundaryM=union(deep,PRECISION).length,sourcePortalIds=sorted(source_ids),
                terrainLevelWalkingSurface=bool(all_heights and np.max(np.abs(all_heights))<.002))


def source_candidates(city):
    extent=sh.box(*city['boundsMSK']);result=[]
    for f in city['features']:
        semantic=classify(f['layer'],f['properties'],f['geometryType'])
        if semantic.get('kind')!='road':continue
        xyz=np.asarray(f['coordinates']);patches=[]
        for i in range(len(xyz)-2):
            t=xyz[i:i+3];a=np.column_stack((t[:,:2],np.ones(3)))
            if abs(np.linalg.det(a))<1e-8:continue
            p=sh.set_precision(sh.make_valid(Polygon(t[:,:2])),PRECISION).intersection(extent)
            if p.area>1e-9:patches.append((p,np.linalg.solve(a,t[:,2])))
        if patches:
            result.append(dict(id=f['id'],kind='road',part=f['properties'].get('db_road_part','roadbed_flat'),
                tiers=f['properties'].get('db_tiers') or [0],purpose=semantic['purpose'],
                transport='pedestrian' if semantic['purpose']=='pedestrian' else 'vehicle',
                poly=union([p for p,c in patches],PRECISION),patches=patches))
    return result


def inventory(city):
    if len(city['features'])<1000:return build_inventory(city)
    from source_topology_cache import cached_inventory
    cache=Path(__file__).resolve().parents[2]/'web-preview/prototype/tiles/.source-topology-cache'
    return cached_inventory(city,build_inventory,cache)


def build_inventory(city):
    rows=source_candidates(city);extent=sh.box(*city['boundsMSK'])
    rail={r['source'] for r in confirmed_owners(city['features'],PRECISION)}
    roads=[r for r in rows if r['transport']=='vehicle']
    walking=[r for r in rows if r['transport']=='pedestrian']
    interfaces=shared_interfaces(roads,extent,PRECISION,z_at)
    interfaces=[r for r in interfaces if not any(p in rail for e in r['ends'] for p in e['parents'])]
    for r in interfaces:r['mode']='vehicle'
    ground=shape(city['groundRoadGeometry'])
    connections,_=discover(roads,ground,extent,PRECISION,z_at,interfaces)
    # Check full recovered mouths as well as exact source contacts. They may
    # contain a short generated asphalt connector or several source fragments.
    for c in connections:
        if c['peerKind']!='roadbed_flat' or any(p in rail for p in c['sourceParents']):continue
        line=shape(c['mouthGeometry'])
        known=union([shape(r['mouthGeometry']) for r in interfaces],PRECISION)
        if line.difference(known.buffer(PRECISION*5)).length<.001:continue
        interfaces.append(dict(id='vehicle-ground:'+c['id'],mode='vehicle',mouthGeometry=c['mouthGeometry'],
            mouthWidthM=c['mouthWidthM'],atGround=True,relativeHeightsM=c['relativeHeightsM'],
            ends=[dict(kind=c['kind'],level=c['level'],parents=c['sourceParents']),
                  dict(kind='roadbed_flat',level=[0],parents=c['peerParents'])],
            connectorGeometry=c['connectorGeometry']))
    for r in shared_interfaces(walking,extent,PRECISION,z_at):
        r['id']='pedestrian-'+r['id'];r['mode']='pedestrian';interfaces.append(r)
    # Source connectivity also includes shared grade-zero nodes leading onto
    # asphalt or to another structure. Audit their entrances even if the older
    # construction registry omitted them; emitted geometry cannot decide which
    # passages the independent check is allowed to inspect.
    _,ground_walk=pedestrian_connections(walking,city['features'],ground,extent,PRECISION,z_at,include_mixed_ground=True)
    for r in ground_walk:r['mode']='pedestrian'
    interfaces.extend(ground_walk)
    components=[]
    for mode in ('vehicle','pedestrian'):
        arches=[(f['id'],LineString(np.asarray(f['coordinates'])[:,:2])) for f in city['features']
                if f['properties'].get('db_road_part')=='tunnel_arch' and len(f['coordinates'])>1
                and (f['layer']=='Roadbed_outline_underpasses')==(mode=='pedestrian')]
        descents=[r for r in rows if r['transport']==mode and r['part']=='roadbed_tunnel_descent' and r['id'] not in rail]
        for level in sorted({tuple(r['tiers']) for r in descents}):
            rr=[r for r in descents if tuple(r['tiers'])==level]
            for poly in parts(union([r['poly'] for r in rr],PRECISION)):
                parents={r['id'] for r in rr if r['poly'].intersection(poly).area>PRECISION**2}
                joins=[r for r in interfaces if any(e['kind']=='roadbed_tunnel_descent' and parents.intersection(e['parents']) for e in r['ends'])]
                deep=[r for r in joins if any(e['kind']=='roadbed_tunnel' for e in r['ends'])]
                upper=[r for r in joins if any(e['kind'] in ('roadbed_flat','roadbed_overpass','pedestrian_ground') for e in r['ends'])]
                clipped=poly.distance(extent.boundary)<PRECISION*5
                evidence=source_terminal_evidence(poly,[r for r in rr if r['id'] in parents],arches,extent)
                # A zero-height edge alone is not evidence of a traversable
                # entrance: retain the explicit connectivity requirement.
                source_upper=bool(upper)
                source_deep=bool(deep or evidence['sourcePortalBoundaryM']>.25)
                components.append(dict(id=f'{mode}-descent:{len(components)}',mode=mode,level=list(level),
                    poly=poly,parents=sorted(parents),joins=joins,upperEntries=len(upper),deepPortals=len(deep),
                    sourceTerminals=evidence,regionClipped=clipped,
                    passed=bool((source_upper and source_deep) or (mode=='pedestrian' and evidence['terrainLevelWalkingSurface']) or clipped)))
    return rows,interfaces,components


def volumes(city,dem,demtree):
    rows,interfaces,components=inventory(city);byid={r['id']:r for r in rows}
    # Every outward approach refers to the same immutable ground-road shape.
    # Decode it once, rather than rebuilding the whole city's coordinate tree
    # twice per walking entrance (full width and centre strip).
    ground_road=shape(city['groundRoadGeometry'])
    floors=[s for s in city['surfaces'] if s['kind'].startswith('roadbed')]
    polys=[shape(s['geometry']) for s in floors];tree=sh.STRtree(polys)
    result=[];cores=[];coverage=[];covered_interfaces=[]

    def floor_cells(gate,mode,end_keys):
        cells=[];covered=[]
        selected=[]
        for i in tree.query(gate,predicate='intersects'):
            s=floors[int(i)];r=byid.get(s['owner'])
            if not r or r['transport']!=mode or (s['kind'],tuple(s['tiers'])) not in end_keys:continue
            piece=gate.intersection(polys[int(i)])
            selected.append((s,piece))
        # Source ground polygons can continue under a rising connected ramp.
        # The exposed floor there is the structural slab, not the lower ground
        # polygon. Its buried end face is not an obstacle above the road.
        structural=union([p for s,p in selected if s['kind']!='roadbed_flat'],PRECISION)
        for s,piece in selected:
            if s['kind']=='roadbed_flat':piece=piece.difference(structural)
            cells.extend(volume_cells(piece,s['heightPlane'],city['originMSK'],.02,.75));covered.append(piece)
        return cells,union(covered,PRECISION)

    def entry_cells(gate,r,outside):
        keys={(e['kind'],tuple(e['level'])) for e in r['ends']}
        cells,covered=floor_cells(gate,r['mode'],keys)
        if not outside.is_empty:
            # A confirmed walking node can open onto asphalt. Use its real
            # canonical floor there, not an invented raised sidewalk plane.
            asphalt=outside.intersection(ground_road)
            for i in tree.query(asphalt,predicate='intersects'):
                s=floors[int(i)]
                if s['kind']!='roadbed_flat' or s['tiers']!=[0]:continue
                piece=gate.intersection(asphalt).intersection(polys[int(i)])
                cells.extend(volume_cells(piece,s['heightPlane'],city['originMSK'],.02,.75))
                covered=covered.union(piece)
            pavement=outside.difference(asphalt)
            for i in demtree.query(pavement,predicate='intersects'):
                p,c=dem[int(i)];piece=gate.intersection(pavement).intersection(p)
                cells.extend(volume_cells(piece,np.asarray(c)+[0,0,LAND_RAISE],city['originMSK'],.02,.75))
                covered=covered.union(piece)
        return cells,covered

    for r in interfaces:
        if all(e['kind']=='roadbed_tunnel' for e in r['ends']):
            covered_interfaces.append(dict(id=r['id'],reason='both source ends are covered tunnel interiors; not an exposed entrance or descent'))
            continue
        line=shape(r['mouthGeometry']);gate=line.buffer(DEPTH,cap_style='flat')
        source=union([byid[p]['poly'] for e in r['ends'] for p in e['parents'] if p in byid],PRECISION)
        # True lateral edges and medians are outside the passage. A curved or
        # flared source corridor must not be replaced by a rectangular lane.
        walking_ground=any(e['kind']=='pedestrian_ground' for e in r['ends'])
        outside=Polygon()
        if walking_ground:
            # A ground approach is on the OUTWARD side of the source mouth.
            # Extending a rectangle backwards beside a curved ramp invents
            # walkable ground where its legitimate retaining wall stands.
            # Resolve the side from raw source floor geometry, independently
            # of generated landing/wall records. Never shrink the actual ramp.
            approach=[]
            for a,b in zip(line.coords,list(line.coords)[1:]):
                a=np.asarray(a);b=np.asarray(b);n=np.array([-(b-a)[1],(b-a)[0]])
                n/=np.linalg.norm(n);mid=(a+b)/2
                left=source.covers(sh.Point(mid+n*.001));right=source.covers(sh.Point(mid-n*.001))
                assert left!=right,('Ambiguous source entrance',r['id'])
                n*=(-1 if left else 1)*DEPTH
                approach.append(Polygon([a,b,b+n,a+n]))
            outside=union(approach,PRECISION).difference(source)
        if walking_ground:source=source.union(outside)
        if r.get('connectorGeometry'):source=source.union(shape(r['connectorGeometry']))
        gate=gate.intersection(source.buffer(-INSET))
        cells,covered=entry_cells(gate,r,outside)
        missing=gate.difference(covered.buffer(PRECISION*5)).area
        coverage.append(dict(id=r['id'],expectedAreaM2=gate.area,missingFloorM2=missing,passed=bool(cells and missing<.001)))
        if cells:result.append((r,cells))
        # A transverse cap necessarily crosses the middle of a passage.
        # Separately retain ALL full-width contacts, rather than dismissing
        # lateral walls, garden edging or small intrusions as a clean pass.
        core=gate.intersection(substring(line,line.length*.25,line.length*.75).buffer(DEPTH,cap_style='flat'))
        core_cells,core_covered=entry_cells(core,r,outside)
        assert core_cells and core.difference(core_covered.buffer(PRECISION*5)).area<.001,r['id']
        cores.append((r,core_cells))
    for c in components:
        mouths=union([shape(r['mouthGeometry']) for r in c['joins']],PRECISION)
        lateral=c['poly'].boundary.difference(mouths.buffer(PRECISION*5))
        gate=c['poly'].difference(lateral.buffer(INSET))
        cells,covered=floor_cells(gate,c['mode'],{('roadbed_tunnel_descent',tuple(c['level']))})
        missing=gate.difference(covered.buffer(PRECISION*5)).area
        coverage.append(dict(id=c['id'],expectedAreaM2=gate.area,missingFloorM2=missing,passed=bool(cells and missing<.001)))
        if cells:result.append((dict(id=c['id'],mouthWidthM=0,ends=[dict(kind='descent_corridor')]),cells))
        width=min(shape(r['mouthGeometry']).length for r in c['joins']) if c['joins'] else 0
        core=c['poly'].difference(lateral.buffer(max(INSET,width*.25)))
        core_cells,core_covered=floor_cells(core,c['mode'],{('roadbed_tunnel_descent',tuple(c['level']))})
        assert core_cells and core.difference(core_covered.buffer(PRECISION*5)).area<.001,c['id']
        cores.append((dict(id=c['id'],mouthWidthM=0,ends=[dict(kind='descent_corridor')]),core_cells))
    source=dict(interfaces=len(interfaces),byMode=dict(Counter(r['mode'] for r in interfaces)),
        coveredInteriorInterfaces=covered_interfaces,
        groundWalkingEntries=sum(any(e['kind']=='pedestrian_ground' for e in r['ends']) for r in interfaces),
        corridors=[{k:v for k,v in c.items() if k not in ('poly','joins')} for c in components],floorCoverage=coverage)
    source['passed']=all(c['passed'] for c in components+coverage)
    return result,cores,source


def audit(city,dem,demtree,mesh_stream):
    gates,cores,source=volumes(city,dem,demtree)
    nearby=list(near_passages(mesh_stream,gates))
    result=check_interfaces(cores,nearby)
    full_width=check_interfaces(gates,nearby)
    byid={r['id']:(r,cells) for r,cells in cores}
    # A small kerb nib can be inside the centre strip without being a
    # transverse cap. Keep it as an unresolved contact, but distinguish it
    # from a barrier spanning the central half of the source mouth.
    for check in result['checks']:
        if check['passed']:continue
        if not check.get('precisionPassed',True):continue
        r,cells=byid[check['interface']]
        if not r.get('mouthGeometry'):continue  # Entire descent: conservative.
        line=shape(r['mouthGeometry']);intervals=[];ox,oy,_=city['originMSK']
        for name,ts in near_passages(nearby,[(r,cells)]):
            if name not in BARRIERS:continue
            for tri in ts:
                box=sh.box(*(tri[:,[0,2]].min(0)-1e-6),*(tri[:,[0,2]].max(0)+1e-6))
                for gate,planes in cells:
                    if not gate.intersects(box):continue
                    clipped=clipped_polygon(tri,planes)
                    if len(clipped)<3:continue
                    at=[line.project(sh.Point(x+ox,oy-z)) for x,y,z in clipped]
                    if max(at)-min(at)>1e-8:intervals.append(sh.LineString([(min(at),0),(max(at),0)]))
        fraction=sh.union_all(intervals).length/(line.length*.5) if intervals else 0.
        check.update(blockedCoreSpanFraction=fraction,passed=bool(fraction<.95))
    result.update(source=source,passed=all(c['passed'] for c in result['checks']) and source['passed'],halfWidthM=DEPTH,
        fullWidth=full_width,coreWidthFraction=.5,
        scope='source floor contours on both structure sides; full mouth width on outward ground approaches; entire exposed descents; fullWidth rejects every partial obstruction; centre-span classification retained for diagnostics')
    result['partialContacts']=[c for c in full_width['checks'] if not c['passed']]
    result['fullWidth']['halfWidthM']=DEPTH
    return result


if __name__=='__main__':
    root=Path(sys.argv[1]);city=json.loads((root/'canonical/urban-model.json').read_text())
    scene=json.loads((root/'canonical/full/scene.json').read_text());dem,tree=load_terrain(root)
    result=audit(city,dem,tree,meshes(root,scene))
    print(json.dumps(result,ensure_ascii=False,indent=2),flush=True)
    sys.exit(0 if result['passed'] else 1)
