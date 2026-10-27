"""Check remaining full-width transport corridors before expensive tile packing."""
import sys,json
from pathlib import Path
from streaming_json import Document
from prepare_railway_entries import load_terrain,passages,meshes,near_passages
from interface_validation import check_interfaces
from railway_tunnel_validation import audit as tunnel_audit
from transport_clearance_validation import audit as corridor_audit
from overpasses import OVERHANG
from railway_transitions import TRACK_OFFSET

root=Path(sys.argv[1]);doc=Document(root/'canonical/urban-model.json')
city={k:doc.read(k) for k in ['features','boundsMSK','groundRoadGeometry','roadInterfaces','originMSK']}
city['surfaces']=[s for s in doc.items('surfaces') if s['kind'].startswith('roadbed')]
scene=json.loads((root/'canonical/full/scene.json').read_text());dem,tree=load_terrain(root)
print('TRANSPORT PREFLIGHT INPUT',len(city['surfaces']),flush=True)
interfaces=[r for r in city['roadInterfaces'] if any(e['kind']=='railway_ground' for e in r['ends'])]
volumes=passages(city,interfaces,dem,tree)
rail=check_interfaces(volumes,near_passages(meshes(root,scene),volumes))
rail.update(halfWidthM=OVERHANG+.05,heightRangeAboveFloorM=[TRACK_OFFSET+.02,TRACK_OFFSET+.75],
            scope='source-shaped railway ramps and full-width outward ground approaches; serialized canonical meshes')
rail.pop('heightRangeAboveRoadM',None)
(root/'transport-preflight-rail.json').write_text(json.dumps(rail,indent=2))
assert rail['passed'],[r for r in rail['checks'] if not r['passed']]
print('TRANSPORT PREFLIGHT RAIL',len(interfaces),'PASSED',flush=True)
tunnels=tunnel_audit(city,dem,tree,meshes(root,scene))
(root/'transport-preflight-tunnels.json').write_text(json.dumps(tunnels,indent=2))
assert tunnels['passed'],tunnels
print('TRANSPORT PREFLIGHT TUNNELS PASSED',flush=True)
corridors=corridor_audit(city,dem,tree,meshes(root,scene))
(root/'transport-preflight-corridors.json').write_text(json.dumps(corridors,indent=2))
assert corridors['passed'] and corridors['fullWidth']['passed'],corridors['partialContacts']
print('TRANSPORT PREFLIGHT ALL CORRIDORS PASSED',flush=True)
