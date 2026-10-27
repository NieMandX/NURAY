import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {execFileSync} from 'node:child_process';
import {gzipSync} from 'node:zlib';
import {packingKey,readPacked} from './transport_cache.mjs';

const here=path.dirname(fileURLToPath(import.meta.url));
const root=await fs.mkdtemp(path.join(os.tmpdir(),'nuray-pack-proof-'));
try{
 const positions=[[10,0,10],[490,0,10],[490,0,490],[10,0,10],[490,0,490],[10,0,490]];
 const words=new Uint32Array(6*8),floats=new Float32Array(words.buffer);
 positions.forEach((p,i)=>{floats.set(p,i*8);words[i*8+3]=0x7fff0000;floats[i*8+4]=p[0];floats[i*8+5]=p[2];words[i*8+6]=0x80000000;});
 const raw=Buffer.concat([Buffer.from(words.buffer),Buffer.from(new Uint32Array([0,1,2,3,4,5]).buffer)]);
 const chunk={id:0,name:'roadbed_flat',category:'roadbed_flat',file:'mesh-000.bin.gz',vertexCount:6,vertexBytes:192,triangles:2,bounds:{min:[10,0,10],max:[490,0,490]}};
 const context={bounds:[0,0,500,500],origin:[0,500,0],tileSize:250,columns:2,rows:2};
 assert.notEqual(packingKey(context,chunk,raw),packingKey({...context,tileSize:125},chunk,raw));
 assert.notEqual(packingKey(context,chunk,raw),packingKey(context,{...chunk,name:'paint'},raw));
 const changed=Buffer.from(raw);changed[0]^=1;assert.notEqual(packingKey(context,chunk,raw),packingKey(context,chunk,changed));
 async function run(name,disabled=false){
  const base=path.join(root,name),folder=path.join(base,'canonical/full');await fs.mkdir(folder,{recursive:true});
  const city={boundsMSK:context.bounds,originMSK:context.origin,transportTileSizeM:250,features:[],surfaces:[],limitations:[],sourceSnapshot:{freshAcquisition:true,receiptSha256:'fixture-only'}};
  const manifest={origin:context.origin,axes:'X east, Y up, Z south',chunks:[chunk,{...chunk,id:1,file:"mesh-001.bin.gz"}],instances:[],materials:[{color:[.3,.3,.3]}],textures:{}};
  await fs.writeFile(path.join(folder,chunk.file),gzipSync(raw));await fs.writeFile(path.join(folder,'mesh-001.bin.gz'),gzipSync(raw));
  await fs.writeFile(path.join(folder,'scene.json'),JSON.stringify(manifest));
  await fs.writeFile(path.join(base,'canonical/urban-model.json'),JSON.stringify(city));
  await fs.writeFile(path.join(base,'canonical/validation.json'),JSON.stringify({passed:true}));
  const log=execFileSync(process.execPath,[path.join(here,'pack_tiles.mjs'),base],{encoding:'utf8',env:{...process.env,NURAY_DISABLE_PACK_CACHE:disabled?'1':'0'}});
  return {base,log,manifest:await fs.readFile(path.join(base,'tileset.json'),'utf8')};
 }
 const first=await run('first'),second=await run('second'),uncached=await run('uncached',true);
 assert.match(second.log,/PACK REUSED/);assert.equal(first.manifest,second.manifest);assert.equal(first.manifest,uncached.manifest);
 const output=JSON.parse(first.manifest);
 for(const row of output.chunks){assert.deepEqual(await fs.readFile(path.join(first.base,row.file)),await fs.readFile(path.join(second.base,row.file)));}
 const namespace=path.join(root,'.transport-cache/fixture-only');const [code]=await fs.readdir(namespace);const folder=path.join(namespace,code);
 const row=output.chunks[0];await fs.writeFile(path.join(folder,row.file),Buffer.from('corrupt'));
 assert.equal(await readPacked(folder,packingKey(context,chunk,raw)),null);
 const repaired=await run('repaired');assert.match(repaired.log,/PACK roadbed_flat 2/);assert.equal(repaired.manifest,first.manifest);
 const folder2=path.join(first.base,'canonical/full'),m=JSON.parse(await fs.readFile(path.join(folder2,'scene.json')));
 const lifted=Buffer.from(raw),liftedFloats=new Float32Array(lifted.buffer,lifted.byteOffset,48);for(let i=0;i<6;i++)liftedFloats[i*8+1]=1;
 m.chunks[0].bounds.min[1]=m.chunks[0].bounds.max[1]=1;await fs.writeFile(path.join(folder2,'scene.json'),JSON.stringify(m));await fs.writeFile(path.join(folder2,chunk.file),gzipSync(lifted));
 const patchPath=path.join(first.base,'patch.json');await fs.writeFile(patchPath,JSON.stringify({changedChunks:[0],geometryRevision:{type:'fixture'}}));
 execFileSync(process.execPath,[path.join(here,'pack_tiles.mjs'),first.base,patchPath],{stdio:'pipe'});
 const incremental=JSON.parse(await fs.readFile(path.join(first.base,'tileset.json')));
 assert.deepEqual(incremental.chunks.filter(c=>c.sourceChunk===1),output.chunks.filter(c=>c.sourceChunk===1));
 assert.ok(incremental.chunks.filter(c=>c.sourceChunk===0).every(c=>c.bounds.min[1]===1&&c.bounds.max[1]===1));
 console.log('Packing cache passed: byte-identical meshes/catalog; grid/role/geometry invalidation; corrupt payload rebuilt.');
}finally{await fs.rm(root,{recursive:true,force:true});}
