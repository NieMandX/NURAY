"""Conservative source-change and dependency audit; never builds/replaces city meshes.

Local candidates are not a proof that all other meshes are reusable: the current
road height fitter is global. Report that separately, rather than hiding the
dependency behind a fixed halo. Source fragment indices are not persistent IDs.
"""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path
import sys
import numpy as np
import shapely as sh
from shapely.geometry import box, shape, Point, LineString
from pyproj import Transformer

REPO=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(REPO/'prototype'),str(REPO/'prototype/tiling'),str(REPO/'scripts')]
from semantics import classify
from source_objects import exterior_record, INFORMATION_LAYERS, BUILDING_LAYERS
from profiles import AXES
from streaming_json import Document
from audit_source_catalog import layer_selectors, strings


def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        while b:=f.read(1024*1024):h.update(b)
    return h.hexdigest()


def fingerprint(f):
    p=f['properties']
    props={k:v for k,v in p.items() if k.startswith('db_') or k in ('id','beginningIsCut','endingIsCut','componentDistanceStart','componentDistanceEnd')}
    return hashlib.sha256(json.dumps([props,f['_raw']],sort_keys=True,separators=(',',':')).encode()).hexdigest()


def coordinates(data,f,project):
    r=f['_raw'];info=data['tile_info']
    if not r.get('x'):return np.empty((0,2))
    x=info['offset'][0]+np.asarray(r['x'])*info['size']/32768
    y=info['offset'][1]+np.asarray(r['y'])*info['size']/32768
    lon=x/2**32*360;lat=np.degrees(np.arctan(np.sinh(y/2**32*2*np.pi)))
    return np.column_stack(project.transform(lon,lat))


def geometry(xy,typ):
    if not len(xy):return Point()
    if typ=='polyline' and len(xy)>1:return LineString(xy)
    if typ=='polygon' and len(xy)>2:
        triangles=sh.polygons(np.stack([xy[:-2],xy[1:-1],xy[2:]],axis=1))
        return sh.union_all(triangles[sh.area(triangles)>1e-9])
    return sh.union_all(sh.points(xy))


def analyze(base,new,release,out):
    oldplan=json.loads((base/'plan.json').read_text());plan=json.loads((new/'plan.json').read_text())
    assert oldplan['crs_proj']==plan['crs_proj']
    bounds=oldplan['extent_msk_east_north'];extent=box(*bounds)
    target=plan['extent_msk_east_north'];size=250
    project=Transformer.from_crs('EPSG:4326',plan['crs_proj'],always_xy=True)
    oldflat=json.loads((base/'source/style_flat.json').read_text());newflat=json.loads((new/'source/style_flat.json').read_text())
    oldrules={str(r['id']):r for r in oldflat};newrules={str(r['id']):r for r in newflat}
    model_layers=set()
    for r in oldflat+newflat:
        if r.get('type')=='model':model_layers.update(layer_selectors(r.get('filter')))
    def physical(p):
        l=p['db_sublayer'];typ=p.get('db_geometry_type')
        if not exterior_record(p) or l in INFORMATION_LAYERS:return False
        s=classify(l,p,typ)
        return (s['status'] in ('built','legacy-marking','source-modifier','source-boundary') or l in BUILDING_LAYERS|model_layers|AXES|
            {'Railroad_line','Railroad_tunnel_line','Fence','Low_fence','Temporary_fence','Retaining_wall','Embankment','Road_support_column','Road_support_crossbar'} or l.startswith('Pedestrian_road'))
    tile_rows=[];polys=[]
    for n in range(20):
        for e in range(20):
            b=[bounds[0]+e*size,bounds[1]+n*size,bounds[0]+(e+1)*size,bounds[1]+(n+1)*size]
            tile_rows.append(dict(oldTile=f'{e}-{n}',expandedTile=f'{e+8}-{n+8}',boundsMSK=b,reasons=set(),layers=set(),evidence=set()))
            polys.append(box(*b))
    tree=sh.STRtree(polys);evidence=[]
    def mark(g,reason,layers=(),detail=None,pad=0):
        if g.is_empty:return []
        if pad:g=g.buffer(pad)
        hits=list(map(int,tree.query(g,predicate='intersects')))
        if not hits:return []
        eid=len(evidence)
        evidence.append(dict(id=eid,reason=reason,layers=list(layers),boundsMSK=list(g.bounds),oldTiles=[tile_rows[i]['oldTile'] for i in hits],detail=detail))
        for i in hits:
            tile_rows[i]['reasons'].add(reason);tile_rows[i]['layers'].update(layers);tile_rows[i]['evidence'].add(eid)
        return hits
    # One old transport-tile ring is a deliberately conservative scheduling
    # unit, not a claimed maximum dependency radius.
    mark(extent.difference(extent.buffer(-249.99)), 'boundary-context',detail='One 250 m inner ring for the newly supplied outside context.')
    oldtiles={tuple(t[:3]) for t in oldplan['tiles']};newtiles={tuple(t[:3]) for t in plan['tiles']}
    assert oldtiles<=newtiles
    changes=[];changed_ids=set();hash_stats=Counter();changed_by_layer=Counter();ignored=Counter();moved=0
    baseline_features={};dem_changed=[];direct_geoms=[]
    for tile in sorted(oldtiles):
        key='_'.join(map(str,tile));op=base/'source/cache';npth=new/'source/cache'
        for suffix in ('.pbf','.ald.json'):
            hash_stats[f'{suffix}:same' if sha(op/(key+suffix))==sha(npth/(key+suffix)) else f'{suffix}:changed']+=1
        if sha(op/f'dem_{key}.bin')!=sha(npth/f'dem_{key}.bin'):
            dem_changed.append(key)
            d=json.loads((op/f'dem_{key}.json').read_text());info=d['tile_info'];a=np.asarray(d['positions']).reshape(-1,2)
            xy=coordinates({'tile_info':info},{'_raw':{'x':a[:,0].tolist(),'y':a[:,1].tolist()}},project)
            mark(box(*[*xy.min(0),*xy.max(0)]),'changed-dem',detail=key,pad=25)
        a=json.loads((op/(key+'.json')).read_text());b=json.loads((npth/(key+'.json')).read_text())
        lookup=defaultdict(list)
        for i,f in enumerate(b['features']):lookup[fingerprint(f)].append(i)
        consumed=set()
        for i,f in enumerate(a['features']):
            h=fingerprint(f);p=f['properties'];l=p['db_sublayer'];rid=f'2gis:{key}:{i}'
            if physical(p):
                xy=coordinates(a,f,project)
                if len(xy):baseline_features[rid]=dict(layer=l,properties=p,xy=xy,geometryType=p['db_geometry_type'])
            if lookup[h]:
                j=lookup[h].pop();consumed.add(j);moved+=int(i!=j)
                continue
            if not physical(p):ignored[l]+=1;continue
            xy=coordinates(a,f,project);g=geometry(xy,p['db_geometry_type'])
            if not g.intersects(extent):continue
            changed_ids.add(rid);changed_by_layer[l]+=1
            row=dict(side='old',source=rid,layer=l,providerId=p.get('id'),boundsMSK=list(g.bounds),fingerprint=h)
            changes.append(row);direct_geoms.append(g)
            mark(g,'changed-source',[l],row,pad=25)
        for i,f in enumerate(b['features']):
            if i in consumed:continue
            p=f['properties'];l=p['db_sublayer']
            if not physical(p):ignored[l]+=1;continue
            g=geometry(coordinates(b,f,project),p['db_geometry_type'])
            if not g.intersects(extent):continue
            changed_by_layer[l]+=1
            row=dict(side='new',source=f'2gis:{key}:{i}',layer=l,providerId=p.get('id'),boundsMSK=list(g.bounds),fingerprint=fingerprint(f))
            changes.append(row);direct_geoms.append(g)
            mark(g,'changed-source',[l],row,pad=25)
        print('COMPARE',key,'physical changes',len(changes),flush=True)
    direct_union=sh.union_all(direct_geoms) if direct_geoms else Point()
    # Changed physical styles are independent of feature bytes. Ignore editor
    # names and metadata; compare rules that can affect generated geometry/material.
    style_changes=[];style_layers=set()
    def style_signature(r):return {k:r.get(k) for k in ('type','filter','style','drawToTarget','order')}
    for rid in sorted(oldrules.keys()|newrules.keys()):
        a=oldrules.get(rid,{});b=newrules.get(rid,{})
        if style_signature(a)==style_signature(b):continue
        layers=layer_selectors(a.get('filter'))|layer_selectors(b.get('filter'))
        applicable={l for l in layers if physical({'db_sublayer':l,'db_geometry_type':'polygon'})}
        if applicable:style_changes.append(dict(id=rid,layers=sorted(applicable)));style_layers.update(applicable)
    for rid,f in baseline_features.items():
        if f['layer'] in style_layers:
            g=geometry(f['xy'],f['geometryType']);mark(g,'changed-style',[f['layer']],rid,pad=5)
    doc=Document(release/'canonical/urban-model.json')
    # Propagate complete structural sheets, not merely a generic one-tile halo.
    profiles=[]
    for i,p in enumerate(doc.items('overpassProfiles')):
        g=shape(p['deckGeometry']);parents=set(p['sourceParents'])
        reasons=[]
        if g.distance(extent.boundary)<.05:reasons.append('crosses-old-boundary')
        if parents&changed_ids:reasons.append('changed-source-parent')
        if not direct_union.is_empty and g.distance(direct_union)<25:reasons.append('near-source-change')
        if not reasons:continue
        detail=dict(profile=i,transport=p['transport'],levels=p['level'],causes=reasons,parents=sorted(parents),boundsMSK=list(g.bounds))
        profiles.append(detail);mark(g,'structural-sheet',[p['transport']],detail,pad=25)
    # Railway longitudinal UVs are rooted per connected component. Extending
    # one component can shift its phase far from the old extraction edge.
    railway=doc.read('railwayLayer');components=defaultdict(list)
    for e in railway['edges']:components[e['component']].append(e)
    rail_dependencies=[]
    for component,edges in components.items():
        geometries=[];touch=False
        for e in edges:
            f=baseline_features.get(e['source'])
            if not f:continue
            g=geometry(f['xy'],f['geometryType']);geometries.append(g)
            if g.distance(extent.boundary)<.05 or e['source'] in changed_ids:touch=True
        if touch and geometries:
            g=sh.union_all(geometries);detail=dict(component=component,sources=[e['source'] for e in edges],boundsMSK=list(g.bounds))
            rail_dependencies.append(detail);mark(g,'railway-component-uv',['Railroad_line'],detail,pad=5)
    # Buildings share a rigid terrain anchor across all fragments of a provider
    # object. Extending the footprint can move the anchor in the current builder.
    buildings=defaultdict(list)
    for rid,f in baseline_features.items():
        if f['layer'] in BUILDING_LAYERS:
            key=f['properties'].get('id')
            if key:buildings[str(key)].append((rid,f))
    building_dependencies=[]
    for bid,rows in buildings.items():
        xy=np.concatenate([f['xy'] for _,f in rows]);g=box(*[*xy.min(0),*xy.max(0)])
        if not g.intersects(extent):continue
        if g.intersects(extent.boundary) or any(rid in changed_ids for rid,_ in rows):
            detail=dict(buildingId=bid,sourceFragments=len(rows),boundsMSK=list(g.bounds))
            building_dependencies.append(detail);mark(g,'building-group', ['building'],detail,pad=5)
    # Detailed GLBs have their own channel, and may cover more than their anchor.
    def model_index(root,p):
        data=json.loads((root/'output'/p.get('output_subdir','area_5000')/'models.json').read_text());result={}
        for m in data:
            props=m['properties'];identity=json.dumps([props.get('building_id') or props.get('db_id'),m['geometry'],m.get('sourceChannel')],sort_keys=True)
            result[identity]=(m,{k:sha(Path(v)) for k,v in m['local_files'].items()})
        return result
    ma=model_index(base,oldplan);mb=model_index(new,plan);model_changes=[]
    for k in ma.keys()|mb.keys():
        if k in ma and k in mb and ma[k][1]==mb[k][1] and ma[k][0]['properties']==mb[k][0]['properties']:continue
        for side,index in [('old',ma),('new',mb)]:
            if k not in index:continue
            m,_=index[k];props=m['properties'];ll=m['geometry']['coordinates'];xy=project.transform(ll[0],ll[1]);bid=str(props.get('building_id') or props.get('db_id'))
            if bid in buildings:
                v=np.concatenate([f['xy'] for _,f in buildings[bid]]);g=box(*[*v.min(0),*v.max(0)])
            else:g=Point(*xy).buffer(250)  # Conservative candidate, not measured GLB bounds.
            if not g.intersects(extent):continue
            detail=dict(side=side,buildingId=bid,sourceChannel=m.get('sourceChannel'),anchorMSK=list(xy),boundPolicy='source footprint or conservative 250 m anchor radius')
            model_changes.append(detail);mark(g,'changed-detailed-model',['detailed-building'],detail,pad=5)
    reasons=Counter()
    for t in tile_rows:
        for k in ('reasons','layers','evidence'):t[k]=sorted(t[k])
        t['localRebuildCandidate']=bool(t['reasons']);t['globalHeightReviewRequired']=True
        reasons.update(t['reasons'])
    summary=dict(oldTiles=400,expandedTiles=1296,newTiles=896,localCandidates=sum(t['localRebuildCandidate'] for t in tile_rows),
        noLocalChangeDetected=sum(not t['localRebuildCandidate'] for t in tile_rows),globalHeightReviewTiles=400,
        physicalChangedFragments=len(changes),changedDemSourceTiles=len(dem_changed),changedPhysicalStyleRules=len(style_changes),
        changedDetailedModelRecords=len(model_changes),boundaryStructuralSheets=len(profiles),railComponents=len(rail_dependencies),buildingGroups=len(building_dependencies),byReason=dict(reasons))
    report=dict(version=1,base=str(base),freshSource=str(new),release=str(release),oldBoundsMSK=bounds,newBoundsMSK=target,
        captureBoundsMSK=plan['acquisition_bounds_msk'],summary=summary,tiles=tile_rows,evidence=evidence,
        sourceComparison=dict(hashes=dict(hash_stats),changedLayers=dict(changed_by_layer),ignoredLayers=dict(ignored),unchangedFragmentsWithDifferentIndex=moved,
            changes=changes,demChanges=dem_changed,styleChanges=style_changes,detailedModelChanges=model_changes),
        dependencies=dict(structures=profiles,railways=rail_dependencies,buildings=building_dependencies),
        limitations=[
            'Candidate audit, not a rebuilt-mesh equality proof. Boundary ring and local margins are conservative.',
            'RoadHeightModel solves one regularized height system for the entire region; added observations can affect old heights. All 400 old tiles require review if that global fit is rerun.',
            'To reuse old meshes, freeze existing interior height controls and solve the extension with compatible boundary values, then verify heights and seams.',
            'The grid stays at 250 m in the same metric coordinates. Relative tile IDs shift +8 east and +8 north; this is a catalog remap, not a geometric displacement.',
            'Current source record IDs include source-tile array indices. Unchanged fragments must be matched by content/provider identity, not by their current array index.',
            'Rail station/UV origins and building terrain anchors require persistence across incremental rebuilds.',
            'The scene is not rebuilt or switched by this analysis; existing r6 assets remain untouched.'
        ],codeEvidence=['prototype/profiles.py:RoadHeightModel.__init__','prototype/tiling/railway_geometry.py:network','prototype/tiling/prepare_objects.py:anchors','prototype/tiling/pack_tiles.mjs:cacheContext'])
    out.mkdir(parents=True,exist_ok=True);(out/'impact.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    (out/'old-tiles-to-review.json').write_text(json.dumps(tile_rows,ensure_ascii=False,indent=2))
    print('IMPACT',json.dumps(summary,ensure_ascii=False),flush=True)
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('base',type=Path);p.add_argument('fresh',type=Path);p.add_argument('release',type=Path);p.add_argument('output',type=Path)
    a=p.parse_args();analyze(a.base.resolve(),a.fresh.resolve(),a.release.resolve(),a.output.resolve())
