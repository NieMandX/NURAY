"""Extract a bounded railway witness without loading the whole city twice."""
import gzip,json,pickle,sys,time
from pathlib import Path
import ijson
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'prototype/tiling'))
from canonical_store import open_canonical
from railway_layer import select_input

base=Path(sys.argv[1]);out=Path(sys.argv[2]);out.mkdir(parents=True,exist_ok=True)
path=base/'canonical/urban-model.json'
point=(-1869.05561888,4342.67612955);radius=70
def nearby(coords):
    if not coords:return False
    xs=[p[0] for p in coords];ys=[p[1] for p in coords]
    return max(xs)>=point[0]-radius and min(xs)<=point[0]+radius and max(ys)>=point[1]-radius and min(ys)<=point[1]+radius
features=[];witness=[]
with open_canonical(path,'rb') as stream:
    for f in ijson.items(stream,'features.item',use_float=True):
        if f['layer'] in ('Railroad_line','Railroad_tunnel_line'):features.append(f)
        if f.get('coordinates') and isinstance(f['coordinates'][0],list) and nearby(f['coordinates']):witness.append(f)
print('RAIL SOURCE FEATURES',len(features),'local',len(witness),flush=True)
local=[]
def surfaces():
    with open_canonical(path,'rb') as stream:
        for i,s in enumerate(ijson.items(stream,'surfaces.item',use_float=True)):
            rings=s['geometry']['coordinates']
            ring=rings[0] if s['geometry']['type']=='Polygon' else [q for poly in rings for q in poly[0]]
            if nearby(ring):local.append(s)
            if i%500000==0:print('RAIL FLOOR INPUT',i,flush=True)
            yield s
metadata=dict(boundsMSK=[-5000,-5000,5000,5000],originMSK=[0,0,0])
data=select_input(metadata,features,surfaces())
with gzip.open(out/'rail-input.pkl.gz','wb',compresslevel=1) as stream:pickle.dump(data,stream,pickle.HIGHEST_PROTOCOL)
(out/'missing-ground-witness.json').write_text(json.dumps(dict(point=point,features=witness,surfaces=local),ensure_ascii=False))
print('RAIL INPUT SAVED',len(data['surfaces']),len(local),flush=True)
