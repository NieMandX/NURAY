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
// Cache construction cannot read its own irradiance (no feedback).
fn cachedIrradiance(p:vec3f,n:vec3f)->vec4f {return vec4f(0);}
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
    let value=meshTransport(start,rd,hit,true);let count=u.render.y;
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
