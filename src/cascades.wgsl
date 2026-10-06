// Dense 3D radiance cascades: ray intervals (L,T), 4x angular branching,
// trilinear spatial interpolation, and coarse-to-fine interval composition.
// This is a compact experiment, NOT the sparse Split RC paper implementation.
struct Level { dims:vec4u, parentDims:vec4u, interval:vec4f };
@group(0) @binding(1) var<uniform> level:Level;
@group(0) @binding(2) var<storage,read> parent:array<vec4f>;
@group(0) @binding(3) var<storage,read_write> result:array<vec4f>;
const FIELD_MIN=vec3f(-2.96,0.04,-2.96);
const FIELD_SIZE=vec3f(5.92,4.18,5.92);
fn direction(x:u32,y:u32,res:u32)->vec3f {
  let phi=(f32(x)+0.5)/f32(res)*2.0*PI;
  let c=1.0-2.0*(f32(y)+0.5)/f32(res);
  let s=sqrt(max(0.0,1.0-c*c)); return vec3f(s*cos(phi),c,s*sin(phi));
}
fn parentGather(p:vec3f,dir:u32)->vec4f {
  let dims=level.parentDims.xyz;
  let grid=clamp((p-FIELD_MIN)/FIELD_SIZE*vec3f(dims)-0.5,vec3f(0),max(vec3f(0),vec3f(dims)-1.001));
  let c=vec3u(floor(grid)); let f=fract(grid); var sum=vec4f(0);
  for(var z=0u;z<2u;z++){for(var y=0u;y<2u;y++){for(var x=0u;x<2u;x++){
    let q=min(c+vec3u(x,y,z),dims-1u);
    let w=select(vec3f(1)-f,f,vec3u(x,y,z)==vec3u(1));
    let index=(q.x+dims.x*(q.y+dims.y*q.z))*level.parentDims.w*level.parentDims.w+dir;
    sum+=w.x*w.y*w.z*parent[index];
  }}}
  return sum;
}
@compute @workgroup_size(64)
fn main(@builtin(global_invocation_id) gid:vec3u){
  let dirs=level.dims.w*level.dims.w;let count=level.dims.x*level.dims.y*level.dims.z*dirs;
  let index=gid.x;if index>=count{return;}
  let probe=index/dirs;let angular=index%dirs;
  let c=vec3u(probe%level.dims.x,(probe/level.dims.x)%level.dims.y,probe/(level.dims.x*level.dims.y));
  let p=FIELD_MIN+(vec3f(c)+0.5)/vec3f(level.dims.xyz)*FIELD_SIZE;
  if solid(p) { result[index]=vec4f(0);return; }
  let dx=angular%level.dims.w;let dy=angular/level.dims.w;let rd=direction(dx,dy,level.dims.w);
  // Cache sampling is independent of camera/image resets and path batch size.
  rng=(index*1973u+u32(u.render.y)*9277u+level.dims.w*337u+89173u)|1u;
  let start=p+rd*level.interval.x;
  let hit=scene(start,rd);let span=level.interval.y-level.interval.x;
  if hit.t<span {
    let value=firstBounceRadianceFromHit(start,rd,hit);
    let count=u.render.y;
    if count==0.0 { result[index]=vec4f(value,0); }
    else { result[index]=vec4f((result[index].rgb*count+value)/(count+1.0),0); }
    return;
  }
  if level.interval.z>0.5 {
    // Parent already contains averaged radiance; averaging it again would
    // overweight early noisy samples. Reconstruct this empty interval directly.
    var upper=vec4f(0);
    for(var y=0u;y<2u;y++){for(var x=0u;x<2u;x++){
      upper+=parentGather(p,(dy*2u+y)*level.parentDims.w+(dx*2u+x))*0.25;
    }}
    result[index]=upper;
  } else { result[index]=vec4f(environment(rd),1); }
}
