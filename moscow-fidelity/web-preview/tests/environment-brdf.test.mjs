import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {environmentReflectance,ENVIRONMENT_BRDF_WGSL,ENVIRONMENT_BRDF_GLSL} from '../src/district/environment-brdf.js';
import {isDryGround,groundMaterialRole} from '../src/district/ground-surfaces.js';
import {GROUND_COAT_WGSL,GROUND_COAT_GLSL} from '../src/district/ocean/planar-shader.js';
test('rough ground retains weak environment reflection at grazing angles, while smooth Fresnel remains',()=>{
 const legacy=(c,r)=>(.04+.96*(1-c)**5)*(1-.6*r);
 for(const rough of [.84,.88,.91,.93,.96,.98])for(const noV of [0,.02,.08,.2]){
  const value=environmentReflectance(noV,rough);
  assert.ok(value>0&&value<.04,`r=${rough} NoV=${noV}: ${value}`);
  assert.ok(value<legacy(noV,rough)*.25);
 }
 assert.ok(Math.abs(environmentReflectance(1,0)-.04)<.006);
 assert.ok(environmentReflectance(0,0)>.95);
 // Published fully rough limit of the integrated GGX fit, independent of angle.
 for(const noV of [0,.5,1])assert.ok(Math.abs(environmentReflectance(noV,1)-(.04*.4524-.0024))<1e-10);
 for(let r=0;r<=1;r+=.05)for(let v=0;v<=1;v+=.05){
  const f=environmentReflectance(v,r);assert.ok(Number.isFinite(f)&&f>=0&&f<=1);
 }
});
test('semantic ground role covers roads, paving and green areas, excludes water, buildings and props',()=>{
 const ground=['Асфальт','Территория / покрытие','Пешеходное покрытие','Газон','green-cover',
  'parking-asphalt','pedestrian-asphalt','pedestrian-stone','pedestrian-gravel','pedestrian-sand','pedestrian-wood',
  'Кладбище · зелёное покрытие','Неопределённая территория','Площадка · теннис'];
 for(const family of ground){
  const m={kind:1,family,metallic:0};assert.equal(isDryGround(m),true,family);
  assert.ok(groundMaterialRole(m)<-.5);assert.equal(isDryGround({...m,kind:12}),false);
  assert.equal(isDryGround({...m,metallic:.8}),false);
 }
 for(const family of ['Вода','street','vegetation','Buildings','Detailed_2GIS_models','generated-facade-storeys','pitched-roof','recessed-flat-roof']){
  assert.equal(groundMaterialRole({kind:1,family,metallic:0}),0,family);
 }
 assert.equal(groundMaterialRole({kind:1,family:'Пешеходное покрытие'}),-1);
 assert.equal(groundMaterialRole({kind:1,family:'Газон'}),-2);
});
test('both raster backends opt in only ground; the optional reflective finish remains beige-only',()=>{
 const source=p=>readFileSync(new URL(p,import.meta.url),'utf8');
 const gpu=source('../src/district/district.wgsl'),gl=source('../prototype/tiles/webgl-shaders.js');
 assert.match(gpu,/if m.scale.z<-.5 \{environmentWeight=environmentBRDF/);
 assert.match(gl,/if\(info.y<-.5\)environmentWeight=environmentBRDF/);
 assert.match(gl,/int\(physical.z\)==12\?vec3\(waterFresnel\(nv\)\)/);
 for(const shader of [ENVIRONMENT_BRDF_WGSL,ENVIRONMENT_BRDF_GLSL])assert.doesNotMatch(shader,/water|shore|sun/i);
 assert.match(GROUND_COAT_WGSL,/m.scale.z> -1.5/);assert.match(GROUND_COAT_GLSL,/info.y> -1.5/);
});
