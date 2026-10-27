"""Validate the actual serialized revision, not only the generator's report."""
import gzip,hashlib,json
from pathlib import Path
import numpy as np
import shapely as sh

WALLS={'tunnel_wall_top','tunnel_wall_bottom','tunnel_wall_side','inferred-walls'}

def verify_revision(root,city,manifest):
    if city['geometryRevision']['type']=='facade-bands':
        from prepare_facade_bands import verify_revision as verify_facades
        return verify_facades(root,city,manifest)
    if city['geometryRevision']['type']=='parking-material':
        from prepare_parking_material import verify_revision as verify_parking
        return verify_parking(root,city,manifest)
    if city['geometryRevision']['type']=='connected-waterfront':
        from prepare_waterfront import verify_revision as verify_waterfront
        return verify_waterfront(root,city,manifest)
    if city['geometryRevision']['type']=='pitched-roof-materials':
        from prepare_pitched_roofs import verify_revision as verify_pitched_roofs
        return verify_pitched_roofs(root,city,manifest)
    if city['geometryRevision']['type']=='flat-roofs':
        from prepare_flat_roofs import verify_revision as verify_flat_roofs
        return verify_flat_roofs(root,city,manifest)
    if city['geometryRevision']['type']=='pedestrian-materials':
        from prepare_pedestrian_materials import verify_revision as verify_pedestrian_materials
        return verify_pedestrian_materials(root,city,manifest)
    if city['geometryRevision']['type']=='cemetery-cover':
        from prepare_cemetery_cover import verify_revision as verify_cemetery_cover
        return verify_cemetery_cover(root,city,manifest)
    if city['geometryRevision']['type']=='railway-levels':
        from prepare_railway_levels import verify_revision as verify_railway_levels
        return verify_railway_levels(root,city,manifest)
    if city['geometryRevision'].get('type')=='transport-surfaces':
        from transport_surface_validation import verify_revision as verify_transport_surfaces
        return verify_transport_surfaces(root,city,manifest)
    if city['geometryRevision'].get('type')=='road-paint':
        from prepare_road_paint import verify_revision as verify_road_paint
        return verify_road_paint(root,city,manifest)
    if city['geometryRevision'].get('type')=='passage-clearance':
        from prepare_passage_clearance import verify_revision as verify_clearance
        return verify_clearance(root,city,manifest)
    if city['geometryRevision'].get('type')=='railway-entries':
        from prepare_railway_entries import verify_revision as verify_railway_entries
        return verify_railway_entries(root,city,manifest)
    if city['geometryRevision'].get('type')=='fence-types':
        from prepare_fence_types import verify_revision as verify_fences
        return verify_fences(root,city,manifest)
    if city['geometryRevision'].get('type')=='street-template-directions':
        from prepare_street_directions import verify_revision as verify_directions
        return verify_directions(root,city,manifest)
    if city['geometryRevision'].get('type')=='building-foundations':
        from prepare_foundations import verify_revision as verify_foundations
        return verify_foundations(root,city,manifest)
    if city['geometryRevision'].get('type')=='vegetation-size':
        from prepare_vegetation_scale import verify_revision as verify_size
        return verify_size(root,city,manifest)
    if city['geometryRevision'].get('type')=='green-insets':
        from green_insets_validation import verify_revision as verify_green
        return verify_green(root,city,manifest)
    if city['geometryRevision'].get('type')=='street-objects':
        from street_validation import verify_revision as verify_street
        return verify_street(root,city,manifest)
    if city['geometryRevision'].get('type')=='physical-source':
        from physical_geometry import verify_revision as verify_physical
        return verify_physical(root,city,manifest)
    if city['geometryRevision'].get('type')=='custom-vegetation':
        from custom_vegetation_validation import verify_revision as verify_custom
        return verify_custom(root,city,manifest)
    if city['geometryRevision'].get('type')=='vegetation-variation':
        from vegetation_validation import verify_revision as verify_vegetation
        return verify_vegetation(root,city,manifest)
    if city['geometryRevision'].get('type')=='landscape':
        from landscape_validation import verify_revision as verify_landscape
        return verify_landscape(root,city,manifest)
    revision=city['geometryRevision'];parent=root.parent/revision['parent']
    old=json.loads((parent/'canonical/full/scene.json').read_text());old_chunks={c['id']:c for c in old['chunks']}
    new_chunks={c['id']:c for c in manifest['chunks']}
    def raw(folder,c):return gzip.decompress((folder/'canonical/full'/Path(c['file']).name).read_bytes())
    def digest(data):return hashlib.sha256(data).hexdigest()
    walls={r['id'] for r in revision['wallRebuilds']};remaps={r['id']:r for r in revision['materialRemaps']}
    assert walls=={c['id'] for c in old['chunks'] if c['name'] in WALLS}
    assert set(old_chunks)==walls|set(remaps)|{r['id'] for r in revision['preservedChunks']}
    for idx,c in old_chunks.items():
        before=raw(parent,c);after=raw(root,new_chunks[idx]);name=c['name']
        if idx in walls:
            assert new_chunks[idx]['name']==name
            words=np.frombuffer(after[:new_chunks[idx]['vertexBytes']],'<u4').reshape(-1,8)
            assert np.all((words[:,6]&0x7fffffff)==6)
        elif idx in remaps:
            assert name in {'roadbed_tunnel','roadbed_tunnel_descent'}
            words=np.frombuffer(before[:c['vertexBytes']],'<u4').reshape(-1,8).copy()
            words[(words[:,6]&0x7fffffff)==11,6]=np.uint32(0x80000000|7)
            assert words.tobytes()+before[c['vertexBytes']:]==after, 'Material change moved geometry'
        else:assert before==after, ('Unrelated geometry changed',idx,name)
    assert old['instances']==manifest['instances'][:len(old['instances'])]
    assert old['materials']==manifest['materials'] and old['textures']==manifest['textures']
    for name in old['textures']:assert (parent/'textures'/name).read_bytes()==(root/'textures'/name).read_bytes()
    headers=verify_headers(root,city,manifest)
    return dict(passed=True,preservedChunks=len(revision['preservedChunks']),rebuiltWallChunks=len(walls),
        materialOnlyChunks=len(remaps),**headers,
        geometryIdentityOutsideRevision=True,instancesAndTexturesUnchanged=True)

def verify_headers(root,city,manifest):
    revision=city['geometryRevision']
    terrain_path=root/'canonical/terrain.npz';assert hashlib.sha256(terrain_path.read_bytes()).hexdigest()==revision['terrainSha256']
    terrain=np.load(terrain_path);polys=sh.from_wkb(terrain['polygons']);tree=sh.STRtree(polys);planes=terrain['planes']
    top=[];bottom=[];origin=np.asarray(city['originMSK'])
    for c in manifest['chunks']:
        if not c['name'].startswith('portal_guard'):continue
        data=gzip.decompress((root/'canonical/full'/Path(c['file']).name).read_bytes());v=np.frombuffer(data[:c['vertexBytes']],'<f4').reshape(-1,8)
        u=np.frombuffer(data[:c['vertexBytes']],'<u4').reshape(-1,8);ix=np.frombuffer(data[c['vertexBytes']:],'<u4').reshape(-1,3)
        assert np.all((u[:,6]&0x7fffffff)==6)
        world=v[:,:3][:,[0,2,1]]*[1,-1,1]+origin
        if c['name']=='portal_guard_top':top.extend(world[ix])
        if c['name']=='portal_guard_bottom':bottom.extend(world[ix])
    assert top and bottom
    top_xy=sh.union_all([sh.Polygon(t[:,:2]) for t in top]);max_drop=0.
    for p in np.asarray(bottom).reshape(-1,3):
        xy=sh.Point(p[:2]);ids=tree.query(xy,predicate='covered_by');di=int(ids[0]) if len(ids) else int(tree.nearest(xy))
        land=float(planes[di]@np.r_[p[:2],1])+.1;drop=land-p[2]
        assert -.002<=drop<=.502, ('Header blocks the opening',drop)
        max_drop=max(max_drop,drop)
    portals=0;sources=set()
    for group in city['tunnelWalls']['groups']:
        headers=group['portalHeaders'];assert headers['passed']
        for line in headers['openings']:
            geometry=sh.geometry.shape(line)
            assert geometry.difference(top_xy.buffer(.001)).length<.001, 'Missing serialized portal roof'
            portals+=1
        sources.update(headers['sourceIds'])
    assert portals>0
    return dict(portalOpenings=portals,sourceArches=len(sources),maxSerializedHeaderDropM=max_drop)
