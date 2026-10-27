struct Frame { view:mat4x4f, shadow:mat4x4f, camera:vec4f, sun:vec4f, settings:vec4f, display:vec4f };
struct Material { color:vec4f, physical:vec4f, scale:vec4f };
@group(0) @binding(0) var<uniform> frame:Frame;
@group(0) @binding(1) var<storage,read> materials:array<Material>;
@group(0) @binding(2) var albedo:texture_2d_array<f32>;
@group(0) @binding(3) var normals:texture_2d_array<f32>;
@group(0) @binding(4) var properties:texture_2d_array<f32>;
@group(0) @binding(5) var surfaceSampler:sampler;
@group(0) @binding(6) var shadowDepth:texture_depth_2d_array;
@group(0) @binding(7) var shadowSampler:sampler_comparison;
struct SunMaps { matrices:array<mat4x4f,3>, params:array<vec4f,3>, control:vec4f };
@group(0) @binding(9) var<uniform> sunMaps:SunMaps;
struct Instance { x:vec4f,y:vec4f,z:vec4f };
@group(0) @binding(8) var<storage,read> instances:array<Instance>;
fn position(p:vec3f,id:u32)->vec3f {let m=instances[id];return vec3f(dot(m.x,vec4f(p,1)),dot(m.y,vec4f(p,1)),dot(m.z,vec4f(p,1)));}
fn instanceNormal(n:vec3f,id:u32)->vec3f {
  let m=instances[id];let a=vec3f(m.x.x,m.y.x,m.z.x);let b=vec3f(m.x.y,m.y.y,m.z.y);let c=vec3f(m.x.z,m.y.z,m.z.z);
  return normalize(cross(b,c)*n.x+cross(c,a)*n.y+cross(a,b)*n.z);
}
struct VertexIn { @location(0) position:vec3f, @location(1) normal:vec2f, @location(2) uv:vec2f, @location(3) face:u32, @location(4) tint:f32 };
struct VertexOut { @builtin(position) position:vec4f, @location(0) world:vec3f, @location(1) normal:vec3f, @location(2) uv:vec2f, @location(3) @interpolate(flat) material:u32, @location(4) tint:f32 };
fn octDecode(e:vec2f)->vec3f {
  var n=vec3f(e,1.0-abs(e.x)-abs(e.y));let t=clamp(-n.z,0.0,1.0);
  n.x+=select(t,-t,n.x>=0.0);n.y+=select(t,-t,n.y>=0.0);return normalize(n);
}
@vertex fn vertex(input:VertexIn,@builtin(instance_index) instance:u32)->VertexOut {
  let kind=input.face&15u;let seed=input.face>>4u;let count=u32(frame.settings.x);
  var material=0u;if (input.face&0x80000000u)>0u {material=input.face&0x7fffffffu;}else if count>1u {material=kind+11u*(seed%((count+10u-kind)/11u));}
  let world=position(input.position,instance);
  return VertexOut(frame.view*vec4f(world,1),world,instanceNormal(octDecode(input.normal),instance),input.uv,material,select(1.0,input.tint,input.tint>0));
}
@vertex fn shadowVertex(@location(0) p:vec3f,@builtin(instance_index) instance:u32)->@builtin(position) vec4f {return frame.shadow*vec4f(position(p,instance),1);}
@group(0) @binding(10) var<storage,read> surfaceField:array<vec4f>;
fn waterHash(p:vec2f)->f32 {return fract(sin(dot(p,vec2f(127.1,311.7)))*43758.5453);}
fn waterNoise(p:vec2f)->f32 {
 let i=floor(p);let f=fract(p);let u=f*f*(3-2*f);
 return mix(mix(waterHash(i),waterHash(i+vec2f(1,0)),u.x),mix(waterHash(i+vec2f(0,1)),waterHash(i+vec2f(1,1)),u.x),u.y);
}
// An exact segment distance inside a coarse spatial index: no tile-edge foam.
fn surfaceDistance(p:vec3f,road:bool)->f32 {
 let grid=surfaceField[0];let cell=vec2i(floor((p.xz-grid.xy)/grid.z));let rows=i32(surfaceField[1].x);
 if any(cell<vec2i(0))||cell.x>=i32(grid.w)||cell.y>=rows {return 100;}
 let header=surfaceField[2+u32(cell.y)*u32(grid.w)+u32(cell.x)];let entry=select(header.xy,header.zw,road);
 var best=100.0;var fallback=100.0;
 for(var i=0u;i<u32(entry.y);i++){
  let address=u32(surfaceField[u32(entry.x)+i/4u][i%4u]);let a=surfaceField[address];let b=surfaceField[address+1u];let delta=a.zw-a.xy;
  let t=clamp(dot(p.xz-a.xy,delta)/max(dot(delta,delta),.0001),0.0,1.0);
  if road&&abs(p.y-mix(b.x,b.y,t))>.65 {continue;}
  let distance=length(p.xz-mix(a.xy,a.zw,t));
  if b.z<1.5 {best=min(best,distance);}else{fallback=min(fallback,distance);}
 }
 if road&&best>3.4 {return fallback;}
 return best;
}
// Sum incommensurate travelling waves; a large-scale wind field controls
// their slope and roughness. Coordinates are global metres, never tile UVs.
fn waterShape(p:vec2f,time:f32,footprint:f32)->vec3f {
 let wind=smoothstep(.20,.82,.7*waterNoise(p*.009)+.3*waterNoise(p*.027+31.7));
 let warp=waterNoise(p*.052+vec2f(time*.013,-time*.009))*3.0;
 let k=vec2f(.91,.42);let q=vec2f(-.34,.94);
 let a=dot(p,k)*2.75+time*1.1+warp;
 let b=dot(p,q)*5.9-time*1.65+warp*.7;
 let c=dot(p,vec2f(.66,-.75))*1.13+time*.58+warp*1.5+waterNoise(p*.21)*1.8;
 let fine=1-smoothstep(.12,.8,footprint);let broad=1-smoothstep(.8,3.0,footprint);
 let slope=(k*cos(a)*.048+q*cos(b)*.029)*fine+vec2f(.66,-.75)*cos(c)*.022*broad;
 return vec3f(slope*mix(.08,1.0,wind),wind);
}
fn waterFoam(p:vec2f,distance:f32,time:f32,footprint:f32)->f32 {
 let variation=waterNoise(p*.63+vec2f(time*.025,-time*.018));
 let patches=smoothstep(.22,.72,waterNoise(p*.16+21.3));
 let width=.35+variation*.42;
 let edge=1-smoothstep(width*.2,width+footprint*.6,distance);
 let lace=(1-smoothstep(.3,1.5,distance))*smoothstep(.55,.79,variation)*patches;
 return clamp((edge*.40+lace*.18)*mix(.4,1.0,patches),0.0,.45);
}
fn roadWear(p:vec3f)->f32 {
 let d=surfaceDistance(p,true);if d>12 {return 0;}
 let lane=abs(fract((d+1.75)/3.5)*3.5-1.75);
 let tracks=exp(-pow((lane-.86)/.32,2));
 let variation=.55+.45*waterNoise(p.xz*.075);
 return tracks*variation*.17;
}

fn sky(d:vec3f,rough:f32)->vec3f {
  let s=mix(vec3f(.26,.25,.21),vec3f(.55,.71,.90),smoothstep(-.15,.7,d.y));
  let sun=pow(max(0.0,dot(d,frame.sun.xyz)),mix(900.0,5.0,rough*rough));
  return s+vec3f(1.0,.88,.66)*sun*mix(3.0,.12,rough)*frame.sun.w;
}
fn fresnel(c:f32,f0:vec3f)->vec3f {return f0+(1-f0)*pow(1-clamp(c,0.0,1.0),5.0);}
fn dielectric(c:f32,eta:f32)->f32 {
  let st2=(1-c*c)/(eta*eta);if st2>=1 {return 1;}
  let ct=sqrt(max(0.0,1-st2));let a=(c-eta*ct)/(c+eta*ct);let b=(eta*c-ct)/(eta*c+ct);return .5*(a*a+b*b);
}
fn shadowAt(p:vec3f,n:vec3f,layer:i32)->f32 {
  let params=sunMaps.params[layer];let m=sunMaps.matrices[layer];let clip=m*vec4f(p+n*params.z,1);
  let uv=clip.xy*vec2f(.5,-.5)+.5;
  if any(uv<vec2f(0))||any(uv>vec2f(1))||clip.z<0||clip.z>1 {return 1;}
  // Compare each tap against the receiver plane at that tap, not the
  // centre depth. This prevents broad acne bands on grazing facades.
  let rx=vec3f(m[0].x,m[1].x,m[2].x);let ry=vec3f(m[0].y,m[1].y,m[2].y);let rz=vec3f(m[0].z,m[1].z,m[2].z);
  let g=vec3f(dot(n,rx)/dot(rx,rx),dot(n,ry)/dot(ry,ry),dot(n,rz)/dot(rz,rz));
  if abs(g.z)<.0001 {return 1;}
  let gradient=-g.xy/g.z*vec2f(2,-2);
  let bias=max(params.y,(abs(gradient.x)+abs(gradient.y))/sunMaps.control.x);
  var value=0.0;
  for(var y=-1;y<=1;y++){for(var x=-1;x<=1;x++){
    let offset=vec2f(f32(x),f32(y))/sunMaps.control.x;
    value+=textureSampleCompareLevel(shadowDepth,shadowSampler,uv+offset,layer,clip.z+dot(gradient,offset)-bias);
  }}
  return value/9.0;
}
fn visibility(p:vec3f,n:vec3f)->f32 {
  if frame.settings.z<.5 {return 1;}
  let count=i32(sunMaps.control.y);
  for(var i=0;i<count;i++){
    let q=sunMaps.matrices[i]*vec4f(p,1);let edge=max(abs(q.x),abs(q.y));
    if edge<1 && q.z>0 && q.z<1 {
      let value=shadowAt(p,n,i);
      if i+1<count && edge>.8 {return mix(value,shadowAt(p,n,i+1),smoothstep(.8,1.0,edge));}
      return value;
    }
  }
  return 1;
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
  let geometricNormal=normalize(v.normal);var n=geometricNormal;var color=clamp(m.color.rgb*v.tint,vec3f(0),vec3f(1));var rough=m.color.w;var ao=1.0;
  if frame.settings.y>.5 {
    let tex=textureSample(albedo,surfaceSampler,uv,i32(v.material));
    if tex.a<m.physical.w {discard;}
    let map=textureSample(normals,surfaceSampler,uv,i32(v.material)).xyz*2-1;
    let orm=textureSample(properties,surfaceSampler,uv,i32(v.material));
    color*=tex.rgb;rough=orm.g;ao=orm.r;if m.scale.z>.5 {
      let up=normalize(vec3f(0,1,0)-n*n.y);let right=normalize(cross(up,n));n=normalize(right*map.x+up*map.y+n*map.z);
    }else {n=normalize(tangent*map.x+bitangent*map.y+n*map.z);}
  }
  let footprint=max(length(dp1.xz),length(dp2.xz));
  if u32(m.physical.z)==12u {
    let shape=waterShape(v.world.xz,frame.display.z,footprint);n=normalize(geometricNormal+vec3f(shape.x,0,shape.y));
    let foam=waterFoam(v.world.xz,surfaceDistance(v.world,false),frame.display.z,footprint);
    color=mix(color,vec3f(.50,.54,.51),foam);rough=mix(mix(.12,.24,shape.z),.65,foam);
  }else if m.scale.w>.5 {color*=1-roadWear(v.world);}
  let wo=normalize(frame.camera.xyz-v.world);let wi=frame.sun.xyz;let h=normalize(wo+wi);
  let nv=max(.001,dot(n,wo));let nl=max(.0,dot(n,wi));let nh=max(.0,dot(n,h));let vh=max(.0,dot(wo,h));
  let metal=m.physical.x;let f0=mix(vec3f(.04),color,metal);let F=fresnel(vh,f0);
  let a=max(.001,rough*rough);let a2=a*a;let den=nh*nh*(a2-1)+1;
  let D=a2/(3.14159265*den*den);
  let Gv=2*nv/(nv+sqrt(a2+(1-a2)*nv*nv));let Gl=2*nl/max(.0001,nl+sqrt(a2+(1-a2)*nl*nl));
  let spec=F*D*Gv*Gl/max(.0001,4*nv*nl);
  let diffuse=(1-F)*color*(1-metal)/3.14159265;
  let shadow=visibility(v.world,geometricNormal);
  var light=(diffuse+spec)*vec3f(4.2,3.77,3.1)*nl*shadow*frame.sun.w;
  light+=color*(1-metal)*mix(vec3f(.17,.18,.20),vec3f(.45,.51,.58),n.y*.5+.5)*ao;
  light+=sky(reflect(-wo,n),rough)*fresnel(nv,f0)*mix(1.0,.40,rough);
  if u32(m.physical.z)==4u {
    // Thin architectural glazing over a dark interior. Environment reflection,
    // Fresnel transmission and Beer attenuation; no scene-space ray refraction.
    let Fglass=dielectric(nv,m.physical.y);
    let transmitted=vec3f(.028,.032,.034)*exp(-vec3f(.25,.09,.06)*(.012/max(.15,nv)));
    light=sky(reflect(-wo,n),rough)*Fglass+transmitted*(1-Fglass)+spec*vec3f(4.2,3.77,3.1)*nl*shadow*frame.sun.w;
  }
  light*=mix(1.0/1.4,1.0,shadow);
  let fog=1-exp(-length(frame.camera.xyz-v.world)*frame.display.y);
  light=mix(light,vec3f(.55,.61,.64),fog);
  return vec4f(srgb(toneMap(light*frame.display.x)),1);
}
