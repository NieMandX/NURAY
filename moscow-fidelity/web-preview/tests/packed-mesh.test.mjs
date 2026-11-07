import test from 'node:test';
import assert from 'node:assert/strict';
import {meshBytes,planMeshBatches,visitMeshBatches} from '../prototype/tiles/packed-mesh.js';
const pack={version:1,url:'meshes.pack',bytes:20,entries:{'meshes/a.bin.gz':[7,3]}};
test('cloud pack fetches exactly one byte-identical compressed block',async()=>{
  const result=await meshBytes('meshes/a.bin.gz','https://assets.example/release/',pack,async(url,options)=>{
    assert.equal(url.href,'https://assets.example/release/meshes.pack');assert.equal(options.headers.Range,'bytes=7-9');
    return new Response(new Uint8Array([31,139,8]),{status:206,headers:{'Content-Range':'bytes 7-9/20'}});
  });assert.deepEqual([...new Uint8Array(result)],[31,139,8]);
});

test('combined ranges preserve every block, deduplicate files and bound transfer concurrency',async()=>{
  const source=Uint8Array.from({length:8192},(_,i)=>i%251),entries={};
  for(let i=0;i<1000;i++)entries['block'+i]=[i*8,8];
  const p={version:1,url:'pack',bytes:source.length,entries};let calls=0,inflight=0,peak=0,transferred=0;
  const received=new Map();
  await visitMeshBatches([...Object.keys(entries).reverse(),'block0'],'https://example.org/',p,(file,bytes)=>{
    assert.ok(!received.has(file));received.set(file,bytes);
    const [o,n]=entries[file];assert.deepEqual(new Uint8Array(bytes),source.slice(o,o+n));
  },{maxBytes:1024,concurrency:3,onTransfer:n=>transferred+=n,fetcher:async(url,opts)=>{
    calls++;peak=Math.max(peak,++inflight);await new Promise(r=>setTimeout(r,1));inflight--;
    const [a,b]=opts.headers.Range.slice(6).split('-').map(Number);
    return new Response(source.slice(a,b+1),{status:206,headers:{'Content-Range':`bytes ${a}-${b}/${source.length}`}});
  }});
  assert.equal(calls,8);assert.equal(received.size,1000);assert.equal(transferred,8000);assert.equal(peak,3);
});

test('camera subset does not fetch distant tiles; corruption is rejected before any block is consumed',async()=>{
  const p={version:1,url:'pack',bytes:100000,entries:{a:[0,8],b:[10,8],far:[90000,10]}};
  const groups=planMeshBatches(['a','b','far'],p,{maxBytes:100000,maxGapBytes:10});
  assert.deepEqual(groups.map(g=>[g.start,g.end]),[[0,17],[90000,90009]]);
  let consumed=0;
  for(const response of [()=>new Response(new Uint8Array(18)),()=>new Response(new Uint8Array(17),{status:206,headers:{'Content-Range':'bytes 0-17/100000'}})]){
    await assert.rejects(visitMeshBatches(['a','b'],'https://example.org/',p,()=>consumed++,{fetcher:async()=>response()}));
  }
  assert.equal(consumed,0);
});
test('range ignored, shifted range and truncated block fail instead of using wrong geometry',async()=>{
  for(const [status,range,data] of [[200,null,[1,2,3]],[206,'bytes 8-10/20',[1,2,3]],[206,'bytes 7-9/20',[1,2]]]){
    await assert.rejects(meshBytes('meshes/a.bin.gz','https://assets.example/',pack,async()=>new Response(new Uint8Array(data),{status,headers:range?{'Content-Range':range}:{}})));
  }
});
test('invalid pack bounds fail before network; non-packed local catalogs still work',async()=>{
  await assert.rejects(meshBytes('meshes/a.bin.gz','https://assets.example/',{...pack,entries:{'meshes/a.bin.gz':[19,3]}},()=>{throw Error('must not fetch');}),/диапазон/);
  assert.deepEqual([...new Uint8Array(await meshBytes('meshes/a.bin.gz','https://assets.example/',null,async()=>new Response(new Uint8Array([1,2]))))],[1,2]);
});
