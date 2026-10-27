"""Read-only contact preflight; full release validation is still required."""
import argparse,gzip,json
from pathlib import Path
import ijson
import numpy as np
from street_placement import SurfaceSampler,GROUND_NAMES
from prepare_foundations import foundation_contact
from adaptive_foundations import BURIAL


def check(root,out):
    print('Loading serialized ground',flush=True)
    ground=SurfaceSampler(root,json.loads((root/'canonical/full/scene.json').read_text()),GROUND_NAMES)
    checks=rounded=0;maximum=0.;failures=[]
    with gzip.open(root/'objects.json.gz','rb') as f:
        for i,row in enumerate(ijson.items(f,'objectLayer.foundations.buildings.item',use_float=True)):
            if i%500==0:print('CONTACT BUILDINGS',i,'checks',checks,'rounded',rounded,'failures',len(failures),flush=True)
            for j,panel in enumerate(row['panels']):
                bottom=np.array(panel['bottom'])
                for station in [.1,.5,.9]:
                    hit=foundation_contact(ground,panel,station)
                    q=bottom[0]+station*(bottom[1]-bottom[0])
                    if not hit or abs(q[1]+BURIAL-hit['height'])>=.0002:
                        failures.append(dict(object=row['id'],panel=j,station=station,hit=hit,bottom=q.tolist()))
                    if hit and 'boundaryRoundingM' in hit:
                        rounded+=1;maximum=max(maximum,hit['boundaryRoundingM'])
                    checks+=1
    result=dict(passed=not failures,checks=checks,rounded=rounded,maxRoundingM=maximum,failures=failures)
    out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(result,indent=2))
    print(json.dumps(result),flush=True)
    return not failures


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);p.add_argument('out',type=Path)
    a=p.parse_args();raise SystemExit(0 if check(a.root,a.out) else 1)
