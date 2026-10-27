import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {lookAt,perspective,multiply} from '../src/district/math.js';
import {WaterHeights,reflectedView,reflectedEye,reflectionSize,reflectionKey,reflectionChunks} from '../src/district/ocean/planar-math.js';
import {cleanWaterSettings} from '../src/district/ocean/settings.js';
import {withCityOcean} from '../src/district/ocean/city-shader.js';
import {captureFragment} from '../prototype/tiles/webgl-shaders.js';
const project=(m,p)=>[0,1,2,3].map(i=>m[i]*p[0]+m[i+4]*p[1]+m[i+8]*p[2]+m[i+12]);
test('mirrored view fixes water points and exactly mirrors objects about the chosen water elevation',()=>{
 const h=-18.4,v=multiply(perspective(.7,1.6,1,10000,true),lookAt([24,65,190],[0,0,0])),m=reflectedView(v,h);
 for(const p of [[30,h,20],[7,40,-25]]){
  const a=project(m,p),b=project(v,[p[0],2*h-p[1],p[2]]);a.forEach((x,i)=>assert.ok(Math.abs(x-b[i])<.0001));
 }
 assert.deepEqual(reflectedEye([20,32,40],h),[20,2*h-32,40]);
});
test('water height index ignores solids, shared models, duplicate loads and offscreen surfaces',()=>{
 const index=new WaterHeights(),materials=[{kind:0},{kind:12}],bytes=new ArrayBuffer(32*4),f=new Float32Array(bytes),u=new Uint32Array(bytes);
 [[0,.4,0,1],[.5,.6,0,0],[20,7,0,1],[.5,.6,0,1]].forEach(([x,y,z,m],i)=>{f.set([x,y,z],i*8);u[i*8+6]=0x80000000|m;});
 index.add('tree',bytes,materials,true);assert.equal(index.cells.size,0);
 index.add('tile',bytes,materials);index.add('tile',bytes,materials);assert.equal(index.cells.get('0,0')[3],2);
 const identity=new Float32Array([1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1]);
 assert.ok(Math.abs(index.height([0,0,0],identity)-.5)<1e-6);
 assert.equal(index.height([20,7,0],identity),index.lastHeight);
});
test('cached reflection is independent of wave playback, blur and intensity but follows light and visibility',()=>{
 const o={camera:{target:[1,2,3]},sun:[1,1,1],sceneLayers:{vegetation:true},state:{textures:true,shadows:true},stats:{geometryBytes:64},chunks:[],waterHeights:{version:1},waterSettings:cleanWaterSettings()};
 const key=()=>reflectionKey(o,-4,[512,256]),a=key();
 Object.assign(o.waterSettings,{animated:true,reflectionBlur:8,reflectionStrength:33,reflectionDistortion:2,windSpeed:20});assert.equal(key(),a);
 o.sceneLayers.vegetation=false;assert.notEqual(key(),a);const b=key();o.waterSettings.sunIntensity=55;assert.notEqual(key(),b);
});
test('reflection dimensions cap allocation and clean settings reject nonfinite inputs',()=>{
 assert.deepEqual(reflectionSize(3840,2160,100),[1536,864]);assert.deepEqual(reflectionSize(1280,720,25),[320,180]);
 const p=cleanWaterSettings({reflectionEnabled:true,reflectionQuality:999,reflectionStrength:-10,reflectionBlur:NaN,reflectionDetail:'yes'});
 assert.equal(p.reflectionEnabled,true);assert.equal(p.reflectionQuality,100);assert.equal(p.reflectionStrength,0);assert.equal(p.reflectionBlur,1);assert.equal(p.reflectionDetail,true);
});
test('capture shaders exclude water and return linear radiance without recursively sampling their own target',()=>{
 const source=readFileSync(new URL('../src/district/district.wgsl',import.meta.url),'utf8'),plain=withCityOcean(source),s=withCityOcean(source,{planar:true}),capture=s.slice(s.indexOf('@fragment fn captureFragment'));
 assert.ok(!plain.includes('@group(2)'));assert.match(s,/let refl = sceneReflection/);
 assert.match(capture,/v.world.y<frame.display.w/);assert.match(capture,/return vec4f\(light,1\)/);assert.ok(!/oceanShade|sceneReflection|lightingOutput/.test(capture));
 assert.ok(!/reflectionMap|sceneReflection/.test(captureFragment));assert.match(captureFragment,/if\(int\(physical.z\)==12\)discard/);assert.match(captureFragment,/return vec4\(light\/8.,1\)/);
});
test('hidden scene layers and optional small instances are omitted from the mirrored pass',()=>{
 const bounds={min:[-.5,.2,.1],max:[.5,.8,.5]},a={bounds,id:'building',instanceCount:1},b={...a,id:'tree',instanceCount:20},c={...a,id:'hidden'};
 const o={chunks:[a,b,c],isChunkVisible:c=>c.id!=='hidden',waterSettings:{reflectionDetail:false}},identity=new Float32Array([1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1]);
 assert.deepEqual(reflectionChunks(o,identity,0),[a]);o.waterSettings.reflectionDetail=true;assert.deepEqual(reflectionChunks(o,identity,0),[a,b]);
});
