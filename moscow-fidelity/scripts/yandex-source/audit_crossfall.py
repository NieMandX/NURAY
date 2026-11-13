"""Measure serialized ground asphalt across its source traffic direction."""
import argparse,gzip,json,pickle
from pathlib import Path
import numpy as np
import shapely as sh
from road_crossfall import source_segments,road_topology

def audit(root,segments,output=None,*,check_continuity=False):
    scene=json.loads((root/'canonical/full/scene.json').read_text());tr=[]
    for c in scene['chunks']:
        if c['name']!='land':continue
        raw=gzip.decompress((root/'canonical/full'/c['file']).read_bytes())
        u=np.frombuffer(raw[:c['vertexBytes']],'<u4').reshape(-1,8);ix=np.frombuffer(raw[c['vertexBytes']:],'<u4').reshape(-1,3)
        ix=ix[(u[ix[:,0],6]&0x7fffffff)==0];tr.append(u.view('<f4')[ix,:3].astype(float))
    t=np.concatenate(tr);xy=t[:,:,[0,2]]*[1,-1];z=t[:,:,1]
    areas=np.abs(np.linalg.det(xy[:,1:]-xy[:,:1]))/2;keep=areas>.001
    omitted=float(areas[~keep].sum());xy,z,areas=xy[keep],z[keep],areas[keep]
    tree=sh.STRtree(sh.linestrings(segments));index=tree.nearest(sh.points(xy.mean(1)))
    d=segments[index,1]-segments[index,0];d/=np.linalg.norm(d,axis=1)[:,None];normal=np.column_stack([-d[:,1],d[:,0]])
    grad=np.linalg.solve(xy[:,1:]-xy[:,:1],(z[:,1:]-z[:,:1])[:,:,None])[:,:,0]
    angle=np.degrees(np.arctan(abs((grad*normal).sum(1))))
    report=dict(triangles=len(xy),areaM2=float(areas.sum()),maxDegrees=float(angle.max()),percentiles=np.percentile(angle,[50,90,95,99]).tolist(),areaOver5M2=float(areas[angle>5].sum()),
                omittedSliverAreaM2=omitted,minimumTriangleAreaM2=.001,scope='Generated ground asphalt; source elevated structures unchanged')
    if check_continuity:
        _,height,_,seam_ids,seam_coeff=road_topology(xy,z)
        report['edgeContinuityConstraints']=len(seam_ids)
        report['edgeContinuityMaxErrorM']=float(np.max(abs((height[seam_ids]*seam_coeff).sum(1)),initial=0))
        assert report['edgeContinuityMaxErrorM']<.002,report
    if output:np.savez_compressed(output,xy=xy,z=z,normal=normal,areas=areas,segments=segments)
    return report

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);p.add_argument('source',type=Path);p.add_argument('--output',type=Path);p.add_argument('--require-limit',action='store_true');a=p.parse_args()
    with (a.source/'projected-scene-v1.pickle').open('rb') as f:rows,*_=pickle.load(f)
    result=audit(a.root,source_segments(rows),a.output,check_continuity=a.require_limit);print(json.dumps(result,indent=2))
    if a.require_limit:assert result['maxDegrees']<=5,result
