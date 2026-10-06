// All transport is scene-linear RGB. Scene units are metres.
struct Uniforms {
  viewport: vec4f,       // width, height, accumulated spp, frame seed
  camera: vec4f,
  right: vec4f,          // xyz, tan(vertical FOV / 2)
  up: vec4f,
  forward: vec4f,
  light: vec4f,          // xyz, emitted radiance
  settings: vec4f,       // mode (0 path/1 cascades), indirect, metal rough, stone rough
  glass: vec4f,          // IOR, absorption scale, exposure, max depth
  render: vec4f,         // samples in this dispatch, previous cache samples, reserved
};
@group(0) @binding(0) var<uniform> u: Uniforms;
const PI = 3.14159265359;
const EPS = 0.0003;
const INF = 1e20;
const LIGHT_AREA = 2.16;
var<private> rng: u32;
fn random() -> f32 {
  rng = rng * 747796405u + 2891336453u;
  let word = ((rng >> ((rng >> 28u) + 4u)) ^ rng) * 277803737u;
  return f32((word >> 22u) ^ word) / 4294967296.0;
}
fn hash3(p: vec3f) -> f32 {
  var q = fract(p * 0.1031);
  q += dot(q, q.yzx + 33.33);
  return fract((q.x + q.y) * q.z);
}
fn noise3(p: vec3f) -> f32 {
  let i = floor(p); let f = fract(p); let a = f*f*(3.0-2.0*f);
  return mix(mix(mix(hash3(i), hash3(i+vec3f(1,0,0)), a.x),
    mix(hash3(i+vec3f(0,1,0)), hash3(i+vec3f(1,1,0)), a.x), a.y),
    mix(mix(hash3(i+vec3f(0,0,1)), hash3(i+vec3f(1,0,1)), a.x),
    mix(hash3(i+vec3f(0,1,1)), hash3(i+vec3f(1,1,1)), a.x), a.y), a.z);
}
struct Hit { t:f32, id:i32, normal:vec3f };
fn miss() -> Hit { return Hit(INF,-1,vec3f(0)); }
fn sphere(ro:vec3f, rd:vec3f, center:vec3f, radius:f32, id:i32) -> Hit {
  let oc = ro-center; let b = dot(oc,rd); let c = dot(oc,oc)-radius*radius;
  let d = b*b-c;
  if d < 0.0 { return miss(); }
  let s=sqrt(d); var t=-b-s;
  if t<EPS { t=-b+s; }
  if t<EPS { return miss(); }
  return Hit(t,id,(ro+rd*t-center)/radius);
}
fn scene(ro:vec3f, rd:vec3f) -> Hit {
  var h=miss(); var t:f32; var p:vec3f;
  // Room: floor, ceiling, left/right walls, back. Open at z=3.
  if abs(rd.y)>1e-7 {
    t=-ro.y/rd.y; p=ro+rd*t;
    if t>EPS && abs(p.x)<=3.0 && abs(p.z)<=3.0 { h=Hit(t,0,vec3f(0,1,0)); }
    t=(4.3-ro.y)/rd.y; p=ro+rd*t;
    if t>EPS && t<h.t && abs(p.x)<=3.0 && abs(p.z)<=3.0 { h=Hit(t,4,vec3f(0,-1,0)); }
    t=(u.light.y-ro.y)/rd.y; p=ro+rd*t;
    if t>EPS && t<h.t && abs(p.x-u.light.x)<=0.9 && abs(p.z-u.light.z)<=0.6 { h=Hit(t,8,vec3f(0,-1,0)); }
  }
  if abs(rd.x)>1e-7 {
    t=(-3.0-ro.x)/rd.x; p=ro+rd*t;
    if t>EPS && t<h.t && p.y>=0.0 && p.y<=4.3 && abs(p.z)<=3.0 { h=Hit(t,1,vec3f(1,0,0)); }
    t=(3.0-ro.x)/rd.x; p=ro+rd*t;
    if t>EPS && t<h.t && p.y>=0.0 && p.y<=4.3 && abs(p.z)<=3.0 { h=Hit(t,2,vec3f(-1,0,0)); }
  }
  if abs(rd.z)>1e-7 {
    t=(-3.0-ro.z)/rd.z; p=ro+rd*t;
    if t>EPS && t<h.t && p.y>=0.0 && p.y<=4.3 && abs(p.x)<=3.0 { h=Hit(t,3,vec3f(0,0,1)); }
  }
  let glass=sphere(ro,rd,vec3f(-1.28,0.85,0.83),0.85,5);
  if glass.t<h.t { h=glass; }
  let stone=sphere(ro,rd,vec3f(0.0,1.03,-0.85),1.03,6);
  if stone.t<h.t { h=stone; }
  let metal=sphere(ro,rd,vec3f(1.34,0.9,0.70),0.9,7);
  if metal.t<h.t { h=metal; }
  return h;
}
fn solid(p:vec3f) -> bool {
  return distance(p,vec3f(-1.28,0.85,0.83))<0.87 ||
    distance(p,vec3f(0,1.03,-0.85))<1.05 || distance(p,vec3f(1.34,0.9,0.70))<0.92;
}
fn baseColor(id:i32,p:vec3f) -> vec3f {
  if id==1 { return vec3f(0.57,0.065,0.038); }
  if id==2 { return vec3f(0.055,0.16,0.40); }
  if id==6 {
    let grain=noise3(p*76.0); let cloud=noise3(p*4.7);
    let fleck=smoothstep(0.50,0.78,noise3(p*130.0));
    let v=clamp(0.27+0.32*grain+0.11*cloud-0.22*fleck,0.08,0.7);
    return vec3f(v*1.04,v,v*0.94);
  }
  if id==0 {
    let grid=0.012*noise3(p*180.0);
    return vec3f(0.64,0.625,0.595)+grid;
  }
  return vec3f(0.64,0.63,0.60);
}
fn alpha(id:i32)->f32 {
  if id==7 { return max(0.0016,u.settings.z*u.settings.z); }
  if id==6 { return max(0.0064,u.settings.w*u.settings.w); }
  return 0.65;
}
fn basis(n:vec3f)->mat3x3f {
  let axis=select(vec3f(0,1,0),vec3f(1,0,0),abs(n.y)>0.9);
  let t=normalize(cross(axis,n)); return mat3x3f(t,cross(n,t),n);
}
fn cosineDirection(n:vec3f)->vec3f {
  let r=sqrt(random()); let phi=2.0*PI*random();
  return basis(n)*vec3f(r*cos(phi),r*sin(phi),sqrt(max(0.0,1.0-r*r)));
}
fn fresnelDielectric(c:f32,eta:f32)->f32 {
  let cosI=clamp(c,0.0,1.0); let sinT2=(1.0-cosI*cosI)/(eta*eta);
  if sinT2>=1.0 { return 1.0; }
  let cosT=sqrt(max(0.0,1.0-sinT2));
  let rP=(eta*cosI-cosT)/(eta*cosI+cosT);
  let rS=(cosI-eta*cosT)/(cosI+eta*cosT);
  return 0.5*(rP*rP+rS*rS);
}
fn fresnelCopper(c:f32)->vec3f {
  // Representative RGB optical constants for copper, not a spectral model.
  let eta=vec3f(0.200,0.924,1.102); let k=vec3f(3.912,2.452,2.142);
  let c2=c*c; let s2=1.0-c2; let t0=eta*eta-k*k-vec3f(s2);
  let ab=sqrt(t0*t0+4.0*eta*eta*k*k);
  let a=sqrt(max(vec3f(0),0.5*(ab+t0)));
  let t1=ab+vec3f(c2); let t2=2.0*c*a;
  let rs=(t1-t2)/(t1+t2);
  let t3=c2*ab+vec3f(s2*s2); let t4=t2*s2;
  let rp=rs*(t3-t4)/(t3+t4);
  return 0.5*(rs+rp);
}
fn ggxD(noH:f32,a:f32)->f32 {
  let a2=a*a; let d=noH*noH*(a2-1.0)+1.0;
  return a2/(PI*d*d);
}
fn ggxG1(noV:f32,a:f32)->f32 {
  if noV<=0.0 { return 0.0; }
  return 2.0*noV/(noV+sqrt(a*a+(1.0-a*a)*noV*noV));
}
fn specProbability(id:i32)->f32 { return select(0.25,1.0,id==7); }
fn brdf(id:i32,p:vec3f,n:vec3f,wo:vec3f,wi:vec3f)->vec3f {
  let nv=dot(n,wo); let nl=dot(n,wi);
  if nv<=0.0 || nl<=0.0 { return vec3f(0); }
  let h=normalize(wo+wi); let nh=max(0.0,dot(n,h)); let vh=max(0.0,dot(wo,h)); let a=alpha(id);
  var f=vec3f(fresnelDielectric(vh,1.5));
  if id==7 { f=fresnelCopper(vh); }
  let spec=f*ggxD(nh,a)*ggxG1(nv,a)*ggxG1(nl,a)/(4.0*nv*nl);
  if id==7 { return spec; }
  // Reciprocal, energy-reducing dielectric diffuse + microfacet reflection.
  let diffuse=baseColor(id,p)/PI*(1.0-fresnelDielectric(nv,1.5))*(1.0-fresnelDielectric(nl,1.5));
  return diffuse+spec;
}
fn bsdfPdf(id:i32,n:vec3f,wo:vec3f,wi:vec3f)->f32 {
  let nv=dot(n,wo); let nl=dot(n,wi);
  if nv<=0.0 || nl<=0.0 { return 0.0; }
  let h=normalize(wo+wi); let a=alpha(id);
  let pSpec=ggxD(max(0.0,dot(n,h)),a)*ggxG1(nv,a)/(4.0*nv);
  let prob=specProbability(id);
  return prob*pSpec+(1.0-prob)*nl/PI;
}
fn sampleGgx(n:vec3f,wo:vec3f,a:f32)->vec3f {
  let b=basis(n); let v=transpose(b)*wo;
  let vh=normalize(vec3f(a*v.x,a*v.y,v.z));
  let lensq=vh.x*vh.x+vh.y*vh.y;
  var t1=vec3f(1,0,0);
  if lensq>1e-8 { t1=vec3f(-vh.y,vh.x,0)/sqrt(lensq); }
  let t2=cross(vh,t1); let r=sqrt(random()); let phi=2.0*PI*random();
  let x=r*cos(phi); var y=r*sin(phi); let s=0.5*(1.0+vh.z);
  y=(1.0-s)*sqrt(max(0.0,1.0-x*x))+s*y;
  let nh=x*t1+y*t2+sqrt(max(0.0,1.0-x*x-y*y))*vh;
  let h=b*normalize(vec3f(a*nh.x,a*nh.y,max(0.0,nh.z)));
  return reflect(-wo,h);
}
fn sampleBsdf(id:i32,n:vec3f,wo:vec3f)->vec3f {
  if random()<specProbability(id) { return sampleGgx(n,wo,alpha(id)); }
  return cosineDirection(n);
}
fn powerHeuristic(a:f32,b:f32)->f32 { return a*a/max(1e-20,a*a+b*b); }
fn lightPdf(p:vec3f,q:vec3f)->f32 {
  let d=q-p; let d2=dot(d,d); let c=abs(d.y)/sqrt(d2);
  return d2/max(1e-9,c*LIGHT_AREA);
}
fn directLight(id:i32,p:vec3f,n:vec3f,wo:vec3f,useMis:bool)->vec3f {
  let q=u.light.xyz+vec3f((random()*2.0-1.0)*0.9,0,(random()*2.0-1.0)*0.6);
  let delta=q-p; let dist=length(delta); let wi=delta/dist;
  if wi.y<=0.0 || dot(wi,n)<=0.0 { return vec3f(0); }
  let block=scene(p+n*EPS*2.0,wi);
  if block.id!=8 { return vec3f(0); }
  let pdf=lightPdf(p,q); var w=1.0;
  if useMis { w=powerHeuristic(pdf,bsdfPdf(id,n,wo,wi)); }
  return brdf(id,p,n,wo,wi)*u.light.w*max(0.0,dot(n,wi))*w/pdf;
}
fn environment(rd:vec3f)->vec3f {
  return mix(vec3f(0.07,0.078,0.09),vec3f(0.18,0.19,0.21),clamp(rd.y*0.5+0.5,0.0,1.0));
}
fn absorption(t:f32)->vec3f { return exp(-vec3f(0.28,0.055,0.16)*u.glass.y*t); }

fn firstBounceRadianceFromHit(firstPoint:vec3f,firstDirection:vec3f,firstHit:Hit)->vec3f {
  var ro=firstPoint;var rd=firstDirection;var value=vec3f(0);var beta=vec3f(1);
  var inGlass=false;var delta=true;var lastPdf=0.0;var lastPoint=ro;
  for(var depth=0u;depth<10u;depth++){
    var hit=firstHit;
    if depth>0u { hit=scene(ro,rd); }
    if hit.id<0 { return value+beta*environment(rd); }
    if inGlass { beta*=absorption(hit.t); }
    let p=ro+rd*hit.t;
    if hit.id==8 {
      // The main integrator samples the emitter directly. Cache only bounced light.
      if depth>0u && dot(rd,hit.normal)<0.0 {
        var w=1.0;if !delta { w=powerHeuristic(lastPdf,lightPdf(lastPoint,p)); }
        value+=beta*u.light.w*w;
      }
      return value;
    }
    let front=dot(rd,hit.normal)<0.0;let n=select(-hit.normal,hit.normal,front);let wo=-rd;
    if hit.id==5 {
      let eta=select(1.0/u.glass.x,u.glass.x,front);let F=fresnelDielectric(dot(wo,n),eta);
      if random()<F { rd=reflect(rd,n); }
      else { rd=refract(rd,n,1.0/eta);beta/=eta*eta;inGlass=front; }
      ro=p+rd*EPS*2.0;delta=true;
    } else if hit.id==7 {
      value+=beta*directLight(hit.id,p,n,wo,true);
      let wi=sampleBsdf(hit.id,n,wo);let pdf=bsdfPdf(hit.id,n,wo,wi);
      if pdf<=1e-10 || dot(n,wi)<=0.0 { return value; }
      beta*=brdf(hit.id,p,n,wo,wi)*max(0.0,dot(n,wi))/pdf;
      lastPoint=p;lastPdf=pdf;delta=false;ro=p+n*EPS*2.0;rd=wi;
    } else {
      // End after the first diffuse interaction: a first-bounce radiance source.
      value+=beta*directLight(hit.id,p,n,wo,false);
      return value;
    }
  }
  return value;
}
fn firstBounceRadiance(firstPoint:vec3f,firstDirection:vec3f)->vec3f {
  return firstBounceRadianceFromHit(firstPoint,firstDirection,scene(firstPoint,firstDirection));
}
