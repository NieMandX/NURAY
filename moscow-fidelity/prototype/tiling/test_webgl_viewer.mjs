import assert from 'node:assert/strict';
import {budgetTiles,overviewDistance} from '../../web-preview/prototype/tiles/webgl-budget.js';
import {bindCameraInput} from '../../web-preview/prototype/tiles/camera-input.js';
const chunks=['a','b','paint','tree'].map(id=>({id,vertexBytes:80,indexBytes:20}));
const tile=(id,x)=>({id,chunks:[id,'paint'],coarseChunks:[id],instances:[{mesh:'tree'},{mesh:'tree'}],fullTriangles:400,coarseTriangles:300,bounds:{min:[x,0,0],max:[x+1,1,1]}});
const scene={chunks,tiles:[tile('a',0),tile('b',10)]},request=new Map([['b','full'],['a','full']]);
// Both full tiles cost 400 geometry bytes + 8 transforms * 48, regardless
// of shared vegetation appearing four times. Order follows the camera.
let result=budgetTiles(scene,request,[0,0,0],784,10);
assert.equal(result.bytes,784);assert.deepEqual([...result.modes],[['a','full'],['b','full']]);assert(!result.limited);
result=budgetTiles(scene,request,[0,0,0],600,10);
assert.equal(result.bytes,492);assert.deepEqual([...result.modes],[['a','full']]);assert(result.limited);
result=budgetTiles(scene,request,[0,0,0],350,10);
assert.deepEqual([...result.modes],[['a','coarse']]);assert.equal(result.bytes,344);
assert.equal(budgetTiles(scene,request,[10,0,0],784,1).modes.keys().next().value,'b');
assert.equal(budgetTiles(scene,request,[0,0,0],1,10).modes.size,0);
// Geometry can fit memory while repeated plants exceed raster throughput.
result=budgetTiles(scene,request,[0,0,0],10000,10,700);
assert.deepEqual([...result.modes],[['a','full'],['b','coarse']]);assert.equal(result.triangles,700);assert(result.limited);
result=budgetTiles(scene,request,[0,0,0],10000,10,600);
assert.deepEqual([...result.modes],[['a','full']]);assert.equal(result.triangles,400);
// Preserve the nearest heavy tile, but never waive the actual memory cap.
result=budgetTiles(scene,request,[0,0,0],10000,10,100);
assert.deepEqual([...result.modes],[['a','full']]);assert(result.limited);
assert.equal(budgetTiles(scene,request,[0,0,0],1,10,100).modes.size,0);
assert.equal(overviewDistance(18000,()=>true),18000);
assert.equal(overviewDistance(18000,()=>false),400);
assert.equal(overviewDistance(300,()=>false),300);
const fitted=overviewDistance(18000,d=>d<=725);
assert(fitted<=725&&fitted>720);
// Real handler lifecycle, including one -> two -> one fingers. No jump when
// a pointer is added/removed; a cancelled contact cannot move the camera.
const c={yaw:0,pitch:.7,distance:100,target:[0,0,0]},r={camera:c,tileset:{extentMetres:10000}};
const canvas={setPointerCapture(){},addEventListener(name,callback){this[name]=callback;}};let moves=0;
bindCameraInput(canvas,()=>r,()=>true,()=>moves++);
const e=(id,x,y)=>({pointerId:id,clientX:x,clientY:y,buttons:1});
canvas.onpointerdown(e(1,100,100));canvas.onpointermove(e(1,110,100));assert.equal(c.yaw,-.06);
canvas.onpointerdown(e(2,210,100));const yaw=c.yaw;
canvas.onpointermove(e(2,310,100));assert.equal(c.distance,50);assert.equal(c.yaw,yaw);assert.notEqual(c.target[0],0);
canvas.onpointerup(e(2,310,100));canvas.onpointermove(e(1,120,100));assert.equal(c.yaw,-.12);
canvas.onpointercancel(e(1,120,100));const count=moves;canvas.onpointermove(e(1,200,200));assert.equal(moves,count);
canvas.wheel({preventDefault(){},deltaY:1e8});assert.equal(c.distance,23000);
canvas.wheel({preventDefault(){},deltaY:-1e8});assert.equal(c.distance,8);
console.log('Passed: bounded WebGL residency, shared geometry accounting, detail fallback, deterministic priority, pinch/pan/orbit transitions and gesture cancellation.');
