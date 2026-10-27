import test from 'node:test';
import assert from 'node:assert/strict';
import {meshBytes} from '../prototype/tiles/packed-mesh.js';
const pack={version:1,url:'meshes.pack',bytes:20,entries:{'meshes/a.bin.gz':[7,3]}};
test('cloud pack fetches exactly one byte-identical compressed block',async()=>{
  const result=await meshBytes('meshes/a.bin.gz','https://assets.example/release/',pack,async(url,options)=>{
    assert.equal(url.href,'https://assets.example/release/meshes.pack');assert.equal(options.headers.Range,'bytes=7-9');
    return new Response(new Uint8Array([31,139,8]),{status:206,headers:{'Content-Range':'bytes 7-9/20'}});
  });assert.deepEqual([...new Uint8Array(result)],[31,139,8]);
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
