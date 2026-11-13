import test from 'node:test';
import assert from 'node:assert/strict';
import {selectPlants,sortedPairs,transformPoint,compactMeshInstances} from '../src/district/gaussian/model.js';
import {multiply,lookAt,perspective} from '../src/district/math.js';
const matrix=multiply(perspective(Math.PI/3,1,1,1000,true),lookAt([0,5,30],[0,5,0]));
const identity=[1,0,0,0,0,1,0,0,0,0,1,0];
const model={offset:0,bounds:{min:[-2,0,-2],max:[2,10,2]},levels:[1000,500,200,50,10].map(count=>({offset:0,count}))};
test('visible plants obey projected LOD and a hard Gaussian budget',()=>{
  const instances=Array.from({length:20},(_,i)=>({model:0,matrix:identity.map((v,j)=>j===3?(i-10)*.1:v)}));
  const selected=selectPlants(instances,[model],matrix,1000,1000,73);
  assert.ok(selected.length>0);assert.ok(selected.reduce((n,x)=>n+x.count,0)<=73);
  const behind={model:0,matrix:identity.map((v,j)=>j===11?100:v)};
  const outside={model:0,matrix:identity.map((v,j)=>j===3?10000:v)};
  assert.deepEqual(selectPlants([behind,outside],[model],matrix,1000,1000),[]);
});
test('depth sort spans overlapping instances, not just whole tree centres',()=>{
  const points=new Float32Array(32);points.set([0,0,-2],0);points.set([0,0,2],16);
  const instances=[{model:0,matrix:identity},{model:0,matrix:identity.map((v,j)=>j===11?1:v)}];
  const models=[{offset:0,levels:[{offset:0,count:2}]}];
  const pairs=sortedPairs([{id:0,level:0,count:2},{id:1,level:0,count:2}],instances,models,points,matrix);
  assert.deepEqual([...pairs],[0,0,0,1,1,0,1,1]);
});
test('instance transform keeps surveyed root and non-uniform scale',()=>{
  assert.deepEqual(transformPoint([2,0,0,100,0,5,0,17,0,0,2,-60],[0,0,0]),[100,17,-60]);
  assert.deepEqual(transformPoint([2,0,0,100,0,5,0,17,0,0,2,-60],[1,2,3]),[102,27,-54]);
});
test('main-pass compaction keeps one draw per type and never edits shadow transforms',()=>{
  const chunks=[{id:0,instanceFirst:0,instanceCount:1,instanced:false},{id:1,instanceFirst:1,instanceCount:5,instanced:true},{id:2,instanceFirst:6,instanceCount:3,instanced:true}];
  const source=Float32Array.from({length:9*12},(_,i)=>i+.25),before=source.slice();
  const {transforms,counts}=compactMeshInstances(chunks,source,new Set([1,3,5,7]));
  assert.deepEqual(source,before);
  assert.equal(counts.get(1),2);assert.equal(counts.get(2),2);assert.equal(counts.has(0),false);
  assert.deepEqual(transforms.subarray(0,12),source.subarray(0,12));
  for(const [dst,src] of [[1,2],[2,4],[6,6],[7,8]])assert.deepEqual(transforms.subarray(dst*12,dst*12+12),source.subarray(src*12,src*12+12));
  const empty=compactMeshInstances(chunks,source,new Set([6,7,8]));assert.equal(empty.counts.get(2),0);
  assert.deepEqual(compactMeshInstances(chunks,source,new Set()).transforms,source);
});
