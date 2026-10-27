import {HOSEK_GLSL} from '../../src/district/hosek/shaders.js?v=moscow-defaults-1';
import {SEASCAPE_GLSL,SEASCAPE_SHADE_GLSL} from '../../src/district/seascape/seascape-glsl.js?v=moscow-defaults-1';
import {WATER_OPTICS_GLSL} from '../../src/district/ocean/optics.js?v=moscow-defaults-1';
export const surfaceFunctions=`
uniform sampler2D surfaceField;
uniform float waterTime;
uniform vec4 waterP[8]; // [6] absorption / IOR, [7] scattering colour
${WATER_OPTICS_GLSL}
${SEASCAPE_GLSL}
${HOSEK_GLSL}
vec4 field(uint i){uint w=uint(textureSize(surfaceField,0).x);return texelFetch(surfaceField,ivec2(int(i%w),int(i/w)),0);}
float waterHash(vec2 p) {return fract(sin(dot(p,vec2(127.1,311.7)))*43758.5453);}
float waterNoise(vec2 p) {
 vec2 i=floor(p);vec2 f=fract(p);vec2 u=f*f*(3.0-2.0*f);
 return mix(mix(waterHash(i),waterHash(i+vec2(1.0,0.0)),u.x),mix(waterHash(i+vec2(0.0,1.0)),waterHash(i+vec2(1.0,1.0)),u.x),u.y);
}
// An exact segment distance inside a coarse spatial index: no tile-edge foam.
float surfaceDistance(vec3 p,bool road) {
 vec4 grid=field(0u);ivec2 cell=ivec2(floor((p.xz-grid.xy)/grid.z));int rows=int(field(1u).x);
 if(any(lessThan(cell,ivec2(0.0)))||cell.x>=int(grid.w)||cell.y>=rows){return 100.0;}
 vec4 header=field(2u+uint(cell.y)*uint(grid.w)+uint(cell.x));vec2 entry=road?header.zw:header.xy;
 float best=100.0;float fallback=100.0;
 for(uint i=0u;i<uint(entry.y);i++){
  uint address=uint(field(uint(entry.x)+i/4u)[i%4u]);vec4 a=field(address),b=field(address+1u);vec2 delta=a.zw-a.xy;
  float t=clamp(dot(p.xz-a.xy,delta)/max(dot(delta,delta),.0001),0.0,1.0);
  if(road&&abs(p.y-mix(b.x,b.y,t))>.65){continue;}
  float distance=length(p.xz-mix(a.xy,a.zw,t));
  if(b.z<1.5){best=min(best,distance);}else{fallback=min(fallback,distance);}
 }
 if(road&&best>3.4){return fallback;}
 return best;
}
// Sum incommensurate travelling waves; a large-scale wind field controls
// their slope and roughness. Coordinates are global metres, never tile UVs.
vec3 waterShape(vec2 p,float time,float footprint) {
 float speed=waterP[0].x,dir=waterP[0].y,fetch=waterP[0].z,choppy=waterP[0].w;
 float gust=mix(.35,1.2,smoothstep(.25,.75,waterNoise(p*.011+vec2(time*.0004))));
 vec2 slope=vec2(0);float height=0.;
 for(int i=0;i<12;i++){
  float f=float(i),angle=dir+sin(f*7.13)*.65,k=exp2(f*.72-4.0),amp=(.012+speed*.004)*pow(k,-.38)*min(1.,sqrt(fetch/90.));
  vec2 d=vec2(cos(angle),sin(angle));float phase=dot(p,d)*k-sqrt(9.81*k)*time+f*5.17;
  float aa=1.-smoothstep(.8,2.8,k*footprint);slope+=d*cos(phase)*amp*aa*gust*(.5+.5*choppy);height+=sin(phase)*amp/max(k,.1);
 }
 float ks=6.283185/max(waterP[1].y,1.);vec2 sd=vec2(cos(waterP[1].z),sin(waterP[1].z));float phase=dot(p,sd)*ks-sqrt(9.81*ks)*time;
 slope+=sd*cos(phase)*waterP[1].x*ks*.5*(.5+.5*choppy);height+=sin(phase)*waterP[1].x*.5;
 return vec3(slope,height);
}
float seaLightWeight(){return waterP[3].y>2.5?waterP[3].w:(waterP[3].y>1.5?1.:0.);}
float sunVisibility(float raw){return 1.-(1.-raw)*min(waterP[5].z,1.);}
float shadowFill(float raw){return mix(mix(1.,.35,clamp(waterP[5].z-1.,0.,1.)),1.,raw);}
vec3 waterSunColor(){
 if(waterP[3].y>3.5)return hwP[19].rgb*waterP[5].y;
 if(waterP[3].y>.5)return mix(vec3(4.2,3.77,3.1),vec3(2.5),seaLightWeight())*waterP[5].y;
 float h=max(sun.y,.025),haze=waterP[2].z;return vec3(5.2,5.,4.7)*exp(-vec3(.025,.055,.11)*(1.+haze*.15)/h)*waterP[5].y;
}
vec3 waterAmbient(vec3 n){if(waterP[3].y>3.5)return hwAmbient(n);return mix(mix(vec3(.17,.18,.20),vec3(.45,.51,.58),n.y*.5+.5),seaSky(normalize(vec3(n.x,max(n.y,.15),n.z)),sun)*.55,seaLightWeight());}
vec3 waterSky(vec3 d,float rough){
 if(waterP[3].y>3.5)return hwEnvironment(d,sun,rough);
 if(waterP[3].y>.5){
  vec3 s=mix(vec3(.26,.25,.21),vec3(.55,.71,.90),smoothstep(-.15,.7,d.y));
  float glare=pow(max(0.,dot(d,sun)),mix(900.,5.,rough*rough));
  return mix(s+vec3(1.,.88,.66)*glare*mix(3.,.12,rough)*sunPower*waterP[5].y,seaSky(d,sun),seaLightWeight());
 }
 float height=max(d.y,.02),haze=waterP[2].z,day=smoothstep(-.10,.15,sun.y);
 vec3 zenith=mix(vec3(.10,.23,.43),vec3(.38,.46,.53),clamp(haze/20.,0.,1.));
 vec3 horizon=mix(vec3(.55,.68,.78),vec3(.86,.55,.30),pow(1.-max(sun.y,0.),6.));
 vec3 sky=mix(horizon,zenith,pow(clamp(height,0.,1.),.38));
 vec2 q=d.xz/max(height,.07)*1.7+vec2(waterTime*.002,0.);
 float cloud=waterNoise(q)*.65+waterNoise(q*2.7)*.35;
 float cover=smoothstep(1.-waterP[2].w,.98-waterP[2].w+.28,cloud)*waterP[2].w;
 float veil=smoothstep(.42,.9,waterNoise(q*.4+19.))*waterP[3].x;
 sky=mix(sky,vec3(.72,.75,.78),clamp(cover+veil*.45,0.,.9));
 float glint=pow(max(0.,dot(d,sun)),mix(1600.,6.,rough*rough));
 return sky*day+waterSunColor()*glint*(1.-cover*.8)*sunPower;
}
float waterFoam(vec2 p,float distance,float time,float footprint) {
 float variation=waterNoise(p*.63+vec2(time*.025,-time*.018));
 float patches=smoothstep(.22,.72,waterNoise(p*.16+21.3));
 float width=.35+variation*.42;
 float edge=1.0-smoothstep(width*.2,width+footprint*.6,distance);
 float lace=(1.0-smoothstep(.3,1.5,distance))*smoothstep(.55,.79,variation)*patches;
 return clamp((edge*.40+lace*.18)*mix(.4,1.0,patches),0.0,.45);
}
float roadWear(vec3 p) {
 float d=surfaceDistance(p,true);if(d>12.){return 0.0;}
 float lane=abs(fract((d+1.75)/3.5)*3.5-1.75);
 float tracks=exp(-pow((lane-.86)/.32,2.0));
 float variation=.55+.45*waterNoise(p.xz*.075);
 return tracks*variation*.17;
}
${SEASCAPE_SHADE_GLSL}
`;
