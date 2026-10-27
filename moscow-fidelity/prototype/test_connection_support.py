import numpy as np
import shapely as sh
from connection_support import is_landing,landing_offset,obstruction_area,physical_gate

floor=dict(kind='roadbed_tunnel_descent',owner='ramp',tiers=[-1],transport='pedestrian',poly=sh.box(-2,-2,0,2),plane=np.array([0.,0.,.1]))
land=dict(kind='land',owner='ground',tiers=[0],poly=sh.box(0,-2,2,2),plane=np.array([0.,0.,.1]))
gate=sh.box(-.001,-1,.001,1)
c=dict(peerKind='pedestrian_ground',peerLevel=[0],sourceParents=['ramp'])
assert is_landing(land,c)
flat_stair={**floor,'owner':'landing','tiers':[0]}
assert is_landing(flat_stair,c)
assert not is_landing({**flat_stair,'transport':'vehicle'},c)
# A different display tier is a candidate; the mouth audit subsequently
# requires actual floor-height agreement at three or more source samples.
assert is_landing({**flat_stair,'tiers':[-1]},c)
assert not is_landing({**land,'tiers':[-1]},c)
asphalt={**land,'kind':'roadbed_flat','transport':'vehicle','plane':np.zeros(3)}
assert is_landing(asphalt,c)
# Exercise the caller's height equation, not just the helper's return value:
# a pedestrian mouth at sidewalk height must meet its asphalt reference.
assert abs(floor['plane'][2]+landing_offset(asphalt,c,.1)-asphalt['plane'][2])<1e-12
assert abs(floor['plane'][2]+.02+landing_offset(asphalt,c,.1)-asphalt['plane'][2])>.003
assert not is_landing(floor,c)
assert obstruction_area(gate,[land],[floor])<1e-12
assert obstruction_area(gate,[{**land,'plane':np.array([0.,0.,.2])}],[floor])>.0019
assert obstruction_area(gate,[land],[{**floor,'plane':np.zeros(3)}])>.0019
rail=dict(peerKind='railway_ground',peerLevel=[0],sourceParents=['rail'])
assert is_landing({**land,'kind':'roadbed_flat'},rail)
assert landing_offset(land,rail,.1)==.1
assert landing_offset({**land,'kind':'roadbed_flat'},rail,.1)==0
assert abs(0+landing_offset(land,rail,.1)-land['plane'][2])<1e-12
print('Passed: coplanar land/staircase candidates across display tiers, raised obstructions, explicit walking/railway road datums and purpose rejection.')

# A mouth can turn along its lateral boundary. The probe strip outside both
# connected floors is not carriageway, while an equally thin intrusion inside
# the floor must remain an obstruction. This is independent of world position.
ramp={**floor,'poly':sh.box(-1,0,0,2),'plane':np.zeros(3)}
peer={**floor,'poly':sh.box(0,0,1,1),'plane':np.zeros(3)}
mouth=sh.LineString([(0,0),(0,1),(0,1.3)])
raw=mouth.buffer(.001,cap_style='flat')
physical=physical_gate(raw,[ramp],[peer])
outside={**land,'poly':sh.box(0,1,1,1.3),'plane':np.array([0.,0.,.1])}
inside={**outside,'poly':sh.box(-.001,1,0,1.3)}
assert obstruction_area(raw,[outside],[ramp])>.0001
assert obstruction_area(physical,[outside],[ramp])<1e-12
assert obstruction_area(physical,[inside],[ramp])>.0001
connector=sh.geometry.mapping(sh.box(0,1,.001,1.3))
assert obstruction_area(physical_gate(raw,[ramp],[peer],connector),[outside],[ramp])>.0001
assert physical_gate(raw,[],[]).equals(raw)
print('Passed: bent-mouth probes exclude only area outside confirmed floors; equally small real intrusions and explicit gap connectors are still audited.')
