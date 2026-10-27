"""Identity, reproducibility, placement and non-compounding regression checks."""
import copy,json,os,subprocess,sys
from pathlib import Path
import numpy as np
from vegetation_variation import apply,parameters,transform,key_for,unit

row=dict(id='import:1',layer='Model_tree_deciduous_point',position=[12.345,67.890,150.])
p=parameters(row)
assert p['yawDegrees']==-139.13001652961992 and p['scale']==0.9620022353985949,'Version 1 reproducibility vector changed'
assert p==parameters({**row,'id':'import:999','tileId':'999-0','sourcePointIndex':999,
    'position':[12.345,67.890,200.],'templates':['our-new-tree']})
assert p!=parameters({**row,'position':[12.346,67.890,150.]})
assert key_for({**row,'sourceObjectId':'official-1'})==key_for({**row,'sourceObjectId':'official-1','position':[1,2,3]})
points=[{**row,'position':[i*.031,0,0]} for i in range(1000)]
forward={key_for(r):parameters(r) for r in points}
assert forward=={key_for(r):parameters(r) for r in reversed(points)}
assert forward=={key_for(r):parameters(r) for batch in [points[::2],points[1::2]] for r in batch}
assert all(.92<=v['scale']<1.08 and -180<=v['yawDegrees']<180 for v in forward.values())
assert len({round(v['scale'],8) for v in forward.values()})>990
assert min(v['scale'] for v in forward.values())<.925 and max(v['scale'] for v in forward.values())>1.075
# Independent streams: adding a future model-choice lookup cannot consume yaw.
unit(p['key'],'future-model-choice');assert parameters(row)==p
# Compare fresh interpreter processes, not only calls in the same process.
code='from vegetation_variation import parameters; import json; print(json.dumps(parameters('+repr(row)+'),sort_keys=True))'
a=subprocess.check_output([sys.executable,'-c',code],cwd=Path(__file__).resolve().parent,env={**os.environ,'PYTHONHASHSEED':'1'})
b=subprocess.check_output([sys.executable,'-c',code],cwd=Path(__file__).resolve().parent,env={**os.environ,'PYTHONHASHSEED':'987'})
assert a==b
matrix=[2,0,0,17,0,3,0,4,0,0,2,-52]
changed,base=transform(matrix,p)
assert changed[3::4]==matrix[3::4]
linear=np.asarray(changed).reshape(3,4)[:,:3];original=np.asarray(matrix).reshape(3,4)[:,:3]
assert np.allclose(linear.T@linear,original.T@original*p['scale']**2)
i=dict(id='plant:mesh',objectId='plant',mesh=1,matrix=matrix,tileId='0-0')
plant={**row,'renderInstances':[copy.deepcopy(i)]}
layer=dict(vegetation=[plant],policy={});manifest=dict(instances=[copy.deepcopy(i)])
apply(layer,manifest);first=copy.deepcopy((layer,manifest));apply(layer,manifest)
assert (layer,manifest)==first,'Repeated build compounded scale/rotation'
# A subsequent terrain edit changes only placement, not the variation.
for obj in (layer['vegetation'][0]['renderInstances'][0],manifest['instances'][0]):obj['matrix'][7]+=.1
apply(layer,manifest);assert abs(manifest['instances'][0]['matrix'][7]-4.1)<1e-12
assert manifest['instances'][0]['variationBaseLinear']==base
print('Passed: reorder/batching/reload stability, independent streams/processes, range, unchanged root, uniform scale, idempotence, terrain shift.')
