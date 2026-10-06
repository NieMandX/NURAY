// Dense interval radiance cascades. Cache reflected light only: direct sky/sun
// are sampled separately by the pixel integrator, preventing double counting.
struct CascadeLevel { minimum:vec4f, extent:vec4f, dims:vec4u, parentDims:vec4u, interval:vec4f };
@group(1) @binding(0) var<uniform> level:CascadeLevel;
@group(1) @binding(1) var<storage,read> parentRadiance:array<vec4f>;
@group(1) @binding(2) var<storage,read_write> radiance:array<vec4f>;
fn cascadeDirection(x:u32,y:u32,res:u32)->vec3f {
  let phi=(f32(x)+.5)/f32(res)*2*PI;let c=1-2*(f32(y)+.5)/f32(res);
  let s=sqrt(max(0.0,1-c*c));return vec3f(s*cos(phi),c,s*sin(phi));
}
fn parentGather(p:vec3f,dir:u32)->vec4f {
  let dims=level.parentDims.xyz;
  let g=clamp((p-level.minimum.xyz)/level.extent.xyz*vec3f(dims)-.5,vec3f(0),max(vec3f(0),vec3f(dims)-1.001));
  let cell=vec3u(floor(g));let f=fract(g);var sum=vec4f(0);
  for(var z=0u;z<2u;z++){for(var y=0u;y<2u;y++){for(var x=0u;x<2u;x++){
    let q=min(cell+vec3u(x,y,z),dims-1u);let w=select(1-f,f,vec3u(x,y,z)==vec3u(1));
    sum+=w.x*w.y*w.z*parentRadiance[(q.x+dims.x*(q.y+dims.y*q.z))*level.parentDims.w*level.parentDims.w+dir];
  }}}
  return sum;
}
// First diffuse bounce, with exact specular/glass chains and fixed texture LOD.
// This source does not read the cache it is building (no feedback/amplification).
fn bounceSource(origin:vec3f,direction:vec3f,first:MeshHit)->vec3f {
  var ro=origin;var rd=direction;var hit=first;var value=vec3f(0);var beta=vec3f(1);
  var inside=false;var delta=true;var lastPdf=0.0;
  for(var depth=0u;depth<min(6u,u32(u.glass.w));depth++){
    if depth>0u {hit=traceMesh(ro,rd,false);}
    if hit.t>=INF {
      var weight=1.0;if !delta {weight=powerHeuristic(lastPdf,skyPdf(rd));}
      value+=beta*meshSky(rd)*weight;break;
    }
    if inside {beta*=exp(-vec3f(.28,.055,.16)*hit.t);}
    let p=ro+rd*hit.t;let m=meshSurface(hit,0);let front=dot(rd,m.normal)<0;
    let n=select(-m.normal,m.normal,front);let wo=-rd;
    if m.kind==4u {
      let eta=select(1.0/m.ior,m.ior,front);
      if random()<fresnelDielectric(max(0.0,dot(wo,n)),eta){rd=reflect(rd,n);}
      else{rd=refract(rd,n,1.0/eta);beta/=eta*eta;inside=front;}
      ro=p+rd*EPS*2;delta=true;
    }else{
      let wi=sampleSky();let cosine=max(0.0,dot(n,wi));
      if cosine>0 && traceMesh(p+n*EPS*2,wi,true).t>=INF {
        let pdf=skyPdf(wi);var w=1.0;
        if m.metal>.5 && depth+1u<min(6u,u32(u.glass.w)){w=powerHeuristic(pdf,meshPdf(m,n,wo,wi));}
        value+=beta*meshBrdf(m,n,wo,wi)*meshSky(wi)*cosine*w/pdf;
      }
      if m.metal<.5 {break;}
      let next=sampleGgx(n,wo,max(.002,m.rough*m.rough));let pdf=meshPdf(m,n,wo,next);
      if pdf<1e-10||dot(n,next)<=0{break;}
      beta*=meshBrdf(m,n,wo,next)*max(0.0,dot(n,next))/pdf;
      ro=p+n*EPS*2;rd=next;lastPdf=pdf;delta=false;
    }
  }
  return max(value,vec3f(0));
}
@compute @workgroup_size(64)
fn cascadeMain(@builtin(global_invocation_id) gid:vec3u){
  let dirs=level.dims.w*level.dims.w;let count=level.dims.x*level.dims.y*level.dims.z*dirs;
  let index=gid.x;if index>=count{return;}
  let probe=index/dirs;let angular=index%dirs;
  let c=vec3u(probe%level.dims.x,(probe/level.dims.x)%level.dims.y,probe/(level.dims.x*level.dims.y));
  let p=level.minimum.xyz+(vec3f(c)+.5)/vec3f(level.dims.xyz)*level.extent.xyz;
  let x=angular%level.dims.w;let y=angular/level.dims.w;let rd=cascadeDirection(x,y,level.dims.w);
  rng=(index*1973u+u32(u.render.y)*9277u+level.dims.w*337u+89173u)|1u;
  let start=p+rd*level.interval.x;let span=level.interval.y-level.interval.x;
  let hit=traceMeshLimit(start,rd,false,span);
  if hit.t<INF {
    let value=bounceSource(start,rd,hit);let count=u.render.y;
    if count==0{radiance[index]=vec4f(value,0);}
    else{radiance[index]=vec4f((radiance[index].rgb*count+value)/(count+1),0);}
  }else if level.interval.z>.5 {
    var upper=vec4f(0);
    for(var dy=0u;dy<2u;dy++){for(var dx=0u;dx<2u;dx++){
      upper+=parentGather(p,(y*2u+dy)*level.parentDims.w+x*2u+dx)*.25;
    }}
    radiance[index]=upper;
  }else{radiance[index]=vec4f(0,0,0,1);}
}
