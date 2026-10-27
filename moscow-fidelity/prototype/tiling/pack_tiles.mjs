// Transport tiles cut from the single validated canonical mesh. No new faces.
import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {gzipSync,gunzipSync} from 'node:zlib';
import {createHash} from 'node:crypto';
import {execFileSync} from 'node:child_process';
import {buildMeshBvh,transformBounds} from '../../web-preview/src/district/bvh.js';
import {packingKey,readPacked,savePacked} from './transport_cache.mjs';
const here=path.dirname(fileURLToPath(import.meta.url)),root=path.resolve(process.argv[2]??path.resolve(here,'../../web-preview/prototype/tiles/assets'));
const patchFile=process.argv[3], incremental=patchFile?JSON.parse(await fs.readFile(patchFile)):null;
const changed=incremental?new Set(incremental.changedChunks):null;
const previous=incremental?JSON.parse(await fs.readFile(path.join(root,'tileset.json'))):null;
if(!incremental)execFileSync(process.env.PYTHON??'python3',[path.join(here,'prepare_transport.py'),root],{stdio:'inherit'});
const source=path.join(root,'canonical/full'),city=JSON.parse(await fs.readFile(path.join(root,'canonical/transport-metadata.json'))),report=JSON.parse(await fs.readFile(path.join(root,'canonical/validation.json')));
if(!report.passed)throw Error('Canonical validation failed');
const manifest=JSON.parse(await fs.readFile(path.join(source,'scene.json')));
const tiles=[],tileSize=city.transportTileSizeM??250;
const [x0,y0,x1,y1]=city.boundsMSK,[ox,oy]=city.originMSK;
const columns=Math.ceil((x1-x0)/tileSize),rows=Math.ceil((y1-y0)/tileSize);
const cacheEnabled=city.sourceSnapshot?.freshAcquisition&&city.sourceSnapshot?.receiptSha256&&process.env.NURAY_DISABLE_PACK_CACHE!=='1';
const codeHash=createHash('sha256');
for(const file of [fileURLToPath(import.meta.url),path.join(here,'transport_cache.mjs'),path.join(here,'../../web-preview/src/district/bvh.js')])codeHash.update(await fs.readFile(file));
const cacheFolder=cacheEnabled?path.join(root,'..','.transport-cache',city.sourceSnapshot.receiptSha256,codeHash.digest('hex')):null;
const cacheContext={bounds:city.boundsMSK,origin:city.originMSK,tileSize,columns,rows};
for(let north=0;north<rows;north++)for(let east=0;east<columns;east++){
 const bounds=[x0+east*tileSize,y0+north*tileSize,Math.min(x1,x0+(east+1)*tileSize),Math.min(y1,y0+(north+1)*tileSize)];
 tiles.push({id:`${east}-${north}`,east,north,boundsMSK:bounds,
   bounds:{min:[bounds[0]-ox,-100,oy-bounds[3]],max:[bounds[2]-ox,100,oy-bounds[1]]},chunks:[],coarseChunks:[],instances:[],fullTriangles:0,coarseTriangles:0});
}
const assets=new Map(),sourceChunks=[],seamStats={};
const scratch=new ArrayBuffer(32),sf=new Float32Array(scratch),su=new Uint32Array(scratch),si=new Int16Array(scratch);
function unpack(row){
 const o=row*8,x=this.f[o],y=this.f[o+1],z=this.f[o+2],p=this.u[o+3];
 let nx=(p<<16>>16)/32767,ny=(p>>16)/32767,nz=1-Math.abs(nx)-Math.abs(ny);
 if(nz<0){const a=nx;nx=(1-Math.abs(ny))*(a>=0?1:-1);ny=(1-Math.abs(a))*(ny>=0?1:-1);}
 const n=Math.hypot(nx,ny,nz);return [x,y,z,nx/n,ny/n,nz/n,this.f[o+4],this.f[o+5]];
}
function pack(v,material){
 sf.fill(0);sf.set(v.slice(0,3));sf[4]=v[6];sf[5]=v[7];
 let [x,y,z]=v.slice(3,6);const n=Math.abs(x)+Math.abs(y)+Math.abs(z);x/=n;y/=n;
 if(z<0){const a=x;x=(1-Math.abs(y))*(a>=0?1:-1);y=(1-Math.abs(a))*(y>=0?1:-1);}
 si[6]=Math.round(Math.max(-1,Math.min(1,x))*32767);si[7]=Math.round(Math.max(-1,Math.min(1,y))*32767);su[6]=material;return [...su];
}
function clip(input,b){
 let v=input;
 for(const [axis,edge,sign] of [[0,b.min[0],1],[0,b.max[0],-1],[2,b.min[2],1],[2,b.max[2],-1]]){
  const out=[];
  for(let i=0;i<v.length;i++){
   const a=v[i],c=v[(i+1)%v.length],da=(a[axis]-edge)*sign,dc=(c[axis]-edge)*sign;
   if(da>=0)out.push(a);
   if((da>=0)!==(dc>=0)){const t=da/(da-dc),p=a.map((x,j)=>x+(c[j]-x)*t);p[axis]=edge;out.push(p);}
  }
  v=out;if(v.length<3)return [];
 }
 return Array.from({length:v.length-2},(_,i)=>[v[0],v[i+1],v[i+2]]);
}
function faceArea(t){const a=t[1].map((x,i)=>x-t[0][i]),b=t[2].map((x,i)=>x-t[0][i]);return Math.hypot(a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]);}
let originalTriangles=0,exportedTriangles=0;
for(const c of manifest.chunks){
 if(incremental&&!changed.has(c.id)){
  originalTriangles+=c.triangles;sourceChunks.push(previous.sourceChunks.find(s=>s.id===c.id));
  for(const a of previous.chunks.filter(a=>a.sourceChunk===c.id)){
   assets.set(a.id,a);
   if(a.instanced){
    for(const old of previous.tiles)for(const i of old.instances.filter(i=>i.mesh===a.id)){
     const t=tiles.find(t=>t.id===old.id);t.instances.push(i);t.fullTriangles+=a.triangles;t.coarseTriangles+=a.triangles;exportedTriangles+=a.triangles;
    }
   }else{
    const t=tiles.find(t=>t.id===a.tileId);t.chunks.push(a.id);t.fullTriangles+=a.triangles;exportedTriangles+=a.triangles;
    if(!['paint','unbound-paint'].includes(c.name)){t.coarseChunks.push(a.id);t.coarseTriangles+=a.triangles;}
   }
  }
  continue;
 }
 const data=gunzipSync(await fs.readFile(path.join(source,path.basename(c.file))));
 const cacheKey=cacheFolder&&!c.instanced?packingKey(cacheContext,c,data):null;
 const cached=cacheKey?await readPacked(cacheFolder,cacheKey):null;
 if(cached){
  await fs.mkdir(path.join(root,'meshes'),{recursive:true});
  originalTriangles+=c.triangles;sourceChunks.push({id:c.id,name:c.name,triangles:c.triangles,...(c.sourceObjectIds?{sourceObjectIds:c.sourceObjectIds}:{})});
  for(const {row,bytes} of cached){
   await fs.writeFile(path.join(root,row.file),bytes);assets.set(row.id,row);
   const tile=tiles.find(t=>t.id===row.tileId);if(!tile)throw Error('Cached tile is outside this exact grid');
   tile.chunks.push(row.id);tile.fullTriangles+=row.triangles;exportedTriangles+=row.triangles;
   if(!['paint','unbound-paint'].includes(c.name)){tile.coarseChunks.push(row.id);tile.coarseTriangles+=row.triangles;}
  }
  console.log('PACK REUSED',c.name,c.triangles);continue;
 }
 const buffer=data.buffer.slice(data.byteOffset,data.byteOffset+data.byteLength),u=new Uint32Array(buffer,0,c.vertexBytes/4),f=new Float32Array(buffer,0,c.vertexBytes/4),ix=new Uint32Array(buffer,c.vertexBytes);
 if(c.instanced){
  const originalIx=new Uint32Array(ix),mesh=buildMeshBvh({vertices:buffer.slice(0,c.vertexBytes),indices:originalIx.buffer},'sah');
  const reordered=new Uint32Array(mesh.indices),queues=new Map();
  for(let i=0;i<originalIx.length;i+=3){const key=`${originalIx[i]},${originalIx[i+1]},${originalIx[i+2]}`;if(!queues.has(key))queues.set(key,[]);queues.get(key).push(i/3);}
  const lineage=new Uint32Array(reordered.length/3);
  for(let i=0;i<reordered.length;i+=3)lineage[i/3]=queues.get(`${reordered[i]},${reordered[i+1]},${reordered[i+2]}`).shift();
  const raw=Buffer.concat([Buffer.from(mesh.vertices),Buffer.from(mesh.indices),Buffer.from(mesh.nodes),Buffer.from(lineage.buffer)]),hash=createHash('sha256').update(raw).digest('hex'),file=`meshes/${hash}.bin.gz`,gz=gzipSync(raw,{level:6}),id=`shared:${c.id}`;
  await fs.mkdir(path.join(root,'meshes'),{recursive:true});await fs.writeFile(path.join(root,file),gz);
  assets.set(id,{id,tileId:null,name:c.name,category:c.category,instanced:true,objectGeometry:true,sourceChunk:c.id,file,sha256:hash,downloadBytes:gz.length,vertexCount:c.vertexCount,vertexBytes:c.vertexBytes,indexBytes:mesh.indices.byteLength,nodeBytes:mesh.nodes.byteLength,lineageBytes:lineage.byteLength,nodeCount:mesh.nodeCount,triangles:c.triangles,bounds:c.bounds,format:'nuray-tile-mesh-v1'});
  originalTriangles+=c.triangles;sourceChunks.push({id:c.id,name:c.name,triangles:c.triangles,instanced:true});
  for(const instance of manifest.instances.filter(i=>i.mesh===c.id)){
   const tile=tiles.find(t=>t.id===instance.tileId);if(!tile)throw Error('Missing instance owner tile '+instance.id);
   tile.instances.push({...instance,mesh:id});tile.fullTriangles+=c.triangles;tile.coarseTriangles+=c.triangles;exportedTriangles+=c.triangles;
  }
  console.log('PACK SHARED',c.name,c.triangles);continue;
 }
 const read=unpack.bind({f,u});const buckets=tiles.map(()=>({words:[],indices:[],lineage:[],seen:new Map()}));
 for(let i=0;i<ix.length;i+=3){
  const tri=[read(ix[i]),read(ix[i+1]),read(ix[i+2])];const material=u[ix[i]*8+6];
  const lo=[Math.min(...tri.map(v=>v[0])),Math.min(...tri.map(v=>v[2]))],hi=[Math.max(...tri.map(v=>v[0])),Math.max(...tri.map(v=>v[2]))];
  // Candidate ownership rectangles follow directly from the triangle AABB.
  // Include both sides of exact grid lines; the existing half-open rule below
  // decides ownership of vertical boundary faces without a 400-tile scan.
  const e0=Math.max(0,Math.floor((lo[0]+ox-x0)/tileSize)-1),e1=Math.min(columns-1,Math.floor((hi[0]+ox-x0)/tileSize));
  const n0=Math.max(0,Math.floor((oy-hi[1]-y0)/tileSize)-1),n1=Math.min(rows-1,Math.floor((oy-lo[1]-y0)/tileSize));
  for(let north=n0;north<=n1;north++)for(let east=e0;east<=e1;east++){
   const j=north*columns+east;
   const b=tiles[j].bounds;if(hi[0]<b.min[0]||lo[0]>b.max[0]||hi[1]<b.min[2]||lo[1]>b.max[2])continue;
   // A face lying exactly on an internal cut has one deterministic owner.
   if(lo[0]===hi[0]&&lo[0]===b.max[0]&&tiles[j].east<columns-1)continue;
   if(lo[1]===hi[1]&&lo[1]===b.min[2]&&tiles[j].north<rows-1)continue;
   const bucket=buckets[j];
   for(const t of clip(tri,b)){
    if(faceArea(t)<1e-9)continue;
    const ids=t.map(v=>{const row=pack(v,material),key=row.join(',');let id=bucket.seen.get(key);if(id===undefined){id=bucket.words.length/8;bucket.words.push(...row);bucket.seen.set(key,id);}return id;});
    bucket.indices.push(...ids);bucket.lineage.push(i/3);
   }
  }
 }
 originalTriangles+=c.triangles;sourceChunks.push({id:c.id,name:c.name,triangles:c.triangles,...(c.sourceObjectIds?{sourceObjectIds:c.sourceObjectIds}:{})});
 for(let j=0;j<tiles.length;j++){
  const b=buckets[j];if(!b.indices.length)continue;
  const vertices=Uint32Array.from(b.words).buffer,originalIx=Uint32Array.from(b.indices),mesh=buildMeshBvh({vertices,indices:originalIx.buffer},'sah');
  const reordered=new Uint32Array(mesh.indices),queues=new Map();
  for(let i=0;i<originalIx.length;i+=3){const key=`${originalIx[i]},${originalIx[i+1]},${originalIx[i+2]}`;if(!queues.has(key))queues.set(key,[]);queues.get(key).push(i/3);}
  const lineage=new Uint32Array(reordered.length/3);
  for(let i=0;i<reordered.length;i+=3)lineage[i/3]=b.lineage[queues.get(`${reordered[i]},${reordered[i+1]},${reordered[i+2]}`).shift()];
  const raw=Buffer.concat([Buffer.from(mesh.vertices),Buffer.from(mesh.indices),Buffer.from(mesh.nodes),Buffer.from(lineage.buffer)]),hash=createHash('sha256').update(raw).digest('hex'),file=`meshes/${hash}.bin.gz`,gz=gzipSync(raw,{level:6});
  await fs.mkdir(path.join(root,'meshes'),{recursive:true});await fs.writeFile(path.join(root,file),gz);
  const p=new Float32Array(vertices),min=[Infinity,Infinity,Infinity],max=[-Infinity,-Infinity,-Infinity];for(let i=0;i<p.length;i+=8)for(let a=0;a<3;a++){min[a]=Math.min(min[a],p[i+a]);max[a]=Math.max(max[a],p[i+a]);}
  const id=`${tiles[j].id}:${c.id}`;
  assets.set(id,{id,tileId:tiles[j].id,name:c.name,category:c.category,objectGeometry:!!c.objectGeometry,sourceChunk:c.id,file,sha256:hash,downloadBytes:gz.length,
   vertexCount:b.words.length/8,vertexBytes:vertices.byteLength,indexBytes:mesh.indices.byteLength,nodeBytes:mesh.nodes.byteLength,lineageBytes:lineage.byteLength,nodeCount:mesh.nodeCount,triangles:b.indices.length/3,bounds:{min,max},format:'nuray-tile-mesh-v1'});
  tiles[j].chunks.push(id);tiles[j].fullTriangles+=b.indices.length/3;exportedTriangles+=b.indices.length/3;
  if(!['paint','unbound-paint'].includes(c.name)){tiles[j].coarseChunks.push(id);tiles[j].coarseTriangles+=b.indices.length/3;}
 }
 if(cacheKey)await savePacked(cacheFolder,cacheKey,[...assets.values()].filter(a=>a.sourceChunk===c.id),root);
 console.log('PACK',c.name,c.triangles);
}
const list=[...assets.values()];
// Ownership rectangles stay on the tile grid. Content bounds include complete
// transformed crowns and the actual heights of buildings, for future culling.
for(const tile of tiles){
 const bounds=[...tile.chunks.map(id=>assets.get(id).bounds),...tile.instances.map(i=>transformBounds(assets.get(i.mesh).bounds,i.matrix))];
 if(!bounds.length)continue;
 tile.contentBounds={min:[0,1,2].map(a=>Math.min(...bounds.map(b=>b.min[a]))),max:[0,1,2].map(a=>Math.max(...bounds.map(b=>b.max[a])))};
 tile.bounds.min[1]=tile.contentBounds.min[1];tile.bounds.max[1]=tile.contentBounds.max[1];
}
const scene={version:1,format:'nuray-spatial-tiles-v1',name:`${city.name||'Кутузовская'} · ${columns*rows} тайлов`,regionName:city.name||'Кутузовская',crsProj:city.crsProj,extentMetres:Math.max(x1-x0,y1-y0),tileSizeM:tileSize,grid:{columns,rows},
 origin:manifest.origin,axes:manifest.axes,boundsMSK:city.boundsMSK,materials:manifest.materials,textures:manifest.textures,sourceSnapshot:city.sourceSnapshot,
 tiles,chunks:list,sourceChunks,stats:{originalTriangles,fullTriangles:exportedTriangles,coarseTriangles:tiles.reduce((n,t)=>n+t.coarseTriangles,0),
  uniqueTriangles:list.reduce((n,c)=>n+c.triangles,0),objectLayer:city.objectLayer?.stats,
  fullDownloadBytes:list.reduce((n,c)=>n+c.downloadBytes,0),coarseDownloadBytes:list.filter(c=>!['paint','unbound-paint'].includes(c.name)).reduce((n,c)=>n+c.downloadBytes,0)},
 bvh:{version:1,nodeStride:32,vertexStride:32,leafSize:8,strategy:'sah',prebuilt:true},
 rules:{cut:'clip canonical triangle attributes, do not generate boundary walls; unique ownership for cut-aligned vertical faces',
  preview:'far tiles reuse exact surfaces and structures, omitting road paint only; no geometric simplification yet',
  coordinates:'one region frame; UVs, heights and normals are interpolated from the same canonical triangles',
  identity:'each emitted triangle retains canonical source chunk and primitive index'},
 limitations:city.limitations,objectLayer:city.objectLayer?{stats:city.objectLayer.stats,policy:city.objectLayer.policy,variation:city.objectLayer.variation,customLibrary:city.objectLayer.customLibrary,foundations:city.objectLayer.foundations?{stats:city.objectLayer.foundations.stats,policy:city.objectLayer.foundations.policy}:undefined}:undefined,
 railwayLayer:city.railwayLayer?{stats:city.railwayLayer.stats,policy:city.railwayLayer.policy,texture:city.railwayLayer.texture}:undefined,
 streetLayer:city.streetLayer?{stats:city.streetLayer.stats,policy:city.streetLayer.policy,witnessViews:city.streetLayer.witnessViews,fences:city.streetLayer.fences}:undefined};
if(previous?.witnessViews)scene.witnessViews=previous.witnessViews;
if(incremental?.witnessViews)scene.witnessViews={...scene.witnessViews,...incremental.witnessViews};
if(incremental)scene.geometryRevision=incremental.geometryRevision;
if(city.objectLayer?.roofs)scene.objectLayer.roofs=city.objectLayer.roofs;
if(city.objectLayer?.pitchedRoofs)scene.objectLayer.pitchedRoofs=city.objectLayer.pitchedRoofs;
if(manifest.waterfront)scene.waterfront=manifest.waterfront;
await fs.writeFile(path.join(root,'tileset.json'),JSON.stringify(scene));
if(incremental){
 const referenced=new Set(list.map(c=>path.basename(c.file)));
 for(const name of await fs.readdir(path.join(root,'meshes')))if(!referenced.has(name))await fs.unlink(path.join(root,'meshes',name));
}
console.log('TILESET',JSON.stringify(scene.stats),{tiles:tiles.length,incremental:!!incremental});
