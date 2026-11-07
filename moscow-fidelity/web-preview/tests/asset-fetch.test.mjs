import test from 'node:test';
import assert from 'node:assert/strict';
import {gzipSync} from 'node:zlib';
import {createHash} from 'node:crypto';
import {readFileSync} from 'node:fs';
import {Script} from 'node:vm';
import {openAsset,readAssetJSON,mapConcurrent} from '../src/district/asset-fetch.js';

test('viewer bootstrap remains valid JavaScript after updating its cache version',()=>{
  const html=readFileSync(new URL('../prototype/tiles/index.html',import.meta.url),'utf8');
  for(const match of html.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/g))new Script(match[1]);
});

test('gzip delivery restores exact bytes and reports compressed transfer bytes',async()=>{
  const original=Buffer.from(JSON.stringify({geometry:Array.from({length:20000},(_,i)=>i%31)}));
  const zipped=gzipSync(original);let transferred=0;
  const spec={url:'catalog.json.gz',encoding:'gzip',bytes:zipped.length,decodedBytes:original.length,
    decodedSha256:createHash('sha256').update(original).digest('hex')};
  const fetcher=async()=>new Response(new ReadableStream({start(c){for(let i=0;i<zipped.length;i+=13)c.enqueue(zipped.subarray(i,i+13));c.close();}}));
  assert.deepEqual(await readAssetJSON(spec,'https://example.org/',n=>transferred=n,fetcher),JSON.parse(original));
  assert.equal(transferred,zipped.length);assert.ok(transferred<original.length/5);
  await assert.rejects(readAssetJSON({...spec,decodedSha256:'0'.repeat(64)},'https://example.org/',null,fetcher),/сумма/);
});

test('truncated gzip, a corrupt trailer, and wrong decoded size fail at EOF',async()=>{
  const raw=Buffer.from('verified data'.repeat(10000)),zip=gzipSync(raw),bad=Buffer.from(zip);bad[bad.length-5]^=1;
  for(const [bytes,decodedBytes] of [[zip.subarray(0,-4),raw.length],[bad,raw.length],[zip,raw.length+1]]){
    const stream=await openAsset({url:'model.glb.gz',encoding:'gzip',bytes:bytes.length,decodedBytes},'https://example.org/',undefined,async()=>new Response(bytes));
    await assert.rejects(new Response(stream).arrayBuffer());
  }
});

test('legacy uncompressed files still load; failed work settles before returning',async()=>{
  assert.deepEqual(await readAssetJSON({url:'old.json'},'https://example.org/',undefined,async()=>new Response('{"old":true}')),{old:true});
  let active=0;const seen=[];
  await assert.rejects(mapConcurrent([0,1,2,3,4,5],async n=>{seen.push(n);active++;try{if(n===0)throw Error('failed');await new Promise(r=>setTimeout(r,10));}finally{active--;}}),/failed/);
  assert.equal(active,0);assert.ok(seen.length<=4);
});
