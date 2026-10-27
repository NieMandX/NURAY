// Hosek–Wilkie 1.4a analytic sky. Coefficients and spectral sun are cooked on CPU.
// Source attribution and license: PROVENANCE.md, vendor/ArHosekSkyModel.c.
export const HOSEK_GLSL=`
uniform vec4 hwP[28];
vec3 hwSky(vec3 d,vec3 sun){
 if(d.y<0.)return hwP[20].rgb*hwP[27].y;
 float ct=max(d.y,0.),cg=clamp(dot(d,sun),-1.,1.),g=acos(cg);
 vec3 mie=(1.+cg*cg)/pow(max(vec3(.0001),vec3(1)+hwP[8].rgb*hwP[8].rgb-2.*hwP[8].rgb*cg),vec3(1.5));
 return max(vec3(0),(vec3(1)+hwP[0].rgb*exp(hwP[1].rgb/(ct+.01)))*(hwP[2].rgb+hwP[3].rgb*exp(hwP[4].rgb*g)+hwP[5].rgb*cg*cg+hwP[6].rgb*mie+hwP[7].rgb*sqrt(ct))*hwP[9].rgb)*hwP[27].y;
}
vec3 hwAmbient(vec3 n){
 float x=n.x,y=n.y,z=n.z;
 return max(vec3(0),hwP[10].rgb*.2820947918+hwP[11].rgb*(.4886025119*x)+hwP[12].rgb*(.4886025119*y)+hwP[13].rgb*(.4886025119*z)+hwP[14].rgb*(1.0925484306*x*y)+hwP[15].rgb*(1.0925484306*y*z)+hwP[16].rgb*(.3153915653*(3.*z*z-1.))+hwP[17].rgb*(1.0925484306*x*z)+hwP[18].rgb*(.5462742153*(x*x-y*y)))*hwP[27].y;
}
vec3 hwEnvironment(vec3 d,vec3 sun,float rough){return mix(hwSky(d,sun),hwAmbient(d),rough*rough);}
vec3 hwDisc(vec3 d,vec3 sun,float angularPixel){
 float radius=hwP[27].z,angle=acos(clamp(dot(d,sun),-1.,1.));
 float aa=max(angularPixel*.5,.000001),cover=1.-smoothstep(radius-aa,radius+aa,angle);
 float mu=sqrt(max(0.,1.-pow(sin(min(angle,radius))/sin(radius),2.)));
 vec3 L=hwP[26].rgb;for(int i=25;i>=21;i--)L=L*mu+hwP[i].rgb;
 return max(vec3(0),L)*cover*smoothstep(-aa,aa,d.y);
}
vec3 hwGrade(vec3 light){vec3 x=max(vec3(0),light*hwP[27].x);x=clamp((x*(2.51*x+.03))/(x*(2.43*x+.59)+.14),vec3(0),vec3(1));return mix(1.055*pow(x,vec3(1./2.4))-.055,x*12.92,lessThanEqual(x,vec3(.0031308)));}
`;
export function hosekWGSL(group,binding){return `
struct HosekUniform { p:array<vec4f,28> };
@group(${group}) @binding(${binding}) var<uniform> HW:HosekUniform;
fn hwSky(d:vec3f,sun:vec3f)->vec3f {
 if d.y<0 {return HW.p[20].rgb*HW.p[27].y;}
 let ct=max(d.y,0.0);let cg=clamp(dot(d,sun),-1.0,1.0);let g=acos(cg);
 let mie=(1+cg*cg)/pow(max(vec3f(.0001),vec3f(1)+HW.p[8].rgb*HW.p[8].rgb-2*HW.p[8].rgb*cg),vec3f(1.5));
 return max(vec3f(0),(vec3f(1)+HW.p[0].rgb*exp(HW.p[1].rgb/(ct+.01)))*(HW.p[2].rgb+HW.p[3].rgb*exp(HW.p[4].rgb*g)+HW.p[5].rgb*cg*cg+HW.p[6].rgb*mie+HW.p[7].rgb*sqrt(ct))*HW.p[9].rgb)*HW.p[27].y;
}
fn hwAmbient(n:vec3f)->vec3f {
 let x=n.x;let y=n.y;let z=n.z;
 return max(vec3f(0),HW.p[10].rgb*.2820947918+HW.p[11].rgb*(.4886025119*x)+HW.p[12].rgb*(.4886025119*y)+HW.p[13].rgb*(.4886025119*z)+HW.p[14].rgb*(1.0925484306*x*y)+HW.p[15].rgb*(1.0925484306*y*z)+HW.p[16].rgb*(.3153915653*(3*z*z-1))+HW.p[17].rgb*(1.0925484306*x*z)+HW.p[18].rgb*(.5462742153*(x*x-y*y)))*HW.p[27].y;
}
fn hwEnvironment(d:vec3f,sun:vec3f,rough:f32)->vec3f {return mix(hwSky(d,sun),hwAmbient(d),rough*rough);}
fn hwDisc(d:vec3f,sun:vec3f,angularPixel:f32)->vec3f {
 let radius=HW.p[27].z;let angle=acos(clamp(dot(d,sun),-1.0,1.0));
 let aa=max(angularPixel*.5,.000001);let cover=1-smoothstep(radius-aa,radius+aa,angle);
 let mu=sqrt(max(0.0,1-pow(sin(min(angle,radius))/sin(radius),2.0)));
 var L=HW.p[26].rgb;for(var i=25;i>=21;i--){L=L*mu+HW.p[i].rgb;}
 return max(vec3f(0),L)*cover*smoothstep(-aa,aa,d.y);
}
fn hwGrade(light:vec3f)->vec3f {var x=max(vec3f(0),light*HW.p[27].x);x=clamp((x*(2.51*x+.03))/(x*(2.43*x+.59)+.14),vec3f(0),vec3f(1));return select(1.055*pow(x,vec3f(1/2.4))-.055,x*12.92,x<=vec3f(.0031308));}
`;}
