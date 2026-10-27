@group(0) @binding(1) var<storage,read_write> accumulation:array<vec4f>;
@group(0) @binding(2) var<storage,read> irradiance:array<vec4f>;
const PROBE_DIMS=vec3u(12,8,12);
const FIELD_MIN=vec3f(-2.96,0.04,-2.96);
const FIELD_SIZE=vec3f(5.92,4.18,5.92);
fn probeIndex(p:vec3u)->u32 { return p.x+PROBE_DIMS.x*(p.y+PROBE_DIMS.y*p.z); }
fn cascadeIrradiance(p:vec3f,n:vec3f)->vec4f {
  let g=clamp((p+n*0.10-FIELD_MIN)/FIELD_SIZE*vec3f(PROBE_DIMS)-0.5,vec3f(0),vec3f(PROBE_DIMS)-1.001);
  let cell=vec3u(floor(g)); let f=fract(g); var sum=vec3f(0); var weight=0.0;
  let axisWeights=n*n;
  for(var z=0u;z<2u;z++){for(var y=0u;y<2u;y++){for(var x=0u;x<2u;x++){
    let c=cell+vec3u(x,y,z); let pos=FIELD_MIN+(vec3f(c)+0.5)/vec3f(PROBE_DIMS)*FIELD_SIZE;
    let d=pos-(p+n*EPS*3.0); let dist=length(d);
    if dot(d,n)<-0.015 || solid(pos) { continue; }
    let obstruction=scene(p+n*EPS*3.0,d/max(dist,0.0001));
    if obstruction.t<dist-EPS*4.0 { continue; }
    let v=select(vec3f(1)-f,f,vec3u(x,y,z)==vec3u(1));
    let w=v.x*v.y*v.z; let index=probeIndex(c)*6u;
    let light=irradiance[index+select(1u,0u,n.x>=0.0)].rgb*axisWeights.x+
      irradiance[index+select(3u,2u,n.y>=0.0)].rgb*axisWeights.y+
      irradiance[index+select(5u,4u,n.z>=0.0)].rgb*axisWeights.z;
    sum+=w*light;weight+=w;
  }}}
  return vec4f(sum/max(weight,1e-6),weight);
}
fn pathTrace(origin:vec3f,direction:vec3f)->vec3f {
  var ro=origin; var rd=direction; var radiance=vec3f(0); var beta=vec3f(1);
  var inGlass=false; var etaScale=1.0; var previousDelta=true; var previousPdf=0.0; var previousPoint=origin;
  for(var bounce=0u;bounce<u32(u.glass.w);bounce++){
    let hit=scene(ro,rd);
    if hit.id<0 {
      if bounce==0u { radiance+=vec3f(0.035,0.041,0.043); }
      else { radiance+=beta*environment(rd); }
      break;
    }
    if inGlass { beta*=absorption(hit.t); }
    let p=ro+rd*hit.t;
    if hit.id==8 {
      if dot(rd,hit.normal)<0.0 {
        var weight=1.0;
        if !previousDelta { weight=powerHeuristic(previousPdf,lightPdf(previousPoint,p)); }
        radiance+=beta*u.light.w*weight;
      }
      break;
    }
    let front=dot(rd,hit.normal)<0.0; let n=select(-hit.normal,hit.normal,front); let wo=-rd;
    if hit.id==5 {
      let eta=select(1.0/u.glass.x,u.glass.x,front);
      let F=fresnelDielectric(max(0.0,dot(wo,n)),eta);
      if random()<F { rd=reflect(rd,n); }
      else {
        rd=refract(rd,n,1.0/eta);
        beta/=eta*eta; etaScale*=eta*eta; inGlass=front;
      }
      ro=p+rd*EPS*2.0; previousDelta=true;
    } else {
      let cached=u.settings.x>0.5 && hit.id!=7 && u.settings.y>0.5;
      let terminateDiffuse=u.settings.y<0.5 && hit.id!=7;
      radiance+=beta*directLight(hit.id,p,n,wo,!cached && !terminateDiffuse);
      if cached {
        // Approximate diffuse gather only; deliberately separated from the reference path integrator.
        let fView=1.0-fresnelDielectric(max(0.0,dot(n,wo)),1.5);
        let gather=cascadeIrradiance(p,n);
        let confidence=smoothstep(0.05,0.45,gather.a);
        var incoming=gather.rgb/PI;
        if confidence<0.999 {
          // Missing/occluded probes use a real sampled first-bounce fallback;
          // blending by support removes hard black cells near contacts.
          let wi=cosineDirection(n);
          let fallback=firstBounceRadiance(p+n*EPS*3.0,wi);
          incoming=mix(fallback,incoming,confidence);
        }
        radiance+=beta*baseColor(hit.id,p)*incoming*(fView*0.92);
        break;
      }
      if terminateDiffuse { break; }
      let wi=sampleBsdf(hit.id,n,wo); let pdf=bsdfPdf(hit.id,n,wo,wi);
      if pdf<=1e-10 || dot(wi,n)<=0.0 { break; }
      beta*=brdf(hit.id,p,n,wo,wi)*max(0.0,dot(n,wi))/pdf;
      previousPoint=p; previousPdf=pdf; previousDelta=false;
      ro=p+n*EPS*2.0; rd=wi;
    }
    if bounce>=4u {
      let rrBeta=beta*etaScale;
      let survival=clamp(max(rrBeta.x,max(rrBeta.y,rrBeta.z)),0.05,0.95);
      if random()>survival { break; } beta/=survival;
    }
  }
  return max(radiance,vec3f(0));
}
@compute @workgroup_size(8,8)
fn main(@builtin(global_invocation_id) gid:vec3u){
  let size=vec2u(u.viewport.xy); if any(gid.xy>=size){return;}
  let index=gid.x+gid.y*size.x;
  var mean=vec3f(0);
  if u.viewport.z>0.0 { mean=accumulation[index].rgb; }
  for(var sample=0u;sample<u32(u.render.x);sample++){
    // Same seeds and averaging order for 8 x 1 spp and 1 x 8 spp.
    rng=(index*1973u+(u32(u.viewport.w)+sample)*9277u+89173u)|1u;
    let jitter=vec2f(random(),random());
    let uv=(vec2f(gid.xy)+jitter)/u.viewport.xy*2.0-1.0;
    let rd=normalize(u.forward.xyz+u.right.xyz*uv.x*(u.viewport.x/u.viewport.y)*u.right.w-u.up.xyz*uv.y*u.right.w);
    let value=pathTrace(u.camera.xyz,rd);let count=u.viewport.z+f32(sample);
    mean=(mean*count+value)/(count+1.0);
  }
  accumulation[index]=vec4f(mean,1);
}
