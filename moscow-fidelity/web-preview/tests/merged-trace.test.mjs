import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {planMergedTrace,mergedInstances} from '../prototype/tiles/merged-trace.js';
import {traceScene} from '../prototype/tiles/tile-scene.js';
const path=new URL('../prototype/tiles/assets-spb-10km-live-20261024-r13/merged/',import.meta.url);
test('whole GLB accelerator covers every full-resolution mesh and fits four arenas',()=>{
  const meta=JSON.parse(readFileSync(new URL('metadata.json',path))),manifest=JSON.parse(readFileSync(new URL('trace/manifest.json',path)));
  const plan=planMergedTrace(meta.draws,manifest,1024**3);
  assert.equal(plan.descriptors.size,meta.draws.length);assert.equal(plan.sizes.length,4);
  assert.equal(plan.sizes.reduce((a,b)=>a+b,0),manifest.geometryBytes+manifest.nodeBytes);
  assert.equal(manifest.draws.reduce((a,b)=>a+b.triangles,0),meta.stats.uniqueTriangles);
  assert.equal(meta.stats.uniqueTriangles,41126698);
  for(let p=0;p<4;p++){
    const spans=manifest.draws.filter(d=>plan.descriptors.get(d.id).page===p).map(d=>{const x=plan.descriptors.get(d.id);return [x.vertex*4,(x.nodes+d.nodeCount*8)*4];}).sort((a,b)=>a[0]-b[0]);
    assert.equal(spans[0][0],0);assert.equal(spans.at(-1)[1],plan.sizes[p]);
    for(let i=1;i<spans.length;i++)assert.equal(spans[i-1][1],spans[i][0]);
  }
  assert.throws(()=>planMergedTrace(meta.draws,manifest,256*1024**2),/не помещается/);
  assert.throws(()=>planMergedTrace(meta.draws,{...manifest,draws:manifest.draws.slice(1)},1024**3),/Неполный/);
});
test('shared instance bounds are transformed from local geometry exactly once',()=>{
  const draws=[{id:9,instanceFirst:1,instanceCount:2}],transforms=Float32Array.from([1,0,0,0,0,1,0,0,0,0,1,0, 2,0,0,10,0,3,0,2,0,0,2,-4, 1,0,0,-100,0,1,0,0,0,0,1,0]);
  const instances=mergedInstances(draws,transforms);assert.equal(instances.length,2);
  const scene=traceScene(instances,new Map([[9,{bounds:{min:[-1,0,-1],max:[1,4,1]}}]]),new Map([[9,{page:0,vertex:0,index:32,nodes:40,nodeCount:1}]]));
  const u=new Uint32Array(scene),f=new Float32Array(scene);
  assert.equal(u[2],2);assert.equal(u[3],20);assert.ok(f[4]<-100.9);assert.ok(f[8]>11.9);assert.ok(f[9]>13.9);
  assert.throws(()=>mergedInstances(draws,transforms.subarray(0,24)),/диапазон/);
});
