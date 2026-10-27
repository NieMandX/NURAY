import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createHosek,skyRadiance,solarRadiance,hosekUniforms,HosekCache,SUN_RADIUS} from '../src/district/hosek/model.js';
import {WATER_DEFAULTS} from '../src/district/ocean/settings.js';
const reference=readFileSync(new URL('fixtures/hosek-reference.jsonl',import.meta.url),'utf8').trim().split('\n').map(JSON.parse);
test('RGB sky and spectral sun agree with original compiled C model at fit boundaries and interpolated parameters',()=>{
 for(const [t,a,e,...expected] of reference){
  const model=createHosek(t,a,e),actual=[...skyRadiance(model,.71,1.12),...[400,480,560,640,720].map(w=>solarRadiance(model,w,.002))];
  actual.forEach((v,i)=>assert.ok(Math.abs(v-expected[i])<=1e-10*Math.max(1,Math.abs(expected[i])),`${t}/${a}/${e} channel ${i}`));
 }
});
test('Horizon, zenith, clear sky and haze produce finite GPU uniforms; sun vanishes outside its disc',()=>{
 for(const e of [-Math.PI/12,0,.001,.4,Math.PI/2])for(const t of [1,10])for(const a of [0,1]){
  const values=hosekUniforms([Math.cos(e),Math.sin(e),0],{...WATER_DEFAULTS,hwTurbidity:t,hwAlbedo:a});
  assert.equal(values.byteLength,448);assert.ok([...values].every(Number.isFinite));
  assert.ok(values.slice(76,79).every(x=>x>=0));
  if(e<-.1)assert.ok(values.slice(76,79).every(x=>x===0));
 }
 assert.equal(solarRadiance(createHosek(),560,SUN_RADIUS*1.01),0);
});
test('Changing turbidity and albedo affects radiance; unchanged frames reuse cached coefficients',()=>{
 const sun=[0,.5,Math.sqrt(.75)],c=new HosekCache(),p={...WATER_DEFAULTS};
 const a=c.update(sun,p);assert.equal(c.update([...sun],{...p}),a);
 const b=c.update(sun,{...p,hwTurbidity:8});assert.notDeepEqual(a,b);
 const d=c.update(sun,{...p,hwAlbedo:1});assert.notDeepEqual(a.slice(36,76),d.slice(36,76));
});
