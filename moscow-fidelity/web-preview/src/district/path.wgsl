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
fn meshPath(origin:vec3f,direction:vec3f)->vec3f {
  return meshTransport(origin,direction,traceMesh(origin,direction,false),false);
}
@compute @workgroup_size(8,8)
fn meshMain(@builtin(global_invocation_id) gid:vec3u){
  let size=vec2u(u.viewport.xy);if any(gid.xy>=size){return;}
  let index=gid.x+gid.y*size.x;var mean=vec3f(0);var fresh=vec3f(0);
  if u.viewport.z>0{mean=meshAccumulation[index].rgb;}
  for(var sample=0u;sample<u32(u.render.x);sample++){
    rng=(index*1973u+(u32(u.viewport.w)+sample)*9277u+89173u)|1u;
    let uv=(vec2f(gid.xy)+vec2f(random(),random()))/u.viewport.xy*2-1;
    let rd=normalize(u.forward.xyz+u.right.xyz*uv.x*(u.viewport.x/u.viewport.y)*u.right.w-u.up.xyz*uv.y*u.right.w);
    let value=meshPath(u.camera.xyz,rd);let count=u.viewport.z+f32(sample);
    mean=(mean*count+value)/(count+1);
    fresh+=value;
  }
  meshAccumulation[index]=vec4f(mean,1);
  if u.render.z>.5 {meshAccumulation[index+size.x*size.y]=vec4f(fresh/u.render.x,1);}
}
