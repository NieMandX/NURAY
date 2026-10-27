// Analytic GGX environment BRDF fit (Karis/Lazarov), instead of applying a
// smooth-interface Fresnel directly to a rough surface's environment light.
// https://www.unrealengine.com/blog/physically-based-shading-on-mobile?lang=en-US
// Only dry ground opts in. Direct sun, water and explicit reflective coats
// retain their own BRDFs. Existing sky filtering remains an approximation.
const C0=[-1,-.0275,-.572,.022],C1=[1,.0425,1.04,-.04];
const clamp=v=>Math.max(0,Math.min(1,v));
export function environmentReflectance(noV,roughness,f0=.04){
 const r=C0.map((c,i)=>c*clamp(roughness)+C1[i]);
 const a=Math.min(r[0]*r[0],2**(-9.28*clamp(noV)))*r[0]+r[1];
 return clamp(f0*(-1.04*a+r[2])+1.04*a+r[3]);
}
const vec=(type,a)=>`${type}(${a.map(v=>Number.isInteger(v)?v+'.0':v).join(',')})`;
export const ENVIRONMENT_BRDF_WGSL=`
fn environmentBRDF(noV:f32,roughness:f32,f0:vec3f)->vec3f {
 let r=clamp(roughness,0.0,1.0)*${vec('vec4f',C0)}+${vec('vec4f',C1)};
 let a=min(r.x*r.x,exp2(-9.28*clamp(noV,0.0,1.0)))*r.x+r.y;
 let ab=vec2f(-1.04,1.04)*a+r.zw;
 return clamp(f0*ab.x+ab.y,vec3f(0),vec3f(1));
}
`;
export const ENVIRONMENT_BRDF_GLSL=`
vec3 environmentBRDF(float noV,float roughness,vec3 f0){
 vec4 r=clamp(roughness,0.,1.)*${vec('vec4',C0)}+${vec('vec4',C1)};
 float a=min(r.x*r.x,exp2(-9.28*clamp(noV,0.,1.)))*r.x+r.y;
 vec2 ab=vec2(-1.04,1.04)*a+r.zw;
 return clamp(f0*ab.x+ab.y,vec3(0),vec3(1));
}
`;
