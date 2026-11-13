struct Gaussian {center:vec4f,ca:vec4f,cb:vec4f,color:vec4f};
struct Instance {x:vec4f,y:vec4f,z:vec4f};
struct Frame {vp:mat4x4f,screen:vec4f};
@group(0) @binding(0) var<uniform> frame:Frame;
@group(0) @binding(1) var<storage,read> gaussians:array<Gaussian>;
@group(0) @binding(2) var<storage,read> instances:array<Instance>;
@group(0) @binding(3) var<storage,read> order:array<vec2u>;
struct Out {@builtin(position) clip:vec4f,@location(0) uv:vec2f,@location(1) color:vec4f};
@vertex fn vertex(@builtin(vertex_index) vertex:u32,@builtin(instance_index) index:u32)->Out {
  let entry=order[index];let g=gaussians[entry.x];let m=instances[entry.y];
  let p=vec4f(g.center.xyz,1);let world=vec3f(dot(m.x,p),dot(m.y,p),dot(m.z,p));
  let clip=frame.vp*vec4f(world,1);
  var out:Out;out.clip=vec4f(2,2,2,1);out.uv=vec2f(4);out.color=vec4f(0);
  if(clip.w<=.01||clip.z<0||clip.z>clip.w){return out;}
  let r0=vec3f(frame.vp[0].x,frame.vp[1].x,frame.vp[2].x);
  let r1=vec3f(frame.vp[0].y,frame.vp[1].y,frame.vp[2].y);
  let r3=vec3f(frame.vp[0].w,frame.vp[1].w,frame.vp[2].w);
  let jx=(r0-r3*clip.x/clip.w)*(frame.screen.x*.5/clip.w);
  let jy=(r1-r3*clip.y/clip.w)*(frame.screen.y*.5/clip.w);
  let a=mat3x3f(vec3f(m.x.x,m.y.x,m.z.x),vec3f(m.x.y,m.y.y,m.z.y),vec3f(m.x.z,m.y.z,m.z.z));
  let cov=mat3x3f(vec3f(g.ca.x,g.ca.y,g.ca.z),vec3f(g.ca.y,g.ca.w,g.cb.x),vec3f(g.ca.z,g.cb.x,g.cb.y));
  let bx=transpose(a)*jx;let by=transpose(a)*jy;
  let xx=dot(bx,cov*bx);let xy=dot(bx,cov*by);let yy=dot(by,cov*by);
  let aa=xx+.3;let cc=yy+.3;let mid=(aa+cc)*.5;
  let radius=length(vec2f((aa-cc)*.5,xy));
  let l1=max(mid+radius,.001);let l2=max(mid-radius,.001);
  var dir=vec2f(1,0);if(abs(xy)>1e-7){dir=normalize(vec2f(xy,l1-aa));}else if(cc>aa){dir=vec2f(0,1);}
  let corners=array<vec2f,6>(vec2f(-1,-1),vec2f(1,-1),vec2f(1,1),vec2f(-1,-1),vec2f(1,1),vec2f(-1,1));
  let uv=corners[vertex]*3.0;
  let delta=(dir*sqrt(l1)*uv.x+vec2f(-dir.y,dir.x)*sqrt(l2)*uv.y)*2.0/frame.screen.xy;
  let aaOpacity=sqrt(max(xx*yy-xy*xy,0.0)/max(aa*cc-xy*xy,1e-12));
  out.clip=vec4f(clip.xy+delta*clip.w,clip.z,clip.w);out.uv=uv;
  out.color=vec4f(g.color.rgb,g.center.w*aaOpacity);return out;
}
@fragment fn fragment(in:Out)->@location(0) vec4f {
  let d=dot(in.uv,in.uv);if(d>9.0){discard;}
  let alpha=min(.995,in.color.a*exp(-.5*d));if(alpha<.0039){discard;}
  return vec4f(in.color.rgb*alpha,alpha);
}
