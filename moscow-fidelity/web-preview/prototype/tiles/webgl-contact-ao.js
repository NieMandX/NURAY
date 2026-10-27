export const contactVertex=`#version 300 es
void main(){float x=float((gl_VertexID<<1)&2),y=float(gl_VertexID&2);gl_Position=vec4(x*2.-1.,y*2.-1.,0,1);}`;
export const contactFragment=`#version 300 es
precision highp float;
uniform sampler2D colorMap;
uniform sampler2D depthMap;
uniform mat4 inverseView;
uniform vec3 camera;
uniform vec2 size;
out vec4 result;
ivec2 bound(ivec2 p){return clamp(p,ivec2(0),ivec2(size)-1);}
vec3 point(ivec2 p){vec2 uv=(vec2(p)+.5)/size;float z=texelFetch(depthMap,p,0).r;vec4 h=inverseView*vec4(uv*2.-1.,z,1);return h.xyz/h.w;}
void main(){
 ivec2 p=ivec2(gl_FragCoord.xy);result=vec4(0);if(texelFetch(depthMap,p,0).r>=1.)return;
 vec3 world=point(p),xp=point(bound(p+ivec2(1,0)))-world,xm=world-point(bound(p-ivec2(1,0))),yp=point(bound(p+ivec2(0,1)))-world,ym=world-point(bound(p-ivec2(0,1)));
 vec3 dx=dot(xm,xm)<dot(xp,xp)?xm:xp,dy=dot(ym,ym)<dot(yp,yp)?ym:yp,crossN=cross(dx,dy);if(dot(crossN,crossN)<1e-16)return;
 vec3 n=normalize(crossN);if(dot(n,camera-world)<0.)n=-n;
 float radius=2.4,pixel=max(.0001,min(length(dx),length(dy))),radiusPixels=clamp(radius/pixel,1.,90.);if(radiusPixels<1.5)return;
 float occlusion=0.;
 for(int i=0;i<8;i++){
  float angle=float(i)*.785398163+6.2831853*fract(sin(dot(vec2(p),vec2(12.9898,78.233)))*43758.5453),horizon=0.;
  for(int j=0;j<4;j++){
  float step=(float(j)+.5)/4.,ring=step*step;ivec2 q=p+ivec2(round(vec2(cos(angle),sin(angle))*radiusPixels*ring));
  if(any(lessThan(q,ivec2(0)))||any(greaterThanEqual(q,ivec2(size))))continue;if(texelFetch(depthMap,q,0).r>=1.)continue;
  vec3 delta=point(q)-world;float distance=length(delta);if(distance<.025||distance>radius)continue;
  horizon=max(horizon,max(0.,dot(n,delta)/distance-.12)*(1.-smoothstep(radius*.25,radius,distance)));
  }
  occlusion+=horizon;
 }
 result=vec4(min(.28,occlusion/8.*1.2)*smoothstep(1.5,4.,radiusPixels));
}`;

export const contactComposite=`#version 300 es
precision highp float;
uniform sampler2D colorMap;
uniform sampler2D depthMap;
uniform sampler2D contactMap;
uniform mat4 inverseView;
uniform vec2 size;
out vec4 result;
ivec2 bound(ivec2 p){return clamp(p,ivec2(0),ivec2(size)-1);}
vec3 point(ivec2 p){vec2 uv=(vec2(p)+.5)/size;float z=texelFetch(depthMap,p,0).r;vec4 h=inverseView*vec4(uv*2.-1.,z,1);return h.xyz/h.w;}
void main(){
 ivec2 p=ivec2(gl_FragCoord.xy);vec4 base=texelFetch(colorMap,p,0);result=base;if(texelFetch(depthMap,p,0).r>=1.)return;
 float distance=length(point(p)),tolerance=max(.08,distance*.004),total=0.,weight=0.;
 for(int y=-2;y<=2;y++)for(int x=-2;x<=2;x++){
  ivec2 q=bound(p+ivec2(x,y)*2);if(texelFetch(depthMap,q,0).r>=1.)continue;
  float w=exp(-float(x*x+y*y)*.32)*(1.-smoothstep(tolerance,tolerance*3.,abs(length(point(q))-distance)));
  total+=texelFetch(contactMap,q,0).r*w;weight+=w;
 }
 result=vec4(base.rgb*(1.-total/max(weight,.0001)),base.a);
}`;
