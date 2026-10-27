// Attenuation colour = transmittance after attenuationDistance metres.
// Pickers are sRGB; Beer–Lambert absorption operates in linear light.
export function linearColor(hex){return [1,3,5].map(i=>{const v=parseInt(hex.slice(i,i+2),16)/255;return v<=.04045?v/12.92:((v+.055)/1.055)**2.4;});}
export function absorptionCoefficients(p){return linearColor(p.absorptionColor).map(c=>-Math.log(Math.max(.0001,c))/p.attenuationDistance);}
export function waterTransmission(p,distance){return absorptionCoefficients(p).map(s=>Math.exp(-s*Math.max(0,distance)));}
// Raster-only body approximation. The ray tracer uses water-transport.wgsl:
// refracted BVH rays and absorption along actual segments, never this proxy.
export const WATER_OPTICS_WGSL=`
fn waterIOR()->f32 {return F.viewProj[3].w;}
fn waterFresnel(cosine:f32)->f32 {
 let eta=waterIOR();if abs(eta-1.0)<.00001 {return 0;}
 let c=clamp(abs(cosine),.00001,1.0);let ct=sqrt(max(0.0,1-(1-c*c)/(eta*eta)));
 let a=(c-eta*ct)/(c+eta*ct);let b=(eta*c-ct)/(eta*c+ct);return .5*(a*a+b*b);
}
fn waterBody(shore:f32,cosine:f32)->vec3f {
 let c=clamp(abs(cosine),0.0,1.0);let ct=sqrt(max(.001,1-(1-c*c)/(waterIOR()*waterIOR())));
 let path=clamp(1+shore*.25,1.0,30.0)/max(ct,.1);
 let scattering=max(0.0,F.viewProj[1].z)*.12;
 let extinction=F.viewProj[3].xyz+vec3f(scattering);
 return F.sssCol.rgb*scattering/max(extinction,vec3f(.00001))*(1-exp(-extinction*path));
}
`;
export const WATER_OPTICS_GLSL=`
float waterIOR(){return waterP[6].w;}
float waterFresnel(float cosine){
 float eta=waterIOR();if(abs(eta-1.)<.00001)return 0.;
 float c=clamp(abs(cosine),.00001,1.),ct=sqrt(max(0.,1.-(1.-c*c)/(eta*eta)));
 float a=(c-eta*ct)/(c+eta*ct),b=(eta*c-ct)/(eta*c+ct);return .5*(a*a+b*b);
}
vec3 waterBody(float shore,float cosine){
 float c=clamp(abs(cosine),0.,1.),ct=sqrt(max(.001,1.-(1.-c*c)/(waterIOR()*waterIOR())));
 float path=clamp(1.+shore*.25,1.,30.)/max(ct,.1),scattering=max(0.,waterP[1].w)*.12;
 vec3 extinction=waterP[6].xyz+vec3(scattering);
 return waterP[7].rgb*scattering/max(extinction,vec3(.00001))*(1.-exp(-extinction*path));
}
`;
