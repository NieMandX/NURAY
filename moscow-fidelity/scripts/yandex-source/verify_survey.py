"""Independent survey/terrain seam, rigid model, footing and plant invariants."""
import sys,json,gzip,argparse,numpy as np,shapely as sh
from pathlib import Path
from build_scene import Terrain
from survey_terrain import safe_sample
from apply_crossfall import unpack
parser=argparse.ArgumentParser();parser.add_argument('root',type=Path);parser.add_argument('--parent',type=Path,required=True);args=parser.parse_args();base=args.parent;root=args.root;field=np.load(root/'canonical/survey-field.npz');old=Terrain(np.load(base/'canonical/terrain.npz')['triangles']);new=Terrain(np.load(root/'canonical/terrain.npz')['triangles']);scene=json.loads((root/'canonical/full/scene.json').read_text());parent=json.loads((base/'canonical/full/scene.json').read_text());r=json.loads((root/'survey-terrain.json').read_text());marks=field['marks'];rect=sh.box(*field['bounds'])
error=abs(safe_sample(new,marks[:,:2])-marks[:,2]);assert error.max()<.002
# A quarantined measurement remains inspectable and must not be silently
# overwritten with an interpolated replacement in the source array.
outliers=[]
if 'sourceMarks' in field:
 source=field['sourceMarks'];used=field['sourceMarkUsed'].astype(bool)
 assert np.array_equal(source[used],marks)
 assert len(source)-int(used.sum())==r.get('quarantinedGroundMarks',0)
 flagged={v['index']:v for v in r.get('suspectGroundMarks',[])}
 for i in np.flatnonzero(~used):
  assert int(i) in flagged
  evidence=flagged[int(i)];assert np.array_equal(source[i],evidence['point'])
  replacement=float(safe_sample(new,source[i:i+1,:2])[0])
  outliers.append({**evidence,'originalHeightM':float(source[i,2]),'interpolatedTerrainHeightM':replacement,
   'policy':'Excluded from terrain only; source measurement retained unchanged; interpolation is not a corrected survey measurement'})
 (root/'survey-outliers.json').write_text(json.dumps(dict(source=r['source'],sourceMarks=len(source),retainedMarks=int(used.sum()),quarantined=outliers),ensure_ascii=False,indent=2)+'\n')
boundary=sh.get_coordinates(sh.segmentize(rect.boundary,.5));seam=abs(safe_sample(new,boundary)-safe_sample(old,boundary));assert seam.max()<.002
rng=np.random.default_rng(7301);q=rng.uniform(-2900,2900,(20000,2));q=q[~sh.covers(rect,sh.points(q))];outside=abs(safe_sample(new,q)-safe_sample(old,q));assert outside.max()<1e-7
coverage=sh.union_all(new.polygons[new.tree.query(rect,predicate='intersects')]);gap=rect.difference(coverage).area;assert gap<.001
pc=next(c for c in parent['chunks'] if c['name']=='water');c=next(c for c in scene['chunks'] if c['name']=='water');assert (base/'canonical/full'/pc['file']).read_bytes()==(root/'canonical/full'/c['file']).read_bytes()
source_tinted={}
for c in parent['chunks']:
 raw=gzip.decompress((base/'canonical/full'/c['file']).read_bytes());tint=np.frombuffer(raw[:c['vertexBytes']],'<f4').reshape(-1,8)[:,7]
 source_tinted[c['name']]=source_tinted.get(c['name'],False) or bool(np.any(tint))
for c in scene['chunks']:
 if source_tinted.get(c['name'],True):continue
 raw=gzip.decompress((root/'canonical/full'/c['file']).read_bytes());tint=np.frombuffer(raw[:c['vertexBytes']],'<f4').reshape(-1,8)[:,7]
 assert not np.any(tint),('Neutral source tint changed',c['name'])
labels=np.load(root/'canonical/source-model-ownership.npz')['labels'];deltas=[];cursor=0
for pc in parent['chunks']:
 if pc['name']!='landmarks':continue
 c=next(c for c in scene['chunks'] if c['file']=='survey-parent-'+Path(pc['file']).name)
 a,am,ac=unpack(base/'canonical/full',pc);b,bm,bc=unpack(root/'canonical/full',c);assert np.array_equal(am,bm);assert np.array_equal(ac,bc);assert np.array_equal(a[:,:,[0,2]],b[:,:,[0,2]]);assert np.array_equal(a[:,:,3:],b[:,:,3:]);deltas.extend((b[:,:,1]-a[:,:,1]).tolist())
deltas=np.array(deltas);rigidity={mid:float(np.ptp(deltas[labels==mid])) for mid in np.unique(labels)};assert max(rigidity.values())<.0001,rigidity
plants=json.loads(gzip.decompress((root/'plant-placement-audit.json.gz').read_bytes()));sourceplants=json.loads(gzip.decompress((base/'plant-placement-audit.json.gz').read_bytes()));prior={p['id']:p['matrix'] for p in sourceplants['acceptedPoints']};keep=[0,1,2,3,4,5,6,8,9,10,11]
for p in plants['acceptedPoints']:assert np.array_equal(np.array(p['matrix'])[keep],np.array(prior[p['id']])[keep])
# Facade ground vertices must touch the new terrain; flat roofs remain flat.
foot_errors=[];foot_vertices=[]
for c in scene['chunks']:
 if c['name']!='buildings':continue
 t,m,color=unpack(root/'canonical/full',c);hit=m==20
 if not hit.any():continue
 t=t[hit];xy=t[:,:,[0,2]]*[1,-1];hit=sh.covers(rect,sh.points(xy.mean(1)));t=t[hit];xy=xy[hit]
 if not len(t):continue
 h=safe_sample(new,xy.reshape(-1,2)).reshape(-1,3)-scene['origin'][2];delta=t[:,:,1]-h
 foot_errors.extend(abs(delta.min(1)).tolist())
 foot_vertices.append(np.column_stack([xy.reshape(-1,2),t[:,:,1].ravel()]))
# Wall upper half-triangles have no ground vertex; only bottom-bearing faces are checked.
feet=np.array(foot_errors);small=feet[feet<.1];assert small.max(initial=0)<.002,small.max()
v=np.concatenate(foot_vertices);corners,inverse=np.unique(np.round(v[:,:2],4),axis=0,return_inverse=True)
bottom=np.full(len(corners),np.inf);np.minimum.at(bottom,inverse,v[:,2])
bottom_error=abs(bottom+scene['origin'][2]-safe_sample(new,corners))
assert bottom_error.max(initial=0)<.003,('Facade footing gap',float(bottom_error.max()))
report=dict(passed=True,groundMarkMaxErrorM=float(error.max()),patchSeamMaxErrorM=float(seam.max()),unchangedTerrainOutsidePatchMaxErrorM=float(outside.max()),outsideSamples=len(q),patchCoverageGapM2=gap,waterGeometryByteIdentical=True,neutralSurfaceTintsPreserved=True,authorModelTintsPreserved=True,authorModelRigidShiftMaxSpreadM=max(rigidity.values()),plantXYScaleYawPreserved=True,retainedPlantInstances=len(plants['acceptedPoints']),checkedFootingTriangles=len(small),footingMaxErrorM=float(small.max(initial=0)),acceptedVerticalDatum='BS-77 user assumption')
report.update(retainedSurveyMarks=len(marks),quarantinedSurveyMarks=len(outliers),quarantinedSourcePreserved=True,checkedFacadeFootingCorners=len(corners),facadeFootingCornerMaxErrorM=float(bottom_error.max(initial=0)))
(root/'survey-validation.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
