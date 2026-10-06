struct Frame { view:mat4x4f, shadow:mat4x4f, camera:vec4f, sun:vec4f, settings:vec4f, display:vec4f };
struct Material { color:vec4f, physical:vec4f, scale:vec4f };
@group(0) @binding(0) var<uniform> frame:Frame;
@group(0) @binding(1) var<storage,read> materials:array<Material>;
@group(0) @binding(2) var albedo:texture_2d_array<f32>;
@group(0) @binding(3) var normals:texture_2d_array<f32>;
@group(0) @binding(4) var properties:texture_2d_array<f32>;
@group(0) @binding(5) var surfaceSampler:sampler;
@group(0) @binding(6) var shadowDepth:texture_depth_2d;
@group(0) @binding(7) var shadowSampler:sampler_comparison;
struct Instance { x:vec4f,y:vec4f,z:vec4f };
@group(0) @binding(8) var<storage,read> instances:array<Instance>;
fn position(p:vec3f,id:u32)->vec3f {let m=instances[id];return vec3f(dot(m.x,vec4f(p,1)),dot(m.y,vec4f(p,1)),dot(m.z,vec4f(p,1)));}
fn instanceNormal(n:vec3f,id:u32)->vec3f {
  let m=instances[id];let a=vec3f(m.x.x,m.y.x,m.z.x);let b=vec3f(m.x.y,m.y.y,m.z.y);let c=vec3f(m.x.z,m.y.z,m.z.z);
  return normalize(cross(b,c)*n.x+cross(c,a)*n.y+cross(a,b)*n.z);
}
struct VertexIn { @location(0) position:vec3f, @location(1) normal:vec2f, @location(2) uv:vec2f, @location(3) face:u32 };
struct VertexOut { @builtin(position) position:vec4f, @location(0) world:vec3f, @location(1) normal:vec3f, @location(2) uv:vec2f, @location(3) @interpolate(flat) material:u32 };
fn octDecode(e:vec2f)->vec3f {
  var n=vec3f(e,1.0-abs(e.x)-abs(e.y));let t=clamp(-n.z,0.0,1.0);
  n.x+=select(t,-t,n.x>=0.0);n.y+=select(t,-t,n.y>=0.0);return normalize(n);
}
@vertex fn vertex(input:VertexIn,@builtin(instance_index) instance:u32)->VertexOut {
  let kind=input.face&15u;let seed=input.face>>4u;let count=u32(frame.settings.x);
  var material=0u;if (input.face&0x80000000u)>0u {material=input.face&0x7fffffffu;}else if count>1u {material=kind+11u*(seed%((count+10u-kind)/11u));}
  let world=position(input.position,instance);
  return VertexOut(frame.view*vec4f(world,1),world,instanceNormal(octDecode(input.normal),instance),input.uv,material);
}
@vertex fn shadowVertex(@location(0) p:vec3f,@builtin(instance_index) instance:u32)->@builtin(position) vec4f {return frame.shadow*vec4f(position(p,instance),1);}
fn sky(d:vec3f,rough:f32)->vec3f {
  let s=mix(vec3f(.26,.25,.21),vec3f(.55,.71,.90),smoothstep(-.15,.7,d.y));
  let sun=pow(max(0.0,dot(d,frame.sun.xyz)),mix(900.0,5.0,rough*rough));
  return s+vec3f(1.0,.88,.66)*sun*mix(3.0,.12,rough);
}
fn fresnel(c:f32,f0:vec3f)->vec3f {return f0+(1-f0)*pow(1-clamp(c,0.0,1.0),5.0);}
fn dielectric(c:f32,eta:f32)->f32 {
  let st2=(1-c*c)/(eta*eta);if st2>=1 {return 1;}
  let ct=sqrt(max(0.0,1-st2));let a=(c-eta*ct)/(c+eta*ct);let b=(eta*c-ct)/(eta*c+ct);return .5*(a*a+b*b);
}
fn visibility(p:vec3f,n:vec3f)->f32 {
  if frame.settings.z<.5 {return 1;}
  let clip=frame.shadow*vec4f(p+n*.03,1);let uv=clip.xy/clip.w*vec2f(.5,-.5)+.5;let depth=clip.z/clip.w;
  var value=0.0;
  for(var y=-1;y<=1;y++){for(var x=-1;x<=1;x++){
    value+=textureSampleCompareLevel(shadowDepth,shadowSampler,uv+vec2f(f32(x),f32(y))/2048.0,depth-.00010);
  }}
  return value/9.0;
}
fn toneMap(x:vec3f)->vec3f {return clamp((x*(2.51*x+.03))/(x*(2.43*x+.59)+.14),vec3f(0),vec3f(1));}
fn srgb(x:vec3f)->vec3f {return select(1.055*pow(x,vec3f(1/2.4))-.055,x*12.92,x<=vec3f(.0031308));}
@fragment fn fragment(v:VertexOut)->@location(0) vec4f {
  let m=materials[v.material];let uv=v.uv*m.scale.xy;
  // Derivatives are outside material-dependent branches. The texture switch
  // is uniform across the draw and skips all three texture fetches when off.
  let dp1=dpdx(v.world);let dp2=dpdy(v.world);let duv1=dpdx(v.uv);let duv2=dpdy(v.uv);
  let handed=select(-1.0,1.0,duv1.x*duv2.y-duv1.y*duv2.x>=0);
  let tangent=normalize((dp1*duv2.y-dp2*duv1.y)*handed+vec3f(1e-15));
  let bitangent=normalize((-dp1*duv2.x+dp2*duv1.x)*handed+vec3f(1e-15));
  var n=normalize(v.normal);var color=m.color.rgb;var rough=m.color.w;var ao=1.0;
  if frame.settings.y>.5 {
    let tex=textureSample(albedo,surfaceSampler,uv,i32(v.material));
    if tex.a<m.physical.w {discard;}
    let map=textureSample(normals,surfaceSampler,uv,i32(v.material)).xyz*2-1;
    let orm=textureSample(properties,surfaceSampler,uv,i32(v.material));
    color*=tex.rgb;rough=orm.g;ao=orm.r;n=normalize(tangent*map.x+bitangent*map.y+n*map.z);
  }
  let wo=normalize(frame.camera.xyz-v.world);let wi=frame.sun.xyz;let h=normalize(wo+wi);
  let nv=max(.001,dot(n,wo));let nl=max(.0,dot(n,wi));let nh=max(.0,dot(n,h));let vh=max(.0,dot(wo,h));
  let metal=m.physical.x;let f0=mix(vec3f(.04),color,metal);let F=fresnel(vh,f0);
  let a=max(.001,rough*rough);let a2=a*a;let den=nh*nh*(a2-1)+1;
  let D=a2/(3.14159265*den*den);
  let Gv=2*nv/(nv+sqrt(a2+(1-a2)*nv*nv));let Gl=2*nl/max(.0001,nl+sqrt(a2+(1-a2)*nl*nl));
  let spec=F*D*Gv*Gl/max(.0001,4*nv*nl);
  let diffuse=(1-F)*color*(1-metal)/3.14159265;
  let shadow=visibility(v.world,n);
  var light=(diffuse+spec)*vec3f(4.2,3.77,3.1)*nl*shadow;
  light+=color*(1-metal)*mix(vec3f(.17,.18,.20),vec3f(.45,.51,.58),n.y*.5+.5)*ao;
  light+=sky(reflect(-wo,n),rough)*fresnel(nv,f0)*mix(1.0,.40,rough);
  if u32(m.physical.z)==4u {
    // Thin architectural glazing over a dark interior. Environment reflection,
    // Fresnel transmission and Beer attenuation; no scene-space ray refraction.
    let Fglass=dielectric(nv,m.physical.y);
    let transmitted=vec3f(.028,.032,.034)*exp(-vec3f(.25,.09,.06)*(.012/max(.15,nv)));
    light=sky(reflect(-wo,n),rough)*Fglass+transmitted*(1-Fglass)+spec*vec3f(4.2,3.77,3.1)*nl*shadow;
  }
  let fog=1-exp(-length(frame.camera.xyz-v.world)*frame.display.y);
  light=mix(light,vec3f(.55,.61,.64),fog);
  return vec4f(srgb(toneMap(light*frame.display.x)),1);
}
