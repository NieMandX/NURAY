struct CacheField { minimum:vec4f, extent:vec4f };
@group(1) @binding(0) var<uniform> cacheField:CacheField;
@group(1) @binding(1) var<storage,read> irradiance:array<vec4f>;
// A single stochastic trilinear neighbour + bounded visibility ray. Unsupported
// samples use the reference integrator; no eight long visibility rays per pixel.
fn cachedIrradiance(p:vec3f,n:vec3f)->vec4f {
  let dims=vec3u(16,8,16);let position=(p-cacheField.minimum.xyz)/cacheField.extent.xyz;
  if any(position<vec3f(0))||any(position>vec3f(1)){return vec4f(0);}
  let g=clamp(position*vec3f(dims)-.5,vec3f(0),vec3f(dims)-1.001);
  let c=vec3u(floor(g))+vec3u(select(vec3f(0),vec3f(1),vec3f(random(),random(),random())<fract(g)));
  let pos=cacheField.minimum.xyz+(vec3f(c)+.5)/vec3f(dims)*cacheField.extent.xyz;
  let origin=p+n*EPS*3;let delta=pos-origin;let distance=length(delta);
  if dot(delta,n)<=EPS||traceMeshLimit(origin,delta/max(distance,EPS),true,max(EPS,distance-EPS*4)).t<INF{return vec4f(0);}
  let index=(c.x+dims.x*(c.y+dims.y*c.z))*6u;let w=n*n;
  let light=irradiance[index+select(1u,0u,n.x>=0)].rgb*w.x+
    irradiance[index+select(3u,2u,n.y>=0)].rgb*w.y+irradiance[index+select(5u,4u,n.z>=0)].rgb*w.z;
  return vec4f(light,1);
}
fn specPdf(m:Surface,n:vec3f,wo:vec3f,wi:vec3f)->f32 {
  let nv=dot(n,wo);if nv<=0||dot(n,wi)<=0{return 0;}
  let h=normalize(wo+wi);let a=max(.002,m.rough*m.rough);
  return ggxD(max(0.0,dot(n,h)),a)*ggxG1(nv,a)/(4*nv);
}
fn diffuseBrdf(m:Surface,n:vec3f,wo:vec3f,wi:vec3f)->vec3f {
  return m.color*(1-m.metal)/PI*(1-fresnelDielectric(max(0.0,dot(n,wo)),m.ior))*(1-fresnelDielectric(max(0.0,dot(n,wi)),m.ior));
}
fn meshPath(origin:vec3f,direction:vec3f)->vec3f {
  var ro=origin;var rd=direction;var radiance=vec3f(0);var beta=vec3f(1);var inside=false;
  var etaScale=1.0;var delta=true;var lastPdf=0.0;var travel=0.0;
  for(var bounce=0u;bounce<u32(u.glass.w);bounce++){
    let hit=traceMesh(ro,rd,false);
    if hit.t>=INF {
      var weight=1.0;if !delta {weight=powerHeuristic(lastPdf,skyPdf(rd));}
      radiance+=beta*meshSky(rd)*weight;break;
    }
    travel+=hit.t;if inside {beta*=exp(-vec3f(.28,.055,.16)*hit.t);}
    let p=ro+rd*hit.t;let m=meshSurface(hit,travel);let front=dot(rd,m.normal)<0;let n=select(-m.normal,m.normal,front);let wo=-rd;
    if m.kind==4u {
      let eta=select(1.0/m.ior,m.ior,front);let F=fresnelDielectric(max(0.0,dot(wo,n)),eta);
      if random()<F {rd=reflect(rd,n);}
      else {rd=refract(rd,n,1.0/eta);beta/=eta*eta;etaScale*=eta*eta;inside=front;}
      ro=p+rd*EPS*2.0;delta=true;
    }else{
      var gather=vec4f(0);
      if u.settings.w>.5 && u.settings.y>.5 && m.metal<.5 && bounce+1u<u32(u.glass.w) {gather=cachedIrradiance(p,n);}
      let cached=gather.a>.5;
      if cached {radiance+=beta*m.color*(1-m.metal)*(1-fresnelDielectric(max(0.0,dot(n,wo)),m.ior))*gather.rgb/PI;}
      let wi=sampleSky();let cosine=max(0.0,dot(n,wi));
      if cosine>0.0&&traceMesh(p+n*EPS*2.0,wi,true).t>=INF {
        let pdf=skyPdf(wi);var w=powerHeuristic(pdf,meshPdf(m,n,wo,wi));
        if (u.settings.y<.5&&m.metal<.5)||bounce+1u>=u32(u.glass.w) {w=1.0;}
        var contribution=meshBrdf(m,n,wo,wi)*w;
        if cached {
          let diffuse=diffuseBrdf(m,n,wo,wi);
          contribution=diffuse+(meshBrdf(m,n,wo,wi)-diffuse)*powerHeuristic(pdf,.25*specPdf(m,n,wo,wi));
        }
        radiance+=beta*contribution*meshSky(wi)*cosine/pdf;
      }
      if u.settings.y<.5&&m.metal<.5 {break;}
      if cached {
        // Keep coating reflections as actual rays; cache replaces only diffuse transport.
        if random()>=.25 {break;}
        let next=sampleGgx(n,wo,max(.002,m.rough*m.rough));let pdf=.25*specPdf(m,n,wo,next);
        if pdf<1e-10||dot(n,next)<=0 {break;}
        beta*=max(vec3f(0),meshBrdf(m,n,wo,next)-diffuseBrdf(m,n,wo,next))*max(0.0,dot(n,next))/pdf;
        ro=p+n*EPS*2;rd=next;lastPdf=pdf;delta=false;
      }else{
      var next=vec3f(0);if random()<select(.25,1.0,m.metal>.5){next=sampleGgx(n,wo,max(.002,m.rough*m.rough));}else{next=cosineDirection(n);}
      let pdf=meshPdf(m,n,wo,next);if pdf<1e-10||dot(n,next)<=0 {break;}
      beta*=meshBrdf(m,n,wo,next)*max(0.0,dot(n,next))/pdf;
      ro=p+n*EPS*2.0;rd=next;lastPdf=pdf;delta=false;
      }
    }
    if bounce>=4u {
      let rr=beta*etaScale;let survival=clamp(max(rr.x,max(rr.y,rr.z)),.05,.95);
      if random()>survival {break;}beta/=survival;
    }
  }
  return max(radiance,vec3f(0));
}
@compute @workgroup_size(8,8)
fn meshMain(@builtin(global_invocation_id) gid:vec3u){
  let size=vec2u(u.viewport.xy);if any(gid.xy>=size){return;}
  let index=gid.x+gid.y*size.x;var mean=vec3f(0);
  if u.viewport.z>0{mean=meshAccumulation[index].rgb;}
  for(var sample=0u;sample<u32(u.render.x);sample++){
    rng=(index*1973u+(u32(u.viewport.w)+sample)*9277u+89173u)|1u;
    let uv=(vec2f(gid.xy)+vec2f(random(),random()))/u.viewport.xy*2-1;
    let rd=normalize(u.forward.xyz+u.right.xyz*uv.x*(u.viewport.x/u.viewport.y)*u.right.w-u.up.xyz*uv.y*u.right.w);
    let value=meshPath(u.camera.xyz,rd);let count=u.viewport.z+f32(sample);
    mean=(mean*count+value)/(count+1);
  }
  meshAccumulation[index]=vec4f(mean,1);
}
