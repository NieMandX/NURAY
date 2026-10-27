// Port of the reference Hosek–Wilkie 1.4a equations, BSD-3-Clause.
// See vendor/ArHosekSkyModel.c and PROVENANCE.md for source and units.
import {HOSEK_DATA as D} from './data.js?v=moscow-defaults-1';
export const SUN_RADIUS=.51*Math.PI/360;
export const RADIANCE_SCALE=.04; // Fixed scene-unit conversion; never renormalize by sun elevation.
const clamp=(x,a,b)=>Math.max(a,Math.min(b,x));
const mix=(a,b,t)=>a*(1-t)+b*t;
const xyzToRGB=([x,y,z])=>[3.2404542*x-1.5371385*y-.4985314*z,-.969266*x+1.8760108*y+.041556*z,.0556434*x-.2040259*y+1.0572252*z];
function cook(table,stride,turbidity,albedo,elevation){
 const t=Math.cbrt(elevation/(Math.PI/2)),b=[(1-t)**5,5*(1-t)**4*t,10*(1-t)**3*t*t,10*(1-t)**2*t**3,5*(1-t)*t**4,t**5];
 const low=Math.floor(turbidity)-1,high=Math.min(9,low+1),f=turbidity-low-1;
 return Array.from({length:stride},(_,i)=>{
  let v=0;for(let a=0;a<2;a++)for(let q=0;q<2;q++)for(let k=0;k<6;k++)v+=table[((a*10+(q?high:low))*6+k)*stride+i]*b[k]*(a?albedo:1-albedo)*(q?f:1-f);
  return v;
 });
}
export function createHosek(turbidity=3,albedo=.2,elevation=Math.PI/4){
 turbidity=clamp(turbidity,1,10);albedo=clamp(albedo,0,1);elevation=clamp(elevation,0,Math.PI/2);
 return {turbidity,albedo,elevation,configs:D.configs.map(t=>cook(t,9,turbidity,albedo,elevation)),radiances:D.radiances.map(t=>cook(t,1,turbidity,albedo,elevation)[0])};
}
export function skyRadiance(model,theta,gamma){
 const c=Math.max(0,Math.cos(theta)),g=Math.cos(gamma);
 return model.configs.map((a,i)=>(1+a[0]*Math.exp(a[1]/(c+.01)))*(a[2]+a[3]*Math.exp(a[4]*gamma)+a[5]*g*g+a[6]*(1+g*g)/(1+a[8]*a[8]-2*a[8]*g)**1.5+a[7]*Math.sqrt(c))*model.radiances[i]);
}
function solarSpline(t,wl,e){
 const p=Math.min(44,Math.floor(Math.cbrt(2*e/Math.PI)*45)),x=e-(p/45)**3*Math.PI/2,o=t*180+p*4;
 return ((D.solar[wl][o]*x+D.solar[wl][o+1])*x+D.solar[wl][o+2])*x+D.solar[wl][o+3];
}
export function solarCoefficients(model,wavelength){
 const w=clamp((wavelength-320)/40,0,10),wl=Math.min(9,Math.floor(w)),f=w-wl,t=Math.min(8,Math.floor(model.turbidity)-1),tf=model.turbidity-t-1;
 const L=mix(mix(solarSpline(t,wl,model.elevation),solarSpline(t,wl+1,model.elevation),f),mix(solarSpline(t+1,wl,model.elevation),solarSpline(t+1,wl+1,model.elevation),f),tf);
 return D.limb[wl].map((a,i)=>L*mix(a,D.limb[wl+1][i],f));
}
export function solarRadiance(model,wavelength,gamma=0){
 if(gamma>SUN_RADIUS)return 0;
 const mu=Math.sqrt(Math.max(0,1-(Math.sin(gamma)/Math.sin(SUN_RADIUS))**2));
 return solarCoefficients(model,wavelength).reduce((s,c,i)=>s+c*mu**i,0);
}
function sunRGB(model){
 const xyz=Array.from({length:6},()=>[0,0,0]);
 // 1 nm trapezoidal integration; source solar data spans 320–720 nm.
 // CIE table starts at 360 nm. No extrapolation beyond the model domain.
 for(let w=360;w<=720;w++){
  const c=solarCoefficients(model,w),weight=w===360||w===720?.5:1;
  for(let i=0;i<6;i++)for(let j=0;j<3;j++)xyz[i][j]+=c[i]*D.cie[w-360][j]*weight;
 }
 return xyz.map(xyzToRGB);
}
export function shBasis([x,y,z]){return [.2820947918,.4886025119*x,.4886025119*y,.4886025119*z,1.0925484306*x*y,1.0925484306*y*z,.3153915653*(3*z*z-1),1.0925484306*x*z,.5462742153*(x*x-y*y)];}
export function hosekUniforms(sun,p){
 const length=Math.hypot(...sun);sun=sun.map(x=>x/length);const elevation=Math.asin(clamp(sun[1],-1,1));
 const model=createHosek(p.hwTurbidity,p.hwAlbedo,elevation),limb=sunRGB(model);
 // The model is daytime-only. Below the horizon, fade the horizon solution
 // without evaluating its fit outside the supported elevation range.
 const day=clamp(1+elevation/(Math.PI/30),0,1),scale=RADIANCE_SCALE*day;
 const visible=elevation>=SUN_RADIUS?1:elevation<=-SUN_RADIUS?0:(Math.acos(-elevation/SUN_RADIUS)+(elevation/SUN_RADIUS)*Math.sqrt(1-(elevation/SUN_RADIUS)**2))/Math.PI;
 const direct=[0,1,2].map(c=>Math.max(0,limb.reduce((s,x,i)=>s+x[c]*2/(i+2),0)*Math.PI*Math.sin(SUN_RADIUS)**2*visible*scale));
 const samples=512,hemisphere=[],irr=[0,0,0];
 for(let i=0;i<samples;i++){
  const y=(i+.5)/samples,a=i*2.399963229728653,r=Math.sqrt(1-y*y),d=[Math.cos(a)*r,y,Math.sin(a)*r];
  const L=skyRadiance(model,Math.acos(y),Math.acos(clamp(d.reduce((s,x,j)=>s+x*sun[j],0),-1,1))).map(x=>Math.max(0,x)*scale);
  for(let c=0;c<3;c++)irr[c]+=L[c]*y*2*Math.PI/samples;
  hemisphere.push([d,L]);
 }
 const ground=irr.map((x,c)=>(x+direct[c]*Math.max(0,sun[1]))*model.albedo/Math.PI),sh=Array.from({length:9},()=>[0,0,0]);
 for(const [d,L] of hemisphere)for(const [dir,color] of [[d,L],[[d[0],-d[1],d[2]],ground]]){
  const b=shBasis(dir);for(let i=0;i<9;i++)for(let c=0;c<3;c++)sh[i][c]+=b[i]*color[c]*2*Math.PI/samples*(i===0?1:i<4?2/3:1/4);
 }
 const data=new Float32Array(112);
 for(let i=0;i<9;i++)data.set(model.configs.map(c=>c[i]),i*4);
 data.set(model.radiances.map(x=>x*scale),36);sh.forEach((x,i)=>data.set(x,(10+i)*4));data.set(direct,76);data.set(ground,80);
 limb.forEach((x,i)=>data.set(x.map(v=>v*scale),(21+i)*4));data.set([p.hwExposure,p.hwSkyIntensity/100,SUN_RADIUS,visible],108);
 return data;
}
export class HosekCache {
 update(sun,p){const key=JSON.stringify([sun,p.hwTurbidity,p.hwAlbedo,p.hwExposure,p.hwSkyIntensity]);if(key!==this.key){this.key=key;this.data=hosekUniforms(sun,p);}return this.data;}
}
