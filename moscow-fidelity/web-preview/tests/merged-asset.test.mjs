import test from 'node:test';
import assert from 'node:assert/strict';
import {gzipSync} from 'node:zlib';
import {openMergedAsset} from '../prototype/tiles/merged-asset.js';

const url='https://example.invalid/release/merged/model.gltf';
function fixture(uri='model.bin',truncate=false){
  const binary=Uint8Array.from([1,2,3,4,5,6,7,8]);
  const doc={asset:{version:'2.0'},buffers:[{uri,byteLength:binary.length}],extras:{nuray:{}}};
  const header=new TextEncoder().encode(JSON.stringify(doc));
  const calls=[];
  return {binary,doc,header,calls,fetcher:async input=>{
    calls.push(String(input));
    return new Response(String(input).endsWith('.gltf')?header:truncate?binary.slice(0,-1):binary);
  }};
}
test('external merged glTF streams all bytes and resolves beside its header',async()=>{
  const f=fixture(),progress=[];
  const asset=await openMergedAsset(url,{fetcher:f.fetcher,onProgress:(n,total)=>progress.push([n,total])});
  assert.deepEqual(asset.doc,f.doc);assert.equal(asset.format,'gltf');
  assert.deepEqual(await asset.reader.take(3),f.binary.slice(0,3));
  assert.deepEqual(await asset.reader.take(5),f.binary.slice(3));
  await asset.reader.finish();
  assert.equal(asset.reader.bytes,asset.expectedStreamBytes);
  assert.deepEqual(f.calls,[url,'https://example.invalid/release/merged/model.bin']);
  assert.deepEqual(progress.at(-1),[asset.length,asset.length]);
});
test('truncated buffer and unexpected external URIs are rejected',async()=>{
  const f=fixture('model.bin',true),asset=await openMergedAsset(url,{fetcher:f.fetcher});
  await assert.rejects(()=>asset.reader.take(8),/Неполные|оборван/);
  const unsafe=fixture('../private.bin');
  await assert.rejects(()=>openMergedAsset(url,{fetcher:unsafe.fetcher}),/Неверный внешний/);
  assert.equal(unsafe.calls.length,1);
});
test('compressed header and binary resolve against the catalog, counting actual transfer bytes',async()=>{
  const f=fixture(),header=gzipSync(f.header),binary=gzipSync(f.binary),calls=[],counts=[];
  const asset=await openMergedAsset(url,{
    base:'https://example.invalid/release/tileset.json',
    spec:{url:'delivery/model.gltf.gz',encoding:'gzip',decodedBytes:f.header.length},
    bufferSpec:{url:'delivery/model.bin.gz',encoding:'gzip',decodedBytes:f.binary.length},
    onBytes:n=>counts.push(n),
    fetcher:async input=>{calls.push(String(input));return new Response(String(input).endsWith('.gltf.gz')?header:binary);},
  });
  assert.deepEqual(await asset.reader.take(asset.binaryLength),f.binary);await asset.reader.finish();
  assert.deepEqual(calls,['https://example.invalid/release/delivery/model.gltf.gz','https://example.invalid/release/delivery/model.bin.gz']);
  assert.equal(counts.at(-1),header.length+binary.length);
});
test('existing GLB keeps binary offsets and strict end-of-stream validation',async()=>{
  const f=fixture();delete f.doc.buffers[0].uri;
  let text=JSON.stringify(f.doc);text+=' '.repeat((4-text.length%4)%4);
  const header=new TextEncoder().encode(text),all=new Uint8Array(28+header.length+f.binary.length),d=new DataView(all.buffer);
  d.setUint32(0,0x46546c67,true);d.setUint32(4,2,true);d.setUint32(8,all.length,true);d.setUint32(12,header.length,true);d.setUint32(16,0x4e4f534a,true);all.set(header,20);
  d.setUint32(20+header.length,f.binary.length,true);d.setUint32(24+header.length,0x004e4942,true);all.set(f.binary,28+header.length);
  const asset=await openMergedAsset(url.replace('.gltf','.glb'),{fetcher:async()=>new Response(all)});
  assert.deepEqual(await asset.reader.take(asset.binaryLength),f.binary);await asset.reader.finish();
  assert.equal(asset.reader.bytes,asset.expectedStreamBytes);assert.equal(asset.length,all.length);
});
test('external scene crosses the 4 GiB boundary without offset wrapping or a full-size allocation',async()=>{
  const block=new Uint8Array(1024*1024),tail=Uint8Array.from([91,92,93,94]);let sent=0,lastProgress;
  const header=new TextEncoder().encode(JSON.stringify({asset:{version:'2.0'},buffers:[{uri:'model.bin',byteLength:2**32+tail.length}]}));
  const asset=await openMergedAsset(url,{onProgress:(n,total)=>{lastProgress=[n,total];},fetcher:async input=>
    String(input).endsWith('.gltf')?new Response(header):new Response(new ReadableStream({pull(controller){
      if(sent++<4096)controller.enqueue(block);
      else if(sent===4097)controller.enqueue(tail);
      else controller.close();
    }}))});
  await asset.reader.take(2**32,false);
  assert.deepEqual(await asset.reader.take(tail.length),tail);
  await asset.reader.finish();
  assert.equal(asset.reader.bytes,2**32+tail.length);
  assert.deepEqual(lastProgress,[header.length+2**32+tail.length,asset.length]);
});
