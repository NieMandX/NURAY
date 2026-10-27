import {FRAME_WGSL,ATMO_CORE_WGSL} from './ocean/vendor/common.js?v=moscow-defaults-1';
import {SKY_RENDER_FUNCS,SKY_CLOUD_FUNCS} from './ocean/vendor/sky.js?v=moscow-defaults-1';
import {SEASCAPE_WGSL} from './seascape/seascape-wgsl.js?v=moscow-defaults-1';
import {hosekWGSL} from './hosek/shaders.js?v=moscow-defaults-1';
import {WATER_OPTICS_WGSL} from './ocean/optics.js?v=moscow-defaults-1';
// The ray integrator samples the same physical sky and wave fields as raster.
// Explicit ray-cone LOD replaces fragment derivatives. Water stays on the baked
// finite surface: its BSDF normal changes, not the city geometry or BVH.
export const TRACE_ENVIRONMENT=FRAME_WGSL.replaceAll('Frame','TraceOceanFrame')+`
@group(2) @binding(0) var<uniform> F:TraceOceanFrame;
@group(2) @binding(2) var derivTex:texture_2d_array<f32>;
@group(2) @binding(3) var momTex:texture_2d_array<f32>;
@group(2) @binding(4) var dispTex:texture_2d_array<f32>;
@group(2) @binding(5) var foamTex:texture_2d<f32>;
@group(2) @binding(6) var sampR:sampler;
@group(2) @binding(7) var transLUT:texture_2d<f32>;
@group(2) @binding(8) var sampC:sampler;
@group(2) @binding(9) var coastField:texture_2d<f32>;
@group(2) @binding(10) var skyLUT:texture_2d<f32>;
`+WATER_OPTICS_WGSL+hosekWGSL(2,1)+ATMO_CORE_WGSL.replace(/const PI:.*?;/,'')+SKY_RENDER_FUNCS+SKY_CLOUD_FUNCS.replace('let pix = F.screen.w * 2.0 * length(F.camUp.xyz) * 0.75;','let pix = 0.000001;')+SEASCAPE_WGSL.slice(0,SEASCAPE_WGSL.indexOf('fn seascapeShade'))+`
fn traceSunCos()->f32 {
 if F.windP[1].y>3.5 {return cos(HW.p[27].z);}
 if F.windP[1].y<.5 {return cos(SUN_ANG_R);}
 return .9998;
}
fn cityTraceSky(rd:vec3f)->vec3f {
 let sun=u.light.xyz;let mode=F.windP[1].y;let intensity=F.viewProj[1].w;
 if mode>3.5 {return hwSky(rd,sun)+hwDisc(rd,sun,0.0)*intensity;}
 if mode<.5 {
  if rd.y<0 {return vec3f(.06,.08,.08);}
  var transmission=1.0;let dir=normalize(vec3f(rd.x,max(rd.y,.0005),rd.z));
  let cl=cloudLayers(dir,0.0,vec2f(-1),&transmission);
  return skyAtmo(dir)*(1-cl.a)+cl.rgb+sunDisk(rd)*transmission*intensity;
 }
 let t=select(select(0.0,1.0,mode>1.5),F.viewProj[1].y,mode>2.5);
 let classic=mix(vec3f(.08,.09,.10),vec3f(.30,.43,.65),clamp(rd.y*.5+.5,0.0,1.0));
 let light=mix(vec3f(4.2,3.77,3.1),vec3f(2.5),t)*u.light.w*intensity;
 return mix(classic,seaSky(rd,sun),t)+select(vec3f(0),light/(2*PI*(1-traceSunCos())),dot(rd,sun)>=traceSunCos());
}
// Texture-backed index avoids exceeding the integrator's eight storage slots.
fn coastEntry(i:u32)->vec4f {let w=textureDimensions(coastField).x;return textureLoad(coastField,vec2i(vec2u(i%w,i/w)),0);}
fn traceShore(p:vec3f)->f32 {
 let grid=coastEntry(0u);let cell=vec2i(floor((p.xz-grid.xy)/grid.z));
 if any(cell<vec2i(0))||cell.x>=i32(grid.w)||cell.y>=i32(coastEntry(1u).x) {return 100;}
 let entry=coastEntry(2u+u32(cell.y)*u32(grid.w)+u32(cell.x)).xy;var best=100.0;
 for(var i=0u;i<u32(entry.y);i++){
  let a=coastEntry(u32(coastEntry(u32(entry.x)+i/4u)[i%4u]));let delta=a.zw-a.xy;
  let t=clamp(dot(p.xz-a.xy,delta)/max(dot(delta,delta),.0001),0.0,1.0);
  best=min(best,length(p.xz-mix(a.xy,a.zw,t)));
 }return best;
}
fn traceWater(m:Surface,p:vec3f,travel:f32)->Surface {
 let footprint=max(.015,travel*u.right.w*2/u.viewport.y);var normal=vec3f(0,1,0);var rough=.12;var crest=0.0;
 if F.windP[1].z>.5 {
  let eps=max(.025,footprint*.5);let h=seaHeight(p.xz,footprint);
  normal=normalize(vec3f(h-seaHeight(p.xz+vec2f(eps,0),footprint),eps,h-seaHeight(p.xz+vec2f(0,eps),footprint)));
  crest=smoothstep(1.65,2.3,h/max(F.viewProj[0].x,.001))*.15*F.foamP.z;
 }else{
  let gustN=textureSampleLevel(foamTex,sampR,p.xz*.011+F.windP[0].xy*(F.camPos.w*.0004),0).b;
  let gust=mix(.35,1.2,smoothstep(.3,.72,gustN));var slope=vec2f(0);var j=vec3f(0);var variance=0.0;
  for(var c=0u;c<6u;c++){
   let inv=F.cascInvL[c>>2u][c&3u];let lod=clamp(log2(max(1.0,footprint*inv*256)),0.0,8.0);
   let k=mix(1.0,gust,select(0.0,select(.5,1.0,c>=4u),c>=3u));
   let dv=textureSampleLevel(derivTex,sampR,p.xz*inv,c,lod)*k;
   let mv=textureSampleLevel(momTex,sampR,p.xz*inv,c,lod)*k*k;
   let av=textureSampleLevel(dispTex,sampR,p.xz*inv,c,lod)*k;
   slope+=dv.xy;j+=vec3f(dv.z,dv.w,av.w);variance+=max(0.0,mv.x-dv.x*dv.x)+max(0.0,mv.y-dv.y*dv.y);
  }
  normal=normalize(vec3f(-slope.x/max(1+j.x,.15),1,-slope.y/max(1+j.y,.15)));
  rough=clamp(pow(.0024+variance*.5,.25),.08,.45);
  let J=(1+j.x)*(1+j.y)-j.z*j.z;crest=clamp((F.foamP.x-J)*F.foamP.y,0.0,1.0)*F.foamP.z*.5;
 }
 let pattern=textureSampleLevel(foamTex,sampR,p.xz*.35+vec2f(F.camPos.w*.008,0),clamp(log2(max(1.0,footprint*.35*512)),0.0,9.0)).r;
 let shore=traceShore(p);let coast=(1-smoothstep(.05,.65+pattern*.5,shore))*(.25+.3*pattern)*F.windP[1].x;
 let foam=clamp(max(crest,coast),0.0,.9);
 // Foam is a surface coverage, not absorption. The medium colour and actual
 // distance are integrated by transport.wgsl after the ray crosses the mesh.
 normal=normalize(m.normal+vec3f(normal.x,0,normal.z)/max(normal.y,.05));
 return Surface(vec3f(.65,.68,.66),rough,0,waterIOR(),12u,normal,foam);
}
`;
export function traceEnvironmentGroup(owner,pipeline,guides=false){
 const d=owner.device,o=owner.ocean;
 // Allocate only for ray tracing; the raster path retains its compact buffer.
 if(owner.traceCoastVersion!==owner.surfaceFieldValues){
  owner.traceCoast?.destroy();const values=owner.surfaceFieldValues;
  const width=2048,height=Math.max(1,Math.ceil(values.length/4/width)),data=new Float32Array(width*height*4);data.set(values);
  if(height>d.limits.maxTextureDimension2D)throw Error('Индекс берегов превышает размер GPU-текстуры');
  owner.traceCoast=d.createTexture({label:'Ray-traced shoreline index',size:[width,height],format:'rgba32float',usage:GPUTextureUsage.TEXTURE_BINDING|GPUTextureUsage.COPY_DST});
  d.queue.writeTexture({texture:owner.traceCoast},data,{bytesPerRow:width*16},[width,height]);owner.traceCoastVersion=values;
 }
 const view=t=>t.createView({dimension:'2d-array'});
 const resources=[{buffer:o.frame},{buffer:o.hosek},view(o.deriv),view(o.mom),view(o.disp),o.foamTex.createView(),o.repeat,o.trans.createView(),o.clamp,owner.traceCoast.createView(),o.sky.createView()];
 const used=guides?[0,2,3,4,5,6,9]:resources.map((_,i)=>i);
 return d.createBindGroup({layout:pipeline.getBindGroupLayout(2),entries:used.map(binding=>({binding,resource:resources[binding]}))});
}
