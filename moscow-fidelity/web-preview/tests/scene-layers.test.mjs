import test from 'node:test';
import assert from 'node:assert/strict';
import {sceneLayer,layerVisible,normalizeLayers} from '../prototype/tiles/scene-layers.js';
import {validateVisibility} from '../prototype/tiles/merged-visibility.js';
import {mergedInstances} from '../prototype/tiles/merged-trace.js';
import {traceScene} from '../prototype/tiles/tile-scene.js';
test('semantic switches keep lawns, bridge supports, embankments and other street furniture',()=>{
 for(const name of ['nuray-approved-birch','nuray-approved-bush'])assert.equal(sceneLayer({name}),'vegetation');
 for(const name of ['street-lamppost1','street-lamppost4'])assert.equal(sceneLayer({name}),'lights');
 for(const name of ['street-swing2','street-slide2','street-trampoline'])assert.equal(sceneLayer({name}),'playgrounds');
 assert.equal(sceneLayer({name:'street-fences'}),'fences');
 for(const name of ['land','street-supports','waterfront-bank','street-bench1','street-busstation','street-workout'])assert.equal(layerVisible({name},normalizeLayers({vegetation:false,fences:false,playgrounds:false,lights:false})),true);
 assert.deepEqual(normalizeLayers({vegetation:'false',fences:false}),{vegetation:true,fences:false,playgrounds:true,lights:true});
});
test('filtered shared instances are absent from every ray traversal and return without changing transforms',()=>{
 const draws=[{id:0,name:'city-0',instanceFirst:0,instanceCount:1},{id:1,name:'nuray-approved-birch',instanceFirst:1,instanceCount:2},{id:2,name:'street-lamppost1',instanceFirst:3,instanceCount:1}];
 const transforms=Float32Array.from([1,0,0,0,0,1,0,0,0,0,1,0,1,0,0,10,0,1,0,0,0,0,1,0,1,0,0,20,0,1,0,0,0,0,1,0,1,0,0,30,0,1,0,0,0,0,1,0]);
 const assets=new Map(draws.map(d=>[d.id,{bounds:{min:[0,0,0],max:[1,1,1]}}]));const descriptors=new Map(draws.map(d=>[d.id,{page:0,vertex:d.id*32,index:96,nodes:100,nodeCount:1}]));
 const hidden=mergedInstances(draws.filter(d=>layerVisible(d,{vegetation:false,lights:false})),transforms);
 assert.equal(hidden.length,1);assert.equal(new Uint32Array(traceScene(hidden,assets,descriptors))[2],1);
 assert.equal(mergedInstances(draws,transforms).length,4);assert.equal(transforms[15],10);
});
test('a mismatched GLB or invalid partial fence mask fails closed',()=>{
 const draws=[{id:0,name:'city-0',vertexCount:20}];const data={format:'nuray-merged-visibility-v1',headerSha256:'header',draws:[{id:0,name:'city-0',fenceVertexRanges:[[2,3],[10,2]]}]};
 assert.equal(validateVisibility(data,'header',draws).size,1);
 assert.throws(()=>validateVisibility(data,'other',draws),/GLB/);
 for(const ranges of [[[19,2]],[[2,4],[3,2]],[[0,-1]]])assert.throws(()=>validateVisibility({...data,draws:[{...data.draws[0],fenceVertexRanges:ranges}]},'header',draws),/диапазон/);
});
