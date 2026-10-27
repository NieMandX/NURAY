// Shared path transport for reference rays and radiance-cascade sources.
fn meshTransport(origin:vec3f,direction:vec3f,first:MeshHit,cacheSource:bool)->vec3f {
  var ro=origin;var rd=direction;var radiance=vec3f(0);var beta=vec3f(1);var inside=false;var inWater=pointInWater(origin);
  var etaScale=1.0;var delta=true;var lastPdf=0.0;var travel=0.0;
  let maxBounces=select(u32(u.glass.w),min(6u,u32(u.glass.w)),cacheSource);
  for(var bounce=0u;bounce<maxBounces;bounce++){
    // Roulette also applies to volume scattering events (which continue below).
    if bounce>=4u {
      let rr=beta*etaScale;let survival=clamp(max(rr.x,max(rr.y,rr.z)),.05,.95);
      if random()>survival {break;}beta/=survival;
    }
    var hit=first;if bounce>0u {hit=traceMesh(ro,rd,false);}
    if inWater&&!inside {
      let medium=sampleWaterMedium(hit.t);beta*=medium.weight;
      if max(beta.x,max(beta.y,beta.z))<1e-20 {break;}
      if medium.scatter {
        ro+=rd*medium.distance;travel+=medium.distance;
        rd=isotropicDirection();delta=false;lastPdf=1/(4*PI);continue;
      }
      // Missing bathymetry is an open volume, never a fictitious floor or sky.
      if hit.t>=INF {break;}
    }
    if hit.t>=INF {
      var weight=1.0;if !delta {weight=powerHeuristic(lastPdf,skyPdf(rd));}
      radiance+=beta*meshSky(rd)*weight;break;
    }
    travel+=hit.t;if inside {beta*=exp(-vec3f(.28,.055,.16)*hit.t);}
    let p=ro+rd*hit.t;let m=meshSurface(hit,travel,p);let front=dot(rd,m.normal)<0;let n=select(-m.normal,m.normal,front);let wo=-rd;
    if m.kind==12u {
      let geometry=meshGeometricNormal(hit);let frontWater=dot(rd,geometry)<0;
      let ng=select(-geometry,geometry,frontWater);
      var wn=select(-m.normal,m.normal,frontWater);
      if dot(wo,wn)<=.001 {wn=ng;}
      let eta=waterEta(!frontWater);
      // Next-event estimation is only used on the air side. A submerged
      // surface reaches sunlight by a real ray to the refracting interface.
      let wi=sampleSky();let nextInWater=select(!frontWater,frontWater,dot(ng,wi)<0);
      if !nextInWater&&traceMesh(rayOffset(p,ng,wi),wi,true).t>=INF {
        let e=waterEvaluate(m,wn,wo,wi,eta);let pdf=skyPdf(wi);
        let w=select(powerHeuristic(pdf,e.pdf),1.0,bounce+1u>=maxBounces);
        radiance+=beta*e.f*abs(dot(wn,wi))*meshSky(wi)*w/pdf;
      }
      let next=sampleWaterInterface(m,wn,ng,wo,eta);
      if next.pdf<=0 {break;}
      beta*=next.weight;rd=next.direction;
      if next.transmitted {inWater=frontWater;etaScale*=eta*eta;}
      ro=rayOffset(p,ng,rd);lastPdf=next.pdf;delta=next.delta;
    }else if m.kind==4u {
      let relative=m.ior/select(1.0,waterIndex(),inWater);let eta=select(1.0/relative,relative,front);let F=fresnelDielectric(max(0.0,dot(wo,n)),eta);
      if random()<F {rd=reflect(rd,n);}
      else {rd=refract(rd,n,1.0/eta);beta/=eta*eta;etaScale*=eta*eta;inside=front;}
      ro=p+rd*EPS*2.0;delta=true;
    }else{
      var gather=vec4f(0);
      if !cacheSource&&!inWater&&u.settings.w>.5 && u.settings.y>.5 && m.metal<.5&&m.kind!=12u && bounce+1u<maxBounces {gather=cachedIrradiance(p,n);}
      let cached=gather.a>.5;
      if cached {radiance+=beta*m.color*(1-m.metal)*(1-fresnelDielectric(max(0.0,dot(n,wo)),m.ior))*gather.rgb/PI;}
      let wi=sampleSky();let cosine=max(0.0,dot(n,wi));
      if !inWater&&cosine>0.0&&traceMesh(p+n*EPS*2.0,wi,true).t>=INF {
        let pdf=skyPdf(wi);var w=powerHeuristic(pdf,meshPdf(m,n,wo,wi));
        if ((cacheSource||u.settings.y<.5)&&m.metal<.5&&m.kind!=12u)||bounce+1u>=maxBounces {w=1.0;}
        var contribution=meshBrdf(m,n,wo,wi)*w;
        if cached {
          let diffuse=diffuseBrdf(m,n,wo,wi);
          contribution=diffuse+(meshBrdf(m,n,wo,wi)-diffuse)*powerHeuristic(pdf,.25*specPdf(m,n,wo,wi));
        }
        radiance+=beta*contribution*meshSky(wi)*cosine/pdf;
      }
      if (cacheSource||u.settings.y<.5)&&m.metal<.5&&!inWater {break;}
      if cached {
        // Keep coating reflections as actual rays; cache replaces only diffuse transport.
        if random()>=.25 {break;}
        let next=sampleGgx(n,wo,max(.002,m.rough*m.rough));let pdf=.25*specPdf(m,n,wo,next);
        if pdf<1e-10||dot(n,next)<=0 {break;}
        beta*=max(vec3f(0),meshBrdf(m,n,wo,next)-diffuseBrdf(m,n,wo,next))*max(0.0,dot(n,next))/pdf;
        ro=p+n*EPS*2;rd=next;lastPdf=pdf;delta=false;
      }else{
      var next=vec3f(0);if random()<meshSpecProbability(m){next=sampleGgx(n,wo,max(.002,m.rough*m.rough));}else{next=cosineDirection(n);}
      let pdf=meshPdf(m,n,wo,next);if pdf<1e-10||dot(n,next)<=0 {break;}
      beta*=meshBrdf(m,n,wo,next)*max(0.0,dot(n,next))/pdf;
      ro=p+n*EPS*2.0;rd=next;lastPdf=pdf;delta=false;
      }
    }

  }
  return max(radiance,vec3f(0));
}
