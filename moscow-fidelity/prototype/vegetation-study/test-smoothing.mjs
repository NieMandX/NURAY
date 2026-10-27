import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {gunzipSync} from 'node:zlib';
import {packedNormal,exportGLB} from '../../web-preview/vegetation-study/foliage-editor.js';
import {normalizeAngle,decodePackedGeometry,smoothFoliage} from '../../web-preview/vegetation-study/foliage-smoothing.js';

function mesh(tris,materials){
  const positions=Float32Array.from(tris.flat(2)),normals=new Float32Array(positions.length),words=new Uint32Array(tris.length*3*8),floats=new Float32Array(words.buffer);
  tris.forEach(([a,b,c],t)=>{
    const u=b.map((v,i)=>v-a[i]),v=c.map((v,i)=>v-a[i]);
    const n=[u[1]*v[2]-u[2]*v[1],u[2]*v[0]-u[0]*v[2],u[0]*v[1]-u[1]*v[0]],d=Math.hypot(...n),normal=n.map(v=>v/d);
    for(let k=0;k<3;k++){const i=t*3+k;normals.set(normal,i*3);words[i*8+3]=packedNormal(normal);floats.set(tris[t][k],i*8);words[i*8+6]=(0x80000000|materials[t])>>>0;}
  });
  return {positions,normals,words,materials,vertexCount:tris.length*3,triangles:tris.length};
}
const hinge=[[[0,0,0],[1,0,0],[0,1,0]],[[1,0,0],[0,0,0],[0,0,1]]];
const source=mesh(hinge,[0,2]);
assert.deepEqual(smoothFoliage(source,0).words,source.words);
assert.deepEqual(smoothFoliage(source,89).words,source.words);
const rounded=smoothFoliage(source,90),diagonal=[0,Math.SQRT1_2,Math.SQRT1_2];
for(const corner of [0,1,3,4])for(let j=0;j<3;j++)assert(Math.abs(rounded.normals[corner*3+j]-diagonal[j])<1e-6);
assert.deepEqual(rounded.materials,source.materials,'Color boundaries must retain their materials');
for(const corner of [2,5])assert.deepEqual(rounded.normals.slice(corner*3,corner*3+3),source.normals.slice(corner*3,corner*3+3));
const mixed=mesh(hinge,[0,4]);assert.deepEqual(smoothFoliage(mixed,180).words,mixed.words,'Never smooth into wood');
const pointContact=mesh([hinge[0],[[0,0,0],[-1,0,0],[0,0,-1]]],[0,0]);
assert.deepEqual(smoothFoliage(pointContact,180).words,pointContact.words,'Point contact is not an edge');
const nonManifold=mesh([...hinge,[[0,0,0],[1,0,0],[0,-1,0]]],[0,0,0]);
assert.deepEqual(smoothFoliage(nonManifold,180).words,nonManifold.words,'Non-manifold shared edges stay hard');
assert.equal(normalizeAngle(-1),0);assert.equal(normalizeAngle(190),180);assert.equal(normalizeAngle(NaN),0);

const folder=new URL('../../web-preview/vegetation-study/assets/open-approved-01/',import.meta.url);
const scene=JSON.parse(readFileSync(new URL('scene.json',folder))),chunk=scene.chunks[0];
const data=Uint8Array.from(gunzipSync(readFileSync(new URL(chunk.file,folder))));
const base=decodePackedGeometry(data.buffer,chunk),original=base.words.slice();
const packed=new Uint32Array(data.buffer,0,chunk.vertexBytes/4),ix=new Uint32Array(data.buffer,chunk.vertexBytes);
for(let i=0;i<ix.length;i++)assert.deepEqual(base.words.slice(i*8,i*8+8),packed.slice(ix[i]*8,ix[i]*8+8));
assert.equal(base.triangles,684);assert.equal(base.foliageTriangles,372);assert.equal(base.woodTriangles,312);
let changed=0;
for(const angle of [0,1,30,60,90,180]){
  const result=smoothFoliage(base,angle);
  assert.deepEqual(result.positions,base.positions);assert.deepEqual(result.materials,base.materials);
  assert.equal(result.triangles,base.triangles);assert.deepEqual(result.bounds,base.bounds);
  for(let i=0;i<result.vertexCount;i++){
    assert(Math.abs(Math.hypot(...result.normals.slice(i*3,i*3+3))-1)<1e-6);
    for(let w=0;w<8;w++)if(w!==3||base.materials[Math.floor(i/3)]>=4)assert.equal(result.words[i*8+w],base.words[i*8+w]);
    if(angle===180&&result.words[i*8+3]!==base.words[i*8+3])changed++;
  }
}
assert(changed>100,'The full smoothing setting must visibly affect the actual crown');
assert.deepEqual(base.words,original,'Always start from immutable original normals');
assert.deepEqual(smoothFoliage(base,0).words,original,'0° restores exact original words');
const result=smoothFoliage(base,180),glb=exportGLB(result,scene.materials),dv=new DataView(glb);
const jsonLength=dv.getUint32(12,true),doc=JSON.parse(new TextDecoder().decode(new Uint8Array(glb,20,jsonLength)));
assert.equal(doc.extras.foliageSmoothingAngle,180);
for(const [attribute,expected] of [['NORMAL',result.normals],['POSITION',base.positions]]){
  const a=doc.accessors[doc.meshes[0].primitives[0].attributes[attribute]],v=doc.bufferViews[a.bufferView];
  assert.deepEqual(new Float32Array(glb,28+jsonLength+v.byteOffset,a.count*3),expected);
}
console.log(`PASS: 90° crease threshold, connected fans, point/non-manifold isolation, wood unchanged, exact 0° reset, original geometry/materials, GLB normals; ${changed} foliage corners smoothed at 180°.`);
