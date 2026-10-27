"""Build an auxiliary, world-space lookup for shore foam and asphalt wear.
The canonical city and GLB remain byte-identical. No per-tile boundaries are used.
"""
import argparse,gzip,json,hashlib,math
from collections import defaultdict
from pathlib import Path
import numpy as np
import shapely as sh
import ijson
from flat_roofs import read_faces
from waterfront import bank_segments

MARKINGS={'LinearMarking_Broken','LinearMarking_Solid','LinearMarking_Double','LinearMarking_Reversal','LinearMarking_ShortIntermittentWhite'}
ROADS={'Main_road','Other_road','Internal_road','Segmental_road','Oneway_main_road','Oneway_other_road','Oneway_internal_road','Oneway_segmental_road'}
CELL=8.;MARGIN=3.5

def items(root,key):
 with gzip.open(root/'canonical/urban-model.json.gz','rb') as f:yield from ijson.items(f,key+'.item',use_float=True)

def shoreline(root,scene):
 folder=root/'canonical/full';path=folder/'water-bank-domain.wkb'
 domain=sh.from_wkb(path.read_bytes()) if path.exists() else sh.GeometryCollection()
 sh.prepare(domain)
 parts=[]
 for c in scene['chunks']:
  if c['name'] not in {'water','water-bridge-continuation'}:continue
  faces=read_faces(folder,c).view('<f4')[:,:,:3].astype(float);xy=faces[:,:,[0,2]]*[1,-1]+np.asarray(scene['origin'][:2])*[1,1]
  # Existing connected-water boundary already restores water below bridges.
  # Only add the isolated lakes/pools missing from that boundary.
  selected=~sh.covers(domain,sh.points(xy.mean(1)))
  if selected.any():parts.append(sh.union_all(sh.polygons(xy[selected]),grid_size=.001))
 domain=sh.union_all([domain,*parts],grid_size=.001)
 bounds=scene.get('boundsMSK') or json.loads((root/'tileset.json').read_text())['boundsMSK']
 a,b,_,_,_=bank_segments(domain,bounds)
 ox,oy,_=scene['origin'];a=(a-[ox,oy])*[1,-1];b=(b-[ox,oy])*[1,-1]
 return np.column_stack([a,b,np.zeros((len(a),4))])

def road_lines(root,origin):
 records=[];tiers=[]
 for r in items(root,'features'):
  layer=r['layer']
  if layer not in MARKINGS|ROADS:continue
  p=np.asarray(r['coordinates'],dtype=float)
  if p.ndim!=2 or p.shape[1]<2 or len(p)<2:continue
  level=int(r['properties'].get('db_segment_level',0));kind=1 if layer in MARKINGS else 2
  p=np.asarray(sh.segmentize(sh.LineString(p[:,:2]),3.).coords)
  for a,b in zip(p[:-1],p[1:]):
   if np.linalg.norm(b-a)<.03:continue
   records.append([*a,*b,0,0,kind,0]);tiers.append(level)
 lines=np.asarray(records);tiers=np.asarray(tiers);mid=(lines[:,:2]+lines[:,2:4])/2
 tree=sh.STRtree(sh.points(mid));bound=np.zeros(len(lines),bool)
 def bind(rows):
  if not rows:return
  polys=sh.from_geojson([json.dumps(r['geometry']) for r in rows]);si,li=tree.query(polys,predicate='covers')
  if not len(li):return
  eligible=np.asarray([tiers[j] in rows[i].get('tiers',[0]) for i,j in zip(si,li)])&~bound[li]
  si=si[eligible];li=li[eligible]
  if not len(li):return
  coeff=np.asarray([rows[i]['heightPlane'] for i in si])
  lines[li,4]=np.einsum('ij,ij->i',lines[li,:2],coeff[:,:2])+coeff[:,2]-origin[2]
  lines[li,5]=np.einsum('ij,ij->i',lines[li,2:4],coeff[:,:2])+coeff[:,2]-origin[2];bound[li]=True
 rows=[]
 for r in items(root,'surfaces'):
  if r['material']!=0 or not r['kind'].startswith('roadbed'):continue
  rows.append(r)
  if len(rows)==4096:bind(rows);rows=[]
 bind(rows)
 print('Road segments',len(lines),'bound by source tier',int(bound.sum()),flush=True)
 lines=lines[bound];lines[:,:4]-=np.tile(origin[:2],2);lines[:,[1,3]]*=-1
 return lines,dict(sourceSegments=len(bound),boundSegments=int(bound.sum()),unboundSegments=int((~bound).sum()))

def pack(lines,bounds):
 x0,z0,x1,z1=bounds;cols=math.ceil((x1-x0)/CELL);rows=math.ceil((z1-z0)/CELL)
 buckets=defaultdict(list)
 for i,s in enumerate(lines):
  ax,az,bx,bz=s[:4];margin=1.8 if s[6]==0 else (12.5 if s[6]==2 else MARGIN)
  lo=np.floor((np.minimum([ax,az],[bx,bz])-margin-[x0,z0])/CELL).astype(int);hi=np.floor((np.maximum([ax,az],[bx,bz])+margin-[x0,z0])/CELL).astype(int)
  for z in range(max(0,lo[1]),min(rows-1,hi[1])+1):
   for x in range(max(0,lo[0]),min(cols-1,hi[0])+1):buckets[z*cols+x].append(i)
 headers=np.zeros((cols*rows,4),'<f4');data=[];base=2+len(headers);offset=base+2*len(lines);maximum=0
 for cell,indices in sorted(buckets.items()):
  group=lines[indices];maximum=max(maximum,len(group))
  for k,mask in enumerate([group[:,6]==0,group[:,6]>0]):
   ids=np.asarray(indices)[mask];packed=np.zeros((math.ceil(len(ids)/4),4),'<f4');packed.flat[:len(ids)]=base+ids*2
   headers[cell,k*2:k*2+2]=[offset,len(ids)];data.append(packed);offset+=len(packed)
 assert offset<2**24,'Float lookup addresses require exact integer representation'
 values=np.concatenate([np.array([[x0,z0,CELL,cols],[rows,2,0,0]],'<f4'),headers,lines.astype('<f4').reshape(-1,4),*data])
 return values,dict(columns=cols,rows=rows,cellMetres=CELL,maxCellCandidates=maximum,bytes=values.nbytes,segments=len(lines))

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--catalog',type=Path,required=True);args=ap.parse_args();root=args.catalog
 scene=json.loads((root/'canonical/full/scene.json').read_text());cache=root/'surface-effects-source.npz'
 sources=[root/'canonical/urban-model.json.gz',root/'canonical/full/scene.json',root/'canonical/full/water-bank-domain.wkb']
 cacheFresh=cache.exists() and all(not p.exists() or p.stat().st_mtime_ns<=cache.stat().st_mtime_ns for p in sources)
 if cacheFresh:
  v=np.load(cache);shore=v['shore'];road=v['road'];stats=json.loads(str(v['stats']))
 else:
  print('Global shore boundaries',flush=True);shore=shoreline(root,scene);print('Shore segments',len(shore),flush=True)
  road,stats=road_lines(root,scene['origin']);np.savez_compressed(cache,shore=shore,road=road,stats=json.dumps(stats))
 bounds=json.loads((root/'tileset.json').read_text())['boundsMSK'];ox,oy,_=scene['origin'];local=[bounds[0]-ox,oy-bounds[3],bounds[2]-ox,oy-bounds[1]]
 values,proof=pack(np.concatenate([shore,road]),local);binary=values.tobytes();name='surface-effects-'+hashlib.sha256(binary).hexdigest()[:12]+'.bin.gz'
 (root/name).write_bytes(gzip.compress(binary,mtime=0));proof.update(stats,shoreSegments=len(shore),roadSegments=len(road),passed=True)
 meta=dict(version=2,file=name,sha256=hashlib.sha256(binary).hexdigest(),float4Count=len(values),**proof)
 (root/'surface-effects.json').write_text(json.dumps(meta,indent=2))
 configPath=root.parent/'config.json';config=json.loads(configPath.read_text());config.setdefault('surfaceEffects',{})[root.name+'/tileset.json']=root.name+'/surface-effects.json';configPath.write_text(json.dumps(config,ensure_ascii=False,indent=2)+'\n')
 print(json.dumps(meta),flush=True)
if __name__=='__main__':main()
