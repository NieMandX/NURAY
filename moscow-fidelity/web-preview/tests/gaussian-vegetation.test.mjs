import test from 'node:test';
import assert from 'node:assert/strict';
import {selectPlants,sortedPairs,transformPoint,compactMeshInstances,plantBounds,replacementSet} from '../src/district/gaussian/model.js';
import {multiply,lookAt,perspective} from '../src/district/math.js';
const matrix=multiply(perspective(Math.PI/3,1,1,1000,true),lookAt([0,5,30],[0,5,0]));
const identity=[1,0,0,0,0,1,0,0,0,0,1,0];
const model={offset:0,bounds:{min:[-2,0,-2],max:[2,10,2]},levels:[1000,500,200,50,10].map(count=>({offset:0,count}))};
test('visible plants obey projected LOD and a hard Gaussian budget',()=>{
  const instances=Array.from({length:20},(_,i)=>({model:0,matrix:identity.map((v,j)=>j===3?(i-10)*.1:v)}));
  const selected=selectPlants(instances,[model],matrix,1000,1000,250);
  assert.equal(selected.length,instances.length);assert.ok(selected.reduce((n,x)=>n+x.count,0)<=250);
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

test('crowns crossing the camera plane stay selected instead of returning to meshes',()=>{
  const close={model:0,matrix:identity.map((v,j)=>j===11?29.8:v)};
  assert.equal(selectPlants([close],[model],matrix,1000,1000,350000,[0,5,30]).length,1);
});
test('turning the camera retains detail for common plants and keeps every splat replacement ready',()=>{
  const models=[{...model,levels:[1000,500,200,50,10,1].map(count=>({offset:0,count}))}];
  const instances=Array.from({length:150},(_,i)=>({model:0,sourceInstance:i+10,matrix:identity.map((v,j)=>j===3?(i%15-7)*3:j===11?-Math.floor(i/15)*9:v)}));
  const eye=[0,5,30],a=multiply(perspective(Math.PI/3,1,1,1000,true),lookAt(eye,[0,5,0]));
  const b=multiply(perspective(Math.PI/3,1,1,1000,true),lookAt(eye,[12,5,0]));
  const bounds=plantBounds(instances,models),left=selectPlants(instances,models,a,1000,1000,5000,eye,bounds,true),right=selectPlants(instances,models,b,1000,1000,5000,eye,bounds,true,left);
  const levels=new Map(left.filter(x=>x.visible).map(x=>[x.id,x.level]));let common=0;
  for(const x of right)if(x.visible&&levels.has(x.id)){assert.ok(x.level<=levels.get(x.id));common++;}
  assert.equal(right.length,instances.length);
  assert.ok(common>50);assert.ok(left.reduce((n,x)=>n+x.count,0)<=5000);assert.ok(right.reduce((n,x)=>n+x.count,0)<=5000);
  assert.throws(()=>selectPlants(instances,models,a,1000,1000,100,eye,bounds),/cannot cover every plant/);
});

test('whole-scene render list keeps offscreen splats ready during rapid rotation',()=>{
  const instances=[{model:0,matrix:identity},{model:0,matrix:identity.map((v,j)=>j===11?100:v)}];
  const selected=selectPlants(instances,[model],matrix,1000,1000,350000,[0,5,30],plantBounds(instances,[model]),true);
  assert.equal(selected.length,2);assert.equal(selected.filter(x=>x.visible).length,1);
});
test('complete replacement coverage excludes every polygonal plant and rejects partial/duplicate catalogs',()=>{
  const chunks=[{id:7,name:'nuray-approved-open',instanced:true,instanceFirst:4,instanceCount:2},{id:8,name:'street-lamp',instanced:true,instanceFirst:6,instanceCount:1}];
  const instances=[4,5].map(sourceInstance=>({sourceInstance,sourceDraw:7,sourceType:'nuray-approved-open',model:0,matrix:identity}));
  const manifest={scope:{fullScene:true},instances};
  assert.deepEqual([...replacementSet(manifest,chunks,[model])],[4,5]);
  assert.throws(()=>replacementSet({...manifest,instances:instances.slice(0,1)},chunks,[model]),/every plant/);
  assert.throws(()=>replacementSet({...manifest,instances:[instances[0],instances[0]]},chunks,[model]),/duplicate/);
});

const detailedModel={...model,levels:[32768,8192,2048,512,128,32,8,1].map(count=>({offset:0,count}))};
test('near crowns can reach the full source resolution instead of the old 8192 cap',()=>{
  const eye=[0,5,12],vp=multiply(perspective(Math.PI/3,1,.3,20000,true),lookAt(eye,[0,5,0]));
  const chosen=selectPlants([{model:0,matrix:identity}],[detailedModel],vp,1000,1000,350000,eye);
  assert.equal(chosen[0].count,32768);
});
test('crowded zoom-in never downgrades an approaching visible crown under the same budget',()=>{
  const instances=Array.from({length:1000},(_,i)=>({model:0,matrix:identity.map((v,j)=>j===3?(i%25-12)*7:j===11?-Math.floor(i/25)*9:v)}));
  const models=[detailedModel],bounds=plantBounds(instances,models);let previous=null,comparisons=0;
  for(const d of [1600,1000,600,400,200,100,50,25]){
    const eye=[0,5,d],vp=multiply(perspective(Math.PI/3,1,.3,20000,true),lookAt(eye,[0,5,0]));
    const next=selectPlants(instances,models,vp,1000,1000,50000,eye,bounds,true,previous);
    assert.equal(next.length,instances.length);assert.ok(next.reduce((n,x)=>n+x.count,0)<=50000);
    if(previous)for(const x of next){const old=previous[x.id];if(x.visible&&old.visible&&x.size>=old.size){assert.ok(x.count>=old.count);comparisons++;}}
    previous=next;
  }
  assert.ok(comparisons>1000);
});
test('many small zoom-out steps release fine LODs rather than ratcheting detail forever',()=>{
  const instances=[{model:0,matrix:identity}],models=[detailedModel],bounds=plantBounds(instances,models);let previous=null,first,last;
  for(let d=12;d<12000;d*=1.01){
    const eye=[0,5,d],vp=multiply(perspective(Math.PI/3,1,.3,20000,true),lookAt(eye,[0,5,0]));
    previous=selectPlants(instances,models,vp,1000,1000,350000,eye,bounds,true,previous);
    first??=previous[0].count;last=previous[0].count;
  }
  assert.equal(first,32768);assert.equal(last,1);
});
