import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {execFileSync} from 'node:child_process';
import {gzipSync} from 'node:zlib';
import {createHash} from 'node:crypto';
import {packingKey,readPacked,sha} from './transport_cache.mjs';

const here=path.dirname(fileURLToPath(import.meta.url));
const root=await fs.mkdtemp(path.join(os.tmpdir(),'nuray-pack-proof-'));
try{
 const positions=[[10,0,10],[490,0,10],[490,0,490],[10,0,10],[490,0,490],[10,0,490],
  [250,0,10],[250,5,10],[250,5,490],[10,0,250],[10,5,250],[490,5,250],
  [-10,2,-10],[510,4,510],[40,6,300],[250,0,250],[250,0,250],[250,0,250]];
 const words=new Uint32Array(positions.length*8),floats=new Float32Array(words.buffer);
 positions.forEach((p,i)=>{floats.set(p,i*8);words[i*8+3]=0x7fff0000;floats[i*8+4]=p[0];floats[i*8+5]=p[2];words[i*8+6]=0x80000000;});
 const raw=Buffer.concat([Buffer.from(words.buffer),Buffer.from(Uint32Array.from(positions,(_,i)=>i).buffer)]);
 const chunk={id:0,name:'roadbed_flat',category:'roadbed_flat',file:'mesh-000.bin.gz',vertexCount:positions.length,vertexBytes:words.byteLength,triangles:positions.length/3,bounds:{min:[-10,0,-10],max:[510,6,510]}};
 for(const value of [raw,raw.subarray(7,139),Buffer.alloc(0),'Москва']){
  assert.equal(sha(value,17),createHash('sha256').update(value).digest('hex'));
 }
 const context={bounds:[0,0,500,500],origin:[0,500,0],tileSize:250,columns:2,rows:2};
 assert.notEqual(packingKey(context,chunk,raw),packingKey({...context,tileSize:125},chunk,raw));
 assert.notEqual(packingKey(context,chunk,raw),packingKey(context,{...chunk,name:'paint'},raw));
 const changed=Buffer.from(raw);changed[0]^=1;assert.notEqual(packingKey(context,chunk,raw),packingKey(context,chunk,changed));
 async function run(name,disabled=false,bounded=false){
  const base=path.join(root,name),folder=path.join(base,'canonical/full');await fs.mkdir(folder,{recursive:true});
  const city={boundsMSK:context.bounds,originMSK:context.origin,transportTileSizeM:250,features:[],surfaces:[],limitations:[],sourceSnapshot:{freshAcquisition:true,receiptSha256:'fixture-only'}};
  const manifest={origin:context.origin,axes:'X east, Y up, Z south',chunks:[chunk,{...chunk,id:1,file:"mesh-001.bin.gz"}],instances:[],materials:[{color:[.3,.3,.3]}],textures:{}};
  await fs.writeFile(path.join(folder,chunk.file),gzipSync(raw));await fs.writeFile(path.join(folder,'mesh-001.bin.gz'),gzipSync(raw));
  await fs.writeFile(path.join(folder,'scene.json'),JSON.stringify(manifest));
  await fs.writeFile(path.join(base,'canonical/urban-model.json'),JSON.stringify(city));
  await fs.writeFile(path.join(base,'canonical/validation.json'),JSON.stringify({passed:true}));
  const log=execFileSync(process.execPath,[path.join(here,'pack_tiles.mjs'),base],{encoding:'utf8',env:{...process.env,NURAY_DISABLE_PACK_CACHE:disabled?'1':'0',NURAY_PACK_TILE_INDEX_THRESHOLD:bounded?'0':'Infinity'}});
  return {base,log,manifest:await fs.readFile(path.join(base,'tileset.json'),'utf8')};
 }
 const first=await run('first'),second=await run('second'),uncached=await run('uncached',true),bounded=await run('bounded',true,true);
 assert.match(second.log,/PACK REUSED/);assert.equal(first.manifest,second.manifest);assert.equal(first.manifest,uncached.manifest);
 assert.equal(first.manifest,bounded.manifest,'Bounded packing preserves the complete catalog and triangle lineage');
 const output=JSON.parse(first.manifest);
 for(const row of output.chunks){
  assert.deepEqual(await fs.readFile(path.join(first.base,row.file)),await fs.readFile(path.join(second.base,row.file)));
  assert.deepEqual(await fs.readFile(path.join(first.base,row.file)),await fs.readFile(path.join(bounded.base,row.file)));
 }
 const namespace=path.join(root,'.transport-cache/fixture-only');const [code]=await fs.readdir(namespace);const folder=path.join(namespace,code);
 const row=output.chunks[0],retained=await fs.readFile(path.join(first.base,row.file));
 assert.notEqual((await fs.stat(path.join(first.base,row.file))).ino,(await fs.stat(path.join(folder,row.file))).ino);
 await fs.writeFile(path.join(folder,row.file),Buffer.from('corrupt'));
 assert.deepEqual(await fs.readFile(path.join(first.base,row.file)),retained,'Cache mutation must not change the parent release');
 assert.deepEqual(await fs.readFile(path.join(second.base,row.file)),retained,'Cache mutation must not change the cloned release');
 assert.equal(await readPacked(folder,packingKey(context,chunk,raw)),null);
 const repaired=await run('repaired');assert.match(repaired.log,/PACK roadbed_flat 6/);assert.equal(repaired.manifest,first.manifest);
 const folder2=path.join(first.base,'canonical/full'),m=JSON.parse(await fs.readFile(path.join(folder2,'scene.json')));
 const lifted=Buffer.from(raw),liftedFloats=new Float32Array(lifted.buffer,lifted.byteOffset,words.length);for(let i=0;i<positions.length;i++)liftedFloats[i*8+1]=1;
 m.chunks[0].bounds.min[1]=m.chunks[0].bounds.max[1]=1;await fs.writeFile(path.join(folder2,'scene.json'),JSON.stringify(m));await fs.writeFile(path.join(folder2,chunk.file),gzipSync(lifted));
 const patchPath=path.join(first.base,'patch.json');await fs.writeFile(patchPath,JSON.stringify({changedChunks:[0],geometryRevision:{type:'fixture'}}));
 execFileSync(process.execPath,[path.join(here,'pack_tiles.mjs'),first.base,patchPath],{stdio:'pipe'});
 const incremental=JSON.parse(await fs.readFile(path.join(first.base,'tileset.json')));
 assert.deepEqual(incremental.chunks.filter(c=>c.sourceChunk===1),output.chunks.filter(c=>c.sourceChunk===1));
 assert.ok(incremental.chunks.filter(c=>c.sourceChunk===0).every(c=>c.bounds.min[1]===1&&c.bounds.max[1]===1));
 const proof=createHash('sha256').update(first.manifest);
 for(const row of output.chunks)proof.update(await fs.readFile(path.join(second.base,row.file)));
 console.log('PACK OUTPUT PROOF',proof.digest('hex'));
 await fs.writeFile(path.join(first.base,'canonical/validation.json'),JSON.stringify({passed:false}));
 assert.throws(()=>execFileSync(process.execPath,[path.join(here,'pack_tiles.mjs'),first.base,patchPath],{stdio:'pipe'}),/Canonical validation failed/);
 console.log('Packing cache passed: byte-identical bounded meshes/catalog/lineage; grid/role/geometry invalidation; corrupt payload rebuilt; chunked SHA-256.');
}finally{await fs.rm(root,{recursive:true,force:true});}
