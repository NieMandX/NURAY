import {hosekWGSL} from '../hosek/shaders.js?v=moscow-defaults-1';
import {SEASCAPE_WGSL} from '../seascape/seascape-wgsl.js?v=shore-water-1';
import {OCEAN} from './vendor/ocean.js?v=moscow-defaults-1';
import {WATER_OPTICS_WGSL} from './optics.js?v=shore-water-1';
import {PLANAR_WGSL,GROUND_WGSL,GROUND_COAT_WGSL} from './planar-shader.js?v=dry-ground-1';
// Keep the upstream spectral BRDF; use our finite water footprints instead of
// the demonstration's infinite CDLOD ocean. All coordinates remain metres.
export function cityOceanShader(){
 let s=OCEAN.slice(0,OCEAN.indexOf('struct VSOut'))+OCEAN.slice(OCEAN.indexOf('fn fresnelWater'));
 s=s.replaceAll('@group(0)','@group(1)').replaceAll('Frame','OceanFrame');
 s=s.replace('@fragment fn fs(in: VSOut) -> @location(0) vec4f {',`fn oceanShade(world:vec3f, shore:f32, shadow:f32) -> vec4f {
  let rel=world-F.camPos.xyz;
  var height=0.0;
  for(var c=0u;c<6u;c++){height+=textureSampleLevel(dispTex,sampR,world.xz*F.cascInvL[c>>2u][c&3u],c,0.0).y;}`);
 s=s.replaceAll('in.xz','world.xz').replaceAll('in.rel','rel').replaceAll('in.height','height');
 s=s.replace(/fn fresnelWater\([\s\S]*?\n}/,'fn fresnelWater(c:f32)->f32 {return waterFresnel(c);}')
   .replace('F.waterCol.rgb * (skyHemi','waterBody(dot(nV,V)) * (skyHemi');
 s=s.replace('sunIlluminance() * sunVis[0]','waterSun() * shadow');
 // The wave spectrum is independent of the lighting model. Reflections and
 // foam use the same environment as the city in either mode.
 s=s.replace(/textureSampleLevel\(envCube, sampC, (vec3f\([^)]*\)|nrm|R), ([^)]*)\)\.rgb/g,'oceanEnvironment($1,($2)/8.0)');
 s=s.replace('col = col * T + fogCol * (1.0 - T);','if !classicLighting()&&!seascapeLighting() {col = col * T + fogCol * (1.0 - T);}');
 s=s.replace('let fwl = mix(fw1, fw0, w0) * w1;', 'let fwl = mix(fw1, fw0, w0) * w1 * min(F.foamP.z,1.0);');
 s=s.replace('var col = body',`foamMask *= min(F.foamP.z,1.0);
  let shorePattern=textureSample(foamTex,sampR,world.xz*.35+vec2f(F.camPos.w*.008,0)).r;
  let shoreCover=(1.0-smoothstep(.05,.65+shorePattern*.5,shore))*(.25+.3*shorePattern)*F.windP[1].x;
  foamMask=max(foamMask,shoreCover);
  var col = body`);
 return s+WATER_OPTICS_WGSL+SEASCAPE_WGSL+hosekWGSL(1,12)+`
 // One lighting evaluation, blended in linear space; endpoint grades remain exact.
 fn hosekLighting()->bool {return F.windP[1].y>3.5;}
 fn solarPower()->f32 {return select(frame.sun.w,1.0,hosekLighting());}
 fn classicLighting()->bool {return F.windP[1].y>.5&&F.windP[1].y<1.5;}
 fn seascapeLighting()->bool {return F.windP[1].y>1.5;}
 fn seaLightWeight()->f32 {if F.windP[1].y>2.5 {return F.viewProj[1].y;}return select(0.0,1.0,seascapeLighting());}
 fn lightingOutput(light:vec3f)->vec4f {
  if hosekLighting() {return vec4f(hwGrade(light),1);}
  if F.windP[1].y<.5 {return vec4f(light,1);}
  return vec4f(mix(srgb(toneMap(light*frame.display.x)),seaGrade(light,F.viewProj[1].x),seaLightWeight()),1);
 }
 fn sunVisibility(raw:f32)->f32 {return 1-(1-raw)*min(F.viewProj[2].x,1.0);}
 fn shadowFill(raw:f32)->f32 {return mix(mix(1.0,.35,clamp(F.viewProj[2].x-1,0,1)),1.0,raw);}
 fn waterSun()->vec3f {
  if hosekLighting() {return HW.p[19].rgb*F.viewProj[1].w;}
  if F.windP[1].y>.5 {return mix(vec3f(4.2,3.77,3.1),vec3f(2.5),seaLightWeight())*frame.sun.w*F.viewProj[1].w;}
  return sunIlluminance()*sunVis[0]*F.viewProj[1].w;
 }
 fn oceanSun()->vec3f {
  if hosekLighting() {return HW.p[19].rgb*F.viewProj[1].w;}
  if F.windP[1].y>.5 {return mix(vec3f(4.2,3.77,3.1),vec3f(2.5),seaLightWeight())*F.viewProj[1].w;}
  return sunIlluminance()*sunVis[0]*.42*F.viewProj[1].w;
 }
 fn oceanAmbient(n:vec3f)->vec3f {
  if hosekLighting() {return hwAmbient(n);}
  if F.windP[1].y>.5 {return mix(mix(vec3f(.17,.18,.20),vec3f(.45,.51,.58),n.y*.5+.5),seaSky(normalize(vec3f(n.x,max(n.y,.15),n.z)),frame.sun.xyz)*.55,seaLightWeight());}
  return textureSampleLevel(envCube,sampC,normalize(vec3f(n.x,max(n.y,.15),n.z)),8.0).rgb*.85;
 }
 fn oceanEnvironment(d:vec3f,r:f32)->vec3f {
  if hosekLighting() {return hwEnvironment(d,frame.sun.xyz,r);}
  if F.windP[1].y>.5 {return mix(classicSky(d,r),seaSky(d,frame.sun.xyz),seaLightWeight());}
  return textureSampleLevel(envCube,sampC,vec3f(d.x,abs(d.y),d.z),r*8.0).rgb;
 }
 `;
}
export function withCityOcean(source,{planar=false}={}){
 source=source.replace(/fn sky\([\s\S]*?\n}/,original=>original.replace('fn sky(', 'fn classicSky(')+`\nfn sky(d:vec3f,rough:f32)->vec3f {return oceanEnvironment(d,rough);}`);
 const start=source.indexOf('  if u32(m.physical.z)==12u {');
 const end=source.indexOf('  let wo=',start);
 source=source.slice(0,start)+`  if u32(m.physical.z)==12u {
   let rawShadow=visibility(v.world,geometricNormal);let sunShadow=sunVisibility(rawShadow);
   var water:vec4f;
   if F.windP[1].z>.5 {water=seascapeShade(v.world,surfaceDistance(v.world,false),sunShadow);}
   else {water=oceanShade(v.world,surfaceDistance(v.world,false),sunShadow);}
   return lightingOutput(water.rgb*shadowFill(rawShadow));
  }
  if m.scale.w>.5 {color*=1-roadWear(v.world);}
 `+source.slice(end);
 source=source.replaceAll('vec3f(4.2,3.77,3.1)','oceanSun()');
 source=source.replace('mix(vec3f(.17,.18,.20),vec3f(.45,.51,.58),n.y*.5+.5)','oceanAmbient(n)');
 source=source.replace('let shadow=visibility(v.world,geometricNormal);','let rawShadow=visibility(v.world,geometricNormal);let shadow=sunVisibility(rawShadow);');
 source=source.replace('light*=mix(1.0/1.4,1.0,shadow);','light*=mix(1.0/1.4,1.0,shadow)*shadowFill(rawShadow);');
 source=source.replace('mix(3.0,.12,rough)*frame.sun.w','mix(3.0,.12,rough)*frame.sun.w*F.viewProj[1].w');
 source=source.replace('return vec4f(srgb(toneMap(light*frame.display.x)),1);','return lightingOutput(light);');
 source=source.replaceAll('*frame.sun.w','*solarPower()');
 let ocean=cityOceanShader(),capture='';
 if(planar){
  ocean=ocean.replace('let refl = oceanEnvironment(R,(envLod)/8.0);','let refl = sceneReflection(world,nV,envLod/8.0,oceanEnvironment(R,envLod/8.0));');
  capture=source.slice(source.indexOf('@fragment fn fragment(')).replace('fn fragment(', 'fn captureFragment(')
   .replace(/  if u32\(m.physical.z\)==12u \{[\s\S]*?  if m.scale.w/,'  if m.scale.w')
   .replace('  let m=materials[v.material];','  if v.world.y<frame.display.w+.03 || u32(materials[v.material].physical.z)==12u {discard;}\n  let m=materials[v.material];')
   .replace('return lightingOutput(light);','return vec4f(light,1);');
  source=source.replace('  let fog=',GROUND_COAT_WGSL+'  let fog=');
 }
 return 'diagnostic(off, derivative_uniformity);\n'+source+'\n'+ocean+(planar?PLANAR_WGSL+GROUND_WGSL+capture:'');
}
