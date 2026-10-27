import bpy,sys,json,math
import numpy as np
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent))
from repair_blender import triangles
points=[(x,y) for x in range(250,1151,30) for y in range(6950,8101,30)]
rows=[{'xy':p,'hits':{}} for p in points]
for name in ['Terrain_2GIS_TIN','Administrative_quarter','Forest_quarter','Internal_forest_quarter','Internal_lawn','Immersive_park_polygon_green']:
    o=bpy.data.objects.get(name)
    if not o:continue
    ts,_=triangles(o);lo=ts[:,:,:2].min(axis=1);hi=ts[:,:,:2].max(axis=1)
    keep=(lo[:,0]<=1151)&(hi[:,0]>=250)&(lo[:,1]<=8101)&(hi[:,1]>=6950)
    ts=ts[keep];lo=lo[keep];hi=hi[keep]
    for row in rows:
        p=row['xy'];ss=ts[np.all(lo<=p,axis=1)&np.all(hi>=p,axis=1)].astype(float)
        for tri in ss:
            mat=np.column_stack((tri[:,:2],np.ones(3)))
            if abs(np.linalg.det(mat))<1e-10:continue
            weights=np.linalg.solve(mat.T,[*p,1])
            if min(weights)>-1e-6:row['hits'][name]=float(weights@tri[:,2])
    print('SAMPLED',name,flush=True)
summary={}
for name in ['Terrain_2GIS_TIN','Administrative_quarter']:
    bad=[]
    for r in rows:
        grass=[h for n,h in r['hits'].items() if n not in ['Terrain_2GIS_TIN','Administrative_quarter']]
        if grass and name in r['hits'] and r['hits'][name]>max(grass)+.002:bad.append(r)
    summary[name]={'occluded_grass_samples':len(bad),'examples':bad[:5]}
Path('/Users/niemandx/Documents/ChatGPT/IDEAS/moscow-fidelity/output/ground-overlap.json').write_text(json.dumps(summary,indent=2))
print('GROUND CHECK',json.dumps(summary),flush=True)
