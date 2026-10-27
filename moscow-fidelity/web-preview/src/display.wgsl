struct Uniforms { viewport:vec4f,camera:vec4f,right:vec4f,up:vec4f,forward:vec4f,light:vec4f,settings:vec4f,glass:vec4f,render:vec4f };
@group(0) @binding(0) var<uniform> u:Uniforms;
@group(0) @binding(1) var<storage,read> accumulation:array<vec4f>;
struct VertexOut { @builtin(position) position:vec4f };
@vertex fn vertex(@builtin(vertex_index) i:u32)->VertexOut {
  let p=array<vec2f,3>(vec2f(-1,-1),vec2f(3,-1),vec2f(-1,3));
  return VertexOut(vec4f(p[i],0,1));
}
fn toneMap(x:vec3f)->vec3f {
  let a=2.51;let b=0.03;let c=2.43;let d=0.59;let e=0.14;
  return clamp((x*(a*x+b))/(x*(c*x+d)+e),vec3f(0),vec3f(1));
}
fn srgb(x:vec3f)->vec3f {
  return select(1.055*pow(x,vec3f(1.0/2.4))-0.055,x*12.92,x<=vec3f(0.0031308));
}
@fragment fn fragment(@builtin(position) p:vec4f)->@location(0) vec4f {
  let i=u32(p.x)+u32(p.y)*u32(u.viewport.x);
  return vec4f(srgb(toneMap(accumulation[i].rgb*u.glass.z)),1);
}
