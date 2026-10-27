"""Round by narrowing: six circular sections, intact foliage/branches and roots."""
import json
import numpy as np
import build

row=next(m for m in json.loads((build.OUT/'catalog.json').read_text())['models'] if m['id']=='open')
old,old_m,old_parts=build.make('open',row['sourceBounds'],round_trunk=False)
new,new_m,parts=build.make('open',row['sourceBounds'])
build.validate(new,parts)
part=next(p for p in parts if p.get('role')=='trunk')
assert np.array_equal(new[part['end']:],old[part['end']:]),'Foliage and branches must be byte-identical'
assert np.array_equal(old_m,new_m)
assert np.array_equal(new,build.make('open',row['sourceBounds'])[0]),'Deterministic generation'
faces=np.asarray(part['faces'])
vertices=np.empty((len(part['centerline'])*part['sides'],3))
vertices[faces]=new[part['start']:part['end'],:,:3]
rings=vertices.reshape(-1,part['sides'],3)
assert abs(new[:part['end'],:,1].min()-old[:part['end'],:,1].min())<1e-12,'Root stays on the ground'
previous=np.inf
for ring,section in zip(rings,part['roundSections']):
    offsets=ring-section['center'];radii=np.linalg.norm(offsets,axis=1)
    assert np.ptp(radii)<1e-12,'All section vertices lie on a circle'
    singular=np.linalg.svd(offsets,compute_uv=False)
    assert abs(singular[0]/singular[1]-1)<1e-12 and singular[2]<1e-12,'Planar, round section'
    radius=section['radius']
    assert radius<=min(section['beforeRadii'])+1e-12,'Never enlarge the narrow axis'
    assert radius<=previous and radius>0,'Tapers upwards'
    previous=radius
print('PASS: six circular, tapered sections; minor axis never enlarged; root anchored; foliage and branches unchanged; closed, deterministic mesh.')

approved=build.OUT/'open-approved-01'
if (approved/'geometry.npz').exists():
    selected=np.load(approved/'geometry.npz')
    before=np.load(build.OUT/'open-selected-before-trunk/geometry.npz')
    assert np.array_equal(selected['attributes'][part['end']:],before['attributes'][part['end']:])
    assert np.array_equal(selected['materials'],before['materials'])
    assert np.array_equal(selected['attributes'][:part['end'],:,:3],new[:part['end'],:,:3].astype(np.float32))
    assert len(selected['attributes'])==684
    print('PASS: saved selection keeps exact live foliage and branches, 684 triangles; only the central trunk changed.')
