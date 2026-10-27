// Adapted from “Seascape” © Alexander Alekseev (TDM), 2014.
// CC BY-NC-SA 3.0; see PROVENANCE.md and Seascape.original.glsl.
export const SEASCAPE_SKY_GLSL=`
vec3 seaSky(vec3 d,vec3 sun){
 float y=(max(d.y,0.)*.8+.2)*.8;
 return vec3(pow(1.-y,2.),1.-y,.6+(1.-y)*.4)*1.1*mix(.025,1.,smoothstep(-.08,.12,sun.y));
}
vec3 seaGrade(vec3 color,float exposure){return clamp(pow(max(color*exposure,vec3(0)),vec3(.65)),0.,1.);}
`;
export const SEASCAPE_GLSL=SEASCAPE_SKY_GLSL+`
float seaHash(vec2 p){return fract(sin(dot(p,vec2(127.1,311.7)))*43758.5453123);}
float seaNoise(vec2 p){
 vec2 i=floor(p),f=fract(p),u=f*f*(3.-2.*f);
 return -1.+2.*mix(mix(seaHash(i),seaHash(i+vec2(1,0)),u.x),mix(seaHash(i+vec2(0,1)),seaHash(i+vec2(1,1)),u.x),u.y);
}
float seaOctave(vec2 p,float choppy){
 vec2 uv=p+seaNoise(p),w=1.-abs(sin(uv)),sw=abs(cos(uv)),wave=mix(w,sw,w);
 return pow(max(0.,1.-pow(wave.x*wave.y,.65)),choppy);
}
float seaHeight(vec2 p,float footprint){
 vec4 params=waterP[4];vec2 wd=vec2(cos(waterP[0].y),sin(waterP[0].y));
 vec2 uv=vec2(dot(p,wd)*.75,dot(p,vec2(-wd.y,wd.x)));
 float freq=params.y,amp=params.x,choppy=params.z,height=0.,wavelength=1.;
 float time=1.+waterTime*params.w;
 for(int i=0;i<5;i++){
  float aa=1.-smoothstep(.6,2.4,footprint*freq*wavelength);
  float d=seaOctave((uv+time)*freq,choppy)+seaOctave((uv-time)*freq,choppy);
  height+=d*amp*aa;
  uv=vec2(uv.x*1.6+uv.y*1.2,-uv.x*1.2+uv.y*1.6);freq*=1.9;amp*=.22;wavelength*=2.;choppy=mix(choppy,1.,.2);
 }
 return height;
}
`;
// Appended after the environment/shore functions so declarations are available.
export const SEASCAPE_SHADE_GLSL=`
vec3 seascapeShade(vec3 world,vec3 eye,float shore,float shadow){
 float footprint=max(length(dFdx(world).xz),length(dFdy(world).xz)),eps=max(.025,footprint*.5);
 float h=seaHeight(world.xz,footprint);
 vec3 n=normalize(vec3(h-seaHeight(world.xz+vec2(eps,0),footprint),eps,h-seaHeight(world.xz+vec2(0,eps),footprint)));
 float dist=length(eye);eye=normalize(eye);
 float fr=waterFresnel(dot(n,-eye));
 vec3 reflected=waterSky(reflect(eye,n),.08),waterColor=waterP[7].rgb;
 vec3 sunColor=waterSunColor()*sunPower*.4;
 float diffuse=pow(max(dot(n,sun)*.4+.6,0.),80.);
 vec3 base=waterBody(shore,dot(n,-eye));
 vec3 refracted=base*(waterAmbient(n)*2.)+diffuse*waterColor*.12*sunColor*shadow;
 vec3 color=mix(refracted,reflected,fr);
 float atten=max(1.-dist*dist*.00001,0.);
 color+=waterColor*(h-waterP[4].x)*.18*atten;
 float power=max(12.,600./sqrt(max(dist,1.)));
 color+=pow(max(dot(reflect(eye,n),sun),0.),power)*(power+8.)/(3.14159265*8.)*sunColor*shadow*waterFresnel(dot(n,-eye));
 float coast=waterFoam(world.xz,shore,waterTime,footprint)*waterP[2].y;
 float crest=smoothstep(1.65,2.3,h/max(waterP[4].x,.001))*waterP[2].x*.15;
 vec3 foamLight=vec3(.65,.68,.66)*(waterAmbient(n)+sunColor*max(dot(n,sun),0.)*shadow*.3);
 return max(mix(color,foamLight,clamp(coast+crest,0.,.75)),vec3(0));
}
`;
