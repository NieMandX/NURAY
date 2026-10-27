// Homogeneous water transport in scene metres. No shore-distance/depth proxy.
// Water mesh winding defines the air/medium boundary; shading waves affect the
// dielectric BSDF, never the medium-side test or the ray-origin offset.
fn rayOffset(p:vec3f,n:vec3f,wi:vec3f)->vec3f {
  let e=max(EPS*2,max(abs(p.x),max(abs(p.y),abs(p.z)))*2e-7);
  return p+n*select(-e,e,dot(n,wi)>=0);
}
fn pointInWater(p:vec3f)->bool {
  if !cityHasWater() {return false;}
  // Ignore bridges/boats/opaque objects above an underwater camera.
  let h=traceMeshFiltered(p,vec3f(0,1,0),false,INF,true);
  if h.t>=INF {return false;}return meshGeometricNormal(h).y>0;
}
fn waterAbsorb(distance:f32)->vec3f {return exp(-waterAbsorption()*distance);}
struct MediumSample { distance:f32,weight:vec3f,scatter:bool };
fn sampleWaterMedium(limit:f32)->MediumSample {
  let rate=waterScatteringRate();var distance=INF;
  // Sample scattering only; absorption is integrated analytically along every
  // actual ray segment. This avoids RGB channel sampling noise in clear water.
  if rate>0 {distance=-log(max(1e-7,1-random()))/rate;}
  let event=distance<limit;distance=min(distance,limit);
  var weight=waterAbsorb(distance);
  if event {weight*=waterScatteringTint();}
  return MediumSample(distance,weight,event);
}
fn isotropicDirection()->vec3f {
  let y=1-2*random();let a=2*PI*random();let r=sqrt(max(0.0,1-y*y));return vec3f(r*cos(a),y,r*sin(a));
}
fn waterEta(under:bool)->f32 {return select(waterIndex(),1/waterIndex(),under);}
fn interfaceFresnel(c:f32,eta:f32)->f32 {
  if abs(eta-1)<1e-6 {return 0;}
  return fresnelDielectric(abs(c),eta);
}
// Deep water absorbs most transmission paths. Reserve at least half of the
// non-foam samples for reflection; the PDF compensates, so Fresnel energy is
// unchanged. Sampling reflection with F≈0.02 otherwise causes salt-and-pepper
// noise across the map at the interactive 32-sample budget.
fn waterReflectionProbability(fr:f32)->f32 {return max(.5,fr);}
struct WaterEvaluation { f:vec3f,pdf:f32 };
fn waterEvaluate(m:Surface,n:vec3f,wo:vec3f,wi:vec3f,eta:f32)->WaterEvaluation {
  let nv=dot(n,wo);let nl=dot(n,wi);var f=vec3f(0);var pdf=0.0;
  if nv<=0||abs(nl)<1e-7 {return WaterEvaluation(f,pdf);}
  let reflection=nl>0;let coverage=m.foam;
  if reflection {f=coverage*vec3f(.65,.68,.66)/PI;pdf=coverage*nl/PI;}
  // IOR=1 is a delta transmission, accounted for separately by the sampler.
  if abs(eta-1)<1e-6 {return WaterEvaluation(f,pdf);}
  var h=wo+wi*select(eta,1.0,reflection);
  if dot(h,h)<1e-12 {return WaterEvaluation(f,pdf);}
  h=normalize(h);if dot(h,n)<0 {h=-h;}
  let oh=dot(wo,h);let ih=dot(wi,h);
  if oh<=0||ih*nl<=0 {return WaterEvaluation(f,pdf);}
  let a=max(.002,m.rough*m.rough);let d=ggxD(max(0.0,dot(n,h)),a);
  let g1=ggxG1(nv,a);let g=g1*ggxG1(abs(nl),a);
  let fr=interfaceFresnel(oh,eta);let pr=waterReflectionProbability(fr);let visible=d*g1*oh/nv;
  if reflection {
    f+=(1-coverage)*vec3f(fr*d*g/(4*nv*nl));
    pdf+=(1-coverage)*pr*visible/(4*oh);
  }else{
    let denom=(oh+eta*ih)*(oh+eta*ih);
    if denom>1e-14 {
      // Radiance transport: the eta^2 BTDF Jacobian cancels eta^-2.
      f=(1-coverage)*vec3f((1-fr)*d*g*abs(oh*ih)/(nv*abs(nl)*denom));
      pdf=(1-coverage)*(1-pr)*visible*abs(ih)*eta*eta/denom;
    }
  }
  return WaterEvaluation(f,pdf);
}
struct WaterSample { direction:vec3f,weight:vec3f,pdf:f32,transmitted:bool,delta:bool };
fn sampleWaterInterface(m:Surface,n:vec3f,ng:vec3f,wo:vec3f,eta:f32)->WaterSample {
  var wi=vec3f(0);var transmitted=false;
  if random()<m.foam {wi=cosineDirection(n);}
  else if abs(eta-1)<1e-6 {return WaterSample(-wo,vec3f(1),1-m.foam,true,true);}
  else {
    let h=sampleGgxNormal(n,wo,max(.002,m.rough*m.rough));
    if random()<waterReflectionProbability(interfaceFresnel(dot(wo,h),eta)) {wi=reflect(-wo,h);}
    else {wi=refract(-wo,h,1/eta);transmitted=true;}
  }
  if dot(wi,wi)<.5||select(dot(wi,ng)<=0,dot(wi,ng)>=0,transmitted) {
    return WaterSample(wi,vec3f(0),0,false,false);
  }
  wi=normalize(wi);let e=waterEvaluate(m,n,wo,wi,eta);
  if e.pdf<1e-12 {return WaterSample(wi,vec3f(0),0,false,false);}
  return WaterSample(wi,e.f*abs(dot(n,wi))/e.pdf,e.pdf,transmitted,false);
}
