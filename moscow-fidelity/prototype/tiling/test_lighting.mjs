import assert from 'node:assert/strict';
import {sunCascades,inverseMatrix,shadowUniform} from '../../web-preview/src/district/sun-shadows.js';
import {normalize,multiply,perspective,lookAt} from '../../web-preview/src/district/math.js';
import {facadePixels} from '../../web-preview/src/district/facade-relief.js';
const owner={sceneName:'moscow',city:{extentMetres:10000},sun:normalize([-.62,1,.45]),camera:{distance:159,target:[627,8,277]}};
const maps=sunCascades(owner);assert.equal(maps.length,3);assert.equal(shadowUniform(maps,2048).length,64);
assert(maps[0].params[0]<.15);assert(maps[0].params[1]*2000<.15);
function project(m,p){return [0,1,2,3].map(i=>m[i]*p[0]+m[i+4]*p[1]+m[i+8]*p[2]+m[i+12]);}
for(const c of maps){const q=project(c.matrix,owner.camera.target);assert(Math.max(Math.abs(q[0]),Math.abs(q[1]))<1);assert(q[2]>0&&q[2]<1);}
const tiny=sunCascades({...owner,camera:{...owner.camera,target:[627.001,8,277]}});assert.equal(tiny[0].key,maps[0].key);
const moved=sunCascades({...owner,camera:{...owner.camera,target:[800,8,277]}});assert.notEqual(moved[0].key,maps[0].key);assert.equal(moved[2].key,maps[2].key);
const large=sunCascades({...owner,city:{extentMetres:20000}});assert.equal(large[0].params[0],maps[0].params[0]);
for(const reverse of [false,true]){
 const m=multiply(perspective(.8,1.3,1,60000,reverse),lookAt([700,120,300],[627,8,277])),inv=inverseMatrix(m,[700,120,300]),product=multiply(inv,m);
 product.forEach((v,i)=>assert(Math.abs(v-(i>=12&&i<15?-[700,120,300][i-12]:i%5===0?1:0))<.002));
}
const albedo=facadePixels(),normal=facadePixels(8,512,true),middle=(256*8)*4;
assert(albedo[0]<80);assert.equal(albedo[middle],255);assert.equal(albedo[0],albedo.at(-4));
assert(normal[4*8*4+1]<128);assert(normal[(507*8)*4+1]>128);assert.equal(normal[middle+2],255);
console.log('Lighting passed: metric shadow bias, near-detail independent of city extent, stable clipmaps, far cache, inverse projections, periodic recessed joints.');
