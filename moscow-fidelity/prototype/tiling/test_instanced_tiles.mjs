import assert from 'node:assert/strict';
import {planGpuPages} from '../../web-preview/prototype/tiles/gpu-pages.js';
import {activeChunkIds,pageChunkIds,sceneInstances,rasterLayout,traceScene} from '../../web-preview/prototype/tiles/tile-scene.js';
const mesh=(id,instanced=false)=>({id,instanced,vertexBytes:96,indexBytes:12,nodeBytes:32,nodeCount:1,triangles:1,bounds:{min:[-3,0,-3],max:[3,10,3]}});
const chunks=[mesh('left'),mesh('right'),mesh('paint'),mesh('tree',true)],assets=new Map(chunks.map(c=>[c.id,c]));
const matrix=[0,0,2,249,0,3,0,7,-2,0,0,20];
const tree={id:'plant:boundary',mesh:'tree',matrix,tileId:'left'};
const tiles=[{id:'left',chunks:['left','paint'],coarseChunks:['left'],instances:[tree]},{id:'right',chunks:['right'],coarseChunks:['right'],instances:[{id:'plant:other',mesh:'tree',matrix:[1,0,0,260,0,1,0,1,0,0,1,5],tileId:'right'}]}];
const scene={tiles,chunks},modes=new Map([['left','full'],['right','coarse']]),plan=planGpuPages(scene,500);
const ids=plan.flatMap(p=>pageChunkIds(p,scene,modes));assert.equal(ids.filter(x=>x==='tree').length,1);assert.equal(new Set(ids).size,4);
assert.equal(activeChunkIds(scene,modes).size,4);
const instances=sceneInstances(scene,modes);assert.equal(instances.filter(i=>i.mesh==='tree').length,2);
const layout=rasterLayout(instances,assets),draw=layout.draws.find(x=>x.id==='tree');assert.equal(draw.instanceCount,2);
assert(draw.bounds.max[0]>250,'A canopy beyond its owner tile remains visible');
const descriptors=new Map(ids.map((id,i)=>[id,{page:0,vertex:i*100,index:i*100+24,nodes:i*100+27,nodeCount:1}]));
const buffer=traceScene(instances,assets,descriptors),u=new Uint32Array(buffer),f=new Float32Array(buffer);assert.equal(u[3],20);assert.equal(u[2],5);
// Verify inverse instance rows inside the serialized shader descriptor, rather
// than merely checking the source matrix helper in isolation.
const o=u[1],treeDescriptors=[];
for(let i=0;i<u[2];i++){const k=o+i*20;if(u[k+1]===descriptors.get('tree').vertex)treeDescriptors.push([...f.slice(k+8,k+20)]);}
assert.equal(treeDescriptors.length,2);
const inverse=treeDescriptors.find(m=>Math.abs(m[3]-10)<1e-5);assert(inverse);
const local=[1,2,3],world=[255,13,18];
for(let a=0;a<3;a++)assert(Math.abs(inverse[a*4]*world[0]+inverse[a*4+1]*world[1]+inverse[a*4+2]*world[2]+inverse[a*4+3]-local[a])<1e-5);
const coarse=new Map([['left','coarse'],['right','coarse']]);assert(!activeChunkIds(scene,coarse).has('paint'));assert(activeChunkIds(scene,coarse).has('tree'));
assert.deepEqual(planGpuPages({...scene,tiles:[...tiles].reverse()},500),plan);
const selected=new Map([['left','coarse']]);
assert.deepEqual([...activeChunkIds(scene,selected)],['left','tree']);
assert.equal(sceneInstances(scene,selected).length,2);
assert.equal(planGpuPages(scene,200,4,selected).reduce((s,p)=>s+p.bytes,0),280);
assert.deepEqual(plan.flatMap(p=>pageChunkIds(p,scene,selected)).sort(),['left','tree']);
console.log('Passed: one shared BLAS per template, whole crowns across tiles, raster instancing, serialized TLAS transforms, and coarse/full reuse.');
