"""Keep source observations, quarantine new canopy conflicts after grading."""
import argparse,collections,gzip,json
from pathlib import Path
import numpy as np
import shapely as sh
from build_scene import dump

def reconcile(root):
    scene=json.loads((root/'canonical/full/scene.json').read_text())
    masks=json.loads(gzip.decompress((root/'placement-masks.json.gz').read_bytes()))
    audit=json.loads(gzip.decompress((root/'plant-placement-audit.json.gz').read_bytes()))
    rows=audit['acceptedPoints'];xy=np.array([p['eastNorth']for p in rows]);mat=np.array([p['matrix']for p in rows]).reshape(-1,3,4)
    scale=np.linalg.norm(mat[:,:,:3],axis=1)[:,0];crowns=np.array([masks['crowns'][p['model']]for p in rows])*scale[:,None]
    buildings=sh.STRtree([sh.from_wkb(bytes.fromhex(p))for p,h in masks['buildings']]);tops=np.array([h for p,h in masks['buildings']])
    pi,bi=buildings.query(sh.buffer(sh.points(xy),crowns[:,0],quad_segs=8),predicate='intersects')
    bad=tops[bi]>mat[pi,1,3]+scene['origin'][2]+crowns[pi,1]+1e-6
    records=[]
    for i in np.unique(pi[bad]):
        matches=bi[bad&(pi==i)]
        records.append({**rows[i], 'conflicts':['buildingCanopyAfterGrading'],
          'crownBottomM':float(mat[i,1,3]+scene['origin'][2]+crowns[i,1]),'buildingTopM':float(tops[matches].max())})
    ids={p['id']for p in records};scene['instances']=[i for i in scene['instances']if i.get('id') not in ids]
    audit['acceptedPoints']=[p for p in rows if p['id']not in ids];audit['rejectedPoints'].extend(records)
    audit['accepted']-=len(ids);audit['rejected']+=len(ids)
    audit['byModel']=dict(collections.Counter(p['model']for p in audit['acceptedPoints']))
    audit['byConflict']=dict(collections.Counter(k for p in audit['rejectedPoints']for k in p['conflicts']))
    with gzip.open(root/'plant-placement-audit.json.gz','wt')as f:json.dump(audit,f,separators=(',',':'))
    appearance=json.loads((root/'vegetation-appearance.json').read_text())
    for p in appearance['records']:
        if p.get('id')in ids:p['status']='deferred-after-grading';p['conflicts']=['buildingCanopyAfterGrading']
    dump(root/'vegetation-appearance.json',appearance)
    scene['stats']['expandedTriangles']=sum(scene['chunks'][i['mesh']]['triangles']for i in scene['instances']);dump(root/'canonical/full/scene.json',scene)
    city=json.loads((root/'canonical/urban-model.json').read_text());city['objectLayer']['stats']['vegetationInstances']=audit['accepted'];dump(root/'canonical/urban-model.json',city)
    for name in ('canonical/validation.json','build-audit.json'):
        value=json.loads((root/name).read_text());value['stats']=scene['stats'];dump(root/name,value)
    report=dict(policy='Source observations preserved; conservative canopy envelope checked again after changing root elevation',records=records,deferred=len(records))
    dump(root/'graded-plant-conflicts.json',report);print('POST-GRADE CANOPY',len(records),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);reconcile(p.parse_args().root)
