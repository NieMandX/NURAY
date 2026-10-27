import {surfaceFunctions} from './water-shaders.js?v=moscow-defaults-1';
import {PLANAR_GLSL} from '../../src/district/ocean/planar-shader.js?v=water-reflections-1';
export const vertex=`#version 300 es
precision highp float;
precision highp int;
layout(location=0) in vec3 position;
layout(location=1) in vec2 packedNormal;
layout(location=2) in vec2 uv;
layout(location=3) in uint face;
layout(location=4) in float tint;
layout(location=5) in vec4 rowX;
layout(location=6) in vec4 rowY;
layout(location=7) in vec4 rowZ;
uniform mat4 view;
uniform uint materialCount;
out vec3 world;
out vec3 normal;
out vec2 texcoord;
out float shade;
flat out uint material;
void main(){
  world=vec3(dot(rowX,vec4(position,1)),dot(rowY,vec4(position,1)),dot(rowZ,vec4(position,1)));
  vec3 n=vec3(packedNormal,1.-abs(packedNormal.x)-abs(packedNormal.y));float t=clamp(-n.z,0.,1.);
  n.x+=n.x>=0.?-t:t;n.y+=n.y>=0.?-t:t;
  vec3 a=vec3(rowX.x,rowY.x,rowZ.x),b=vec3(rowX.y,rowY.y,rowZ.y),c=vec3(rowX.z,rowY.z,rowZ.z);
  normal=normalize(cross(b,c)*n.x+cross(c,a)*n.y+cross(a,b)*n.z);
  uint kind=face&15u,seed=face>>4u;
  material=(face&0x80000000u)>0u?face&0x7fffffffu:(materialCount>1u?kind+11u*(seed%((materialCount+10u-kind)/11u)):0u);
  texcoord=uv;shade=tint>0.?tint:1.;
  vec4 clip=view*vec4(world,1);
  // Shared camera math uses 0..1 depth; WebGL clip space uses -1..1.
  gl_Position=vec4(clip.xy,2.*clip.z-clip.w,clip.w);
}`;
export const shadowFragment=`#version 300 es
precision highp float;
void main(){}`;
export const fragment=`#version 300 es
precision highp float;
precision highp int;
precision highp sampler2D;
precision highp sampler2DArray;
precision highp sampler2DArrayShadow;
uniform sampler2D materials;
uniform sampler2DArray albedo;
uniform sampler2DArrayShadow shadowMap;
uniform sampler2D facadeNormal;
uniform mat4 shadow[3];
uniform vec4 shadowParams[3];
uniform int shadowCount;
uniform vec3 camera;
uniform vec3 sun;
uniform float sunPower;
uniform float exposure;
uniform float shadowSize;
in vec3 world;
in vec3 normal;
in vec2 texcoord;
in float shade;
flat in uint material;
out vec4 result;
${surfaceFunctions}
${PLANAR_GLSL}
vec3 sky(vec3 d,float rough){return waterSky(d,rough);}
vec3 fresnel(float c,vec3 f0){return f0+(1.-f0)*pow(1.-clamp(c,0.,1.),5.);}
float dielectric(float c,float eta){
  float st2=(1.-c*c)/(eta*eta);if(st2>=1.)return 1.;
  float ct=sqrt(max(0.,1.-st2)),a=(c-eta*ct)/(c+eta*ct),b=(eta*c-ct)/(eta*c+ct);return .5*(a*a+b*b);
}
float shadowAt(vec3 p,vec3 n,int layer){
 mat4 m=shadow[layer];vec4 params=shadowParams[layer],clip=m*vec4(p+n*params.z,1);vec2 uv=clip.xy*.5+.5;
 if(any(lessThan(uv,vec2(0)))||any(greaterThan(uv,vec2(1)))||clip.z<0.||clip.z>1.)return 1.;
 vec3 rx=vec3(m[0].x,m[1].x,m[2].x),ry=vec3(m[0].y,m[1].y,m[2].y),rz=vec3(m[0].z,m[1].z,m[2].z);
 vec3 g=vec3(dot(n,rx)/dot(rx,rx),dot(n,ry)/dot(ry,ry),dot(n,rz)/dot(rz,rz));if(abs(g.z)<.0001)return 1.;
 vec2 gradient=-g.xy/g.z*2.;float bias=max(params.y,(abs(gradient.x)+abs(gradient.y))/shadowSize);
 float total=0.;for(int y=-1;y<=1;y++)for(int x=-1;x<=1;x++){vec2 offset=vec2(x,y)/shadowSize;total+=texture(shadowMap,vec4(uv+offset,float(layer),clip.z+dot(gradient,offset)-bias));}return total/9.;
}
float visibility(vec3 p,vec3 n){
 for(int i=0;i<3;i++){
  if(i>=shadowCount)break;vec4 q=shadow[i]*vec4(p,1);float edge=max(abs(q.x),abs(q.y));
  if(edge<1.&&q.z>0.&&q.z<1.){
   float value=shadowAt(p,n,i);if(i+1<shadowCount&&edge>.8)return mix(value,shadowAt(p,n,i+1),smoothstep(.8,1.,edge));return value;
  }
 }return 1.;
}
vec3 toneMap(vec3 x){return clamp((x*(2.51*x+.03))/(x*(2.43*x+.59)+.14),vec3(0),vec3(1));}
vec3 srgb(vec3 x){return mix(1.055*pow(x,vec3(1./2.4))-.055,x*12.92,lessThanEqual(x,vec3(.0031308)));}
vec4 lightingOutput(vec3 light){if(waterP[3].y>3.5)return vec4(hwGrade(light),1);return vec4(mix(srgb(toneMap(light*exposure)),seaGrade(light,waterP[5].x),seaLightWeight()),1);}
void main(){
  vec4 m=texelFetch(materials,ivec2(0,int(material)),0),physical=texelFetch(materials,ivec2(1,int(material)),0);
  vec4 info=texelFetch(materials,ivec2(2,int(material)),0);float layer=info.x;
  vec4 tex=texture(albedo,vec3(texcoord,layer));if(tex.a<physical.w)discard;
  vec3 n=normalize(normal),color=clamp(m.rgb*shade,vec3(0),vec3(1))*tex.rgb;
  vec3 geometricNormal=n;
  if(info.y>.5){vec3 map=texture(facadeNormal,texcoord).xyz*2.-1.,up=normalize(vec3(0,1,0)-n*n.y),right=normalize(cross(up,n));n=normalize(right*map.x+up*map.y+n*map.z);}
  float rough=m.w,metal=physical.x;
  float footprint=max(length(dFdx(world).xz),length(dFdy(world).xz));
  if(int(physical.z)==12&&waterP[3].z>.5){
    float rawShadow=visibility(world,geometricNormal);
    vec3 light=seascapeShade(world,world-camera,surfaceDistance(world,false),sunVisibility(rawShadow))*shadowFill(rawShadow);
    result=lightingOutput(light);return;
  }
  if(int(physical.z)==12){
    vec3 wave=waterShape(world.xz,waterTime,footprint);n=normalize(geometricNormal+vec3(wave.x,0.,wave.y));
    float foam=clamp(waterFoam(world.xz,surfaceDistance(world,false),waterTime,footprint)*waterP[2].y+smoothstep(.2,.5,length(wave.xy))*waterP[2].x*.25,0.,1.);
    color=waterBody(surfaceDistance(world,false),dot(n,normalize(camera-world)));
    color=mix(color,vec3(.50,.54,.51),foam);rough=mix(mix(.09,.22,clamp(length(wave.xy)*3.,0.,1.)),.65,foam);
  }else if(info.z>.5){color*=1.-roadWear(world);}
  vec3 wo=normalize(camera-world),wi=sun,h=normalize(wo+wi);
  float nv=max(.001,dot(n,wo)),nl=max(0.,dot(n,wi)),nh=max(0.,dot(n,h)),vh=max(0.,dot(wo,h));
  vec3 f0=mix(vec3(int(physical.z)==12?waterFresnel(1.):.04),color,metal),F=int(physical.z)==12?vec3(waterFresnel(vh)):fresnel(vh,f0);
  float a=max(.001,rough*rough),a2=a*a,den=nh*nh*(a2-1.)+1.,D=a2/(3.14159265*den*den);
  float Gv=2.*nv/(nv+sqrt(a2+(1.-a2)*nv*nv)),Gl=2.*nl/max(.0001,nl+sqrt(a2+(1.-a2)*nl*nl));
  vec3 spec=F*D*Gv*Gl/max(.0001,4.*nv*nl),diffuse=(1.-F)*color*(1.-metal)/3.14159265;
  float rawShadow=visibility(world,geometricNormal),shadeSun=sunVisibility(rawShadow);
  vec3 light=(diffuse+spec)*waterSunColor()*nl*shadeSun*sunPower;
  light+=color*(1.-metal)*waterAmbient(n);
  vec3 environment=sky(reflect(-wo,n),rough);
  if(int(physical.z)==12)environment=sceneReflection(world,n,rough,environment);
  light+=environment*(int(physical.z)==12?vec3(waterFresnel(nv)):fresnel(nv,f0))*mix(1.,.40,rough);
  if(int(physical.z)==4){
    float f=dielectric(nv,physical.y);vec3 transmitted=vec3(.028,.032,.034)*exp(-vec3(.25,.09,.06)*(.012/max(.15,nv)));
    light=sky(reflect(-wo,n),rough)*f+transmitted*(1.-f)+spec*waterSunColor()*nl*shadeSun*sunPower;
  }
  light*=mix(1./1.4,1.,shadeSun)*shadowFill(rawShadow);
  result=lightingOutput(light);
}`;
export const captureFragment=fragment.replace(PLANAR_GLSL,'')
 .replace('void main(){','uniform float captureHeight;\nvoid main(){\n if(world.y<captureHeight+.03)discard;')
 .replace('  vec4 info=','  if(int(physical.z)==12)discard;\n  vec4 info=')
 .replace('  if(int(physical.z)==12)environment=sceneReflection(world,n,rough,environment);','')
 .replace('vec4 lightingOutput(vec3 light){','vec4 lightingOutput(vec3 light){return vec4(light/8.,1);}\nvec4 unusedGrade(vec3 light){');
