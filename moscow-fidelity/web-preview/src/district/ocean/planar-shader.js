export const PLANAR_WGSL=`
struct Reflection {view:mat4x4f,params:vec4f,size:vec4f}
@group(2) @binding(0) var reflectionMap:texture_2d<f32>;
@group(2) @binding(1) var reflectionSampler:sampler;
@group(2) @binding(2) var<uniform> reflection:Reflection;
fn sceneReflection(world:vec3f,n:vec3f,rough:f32,sky:vec3f)->vec3f {
 if reflection.size.z<.5 {return sky;}
 let q=reflection.view*vec4f(world.x,reflection.params.x,world.z,1);
 if q.w<=0 {return sky;}
 let uv=q.xy/q.w*vec2f(.5,-.5)+.5+n.xz*reflection.params.w*.025;
 let edge=smoothstep(0.0,.04,min(min(uv.x,uv.y),min(1-uv.x,1-uv.y)));
 let level=1-smoothstep(1.0,5.0,abs(world.y-reflection.params.x));
 let r=(reflection.params.z+rough*3)/reflection.size.xy;
 var c=textureSampleLevel(reflectionMap,reflectionSampler,uv,0)*.4;
 c+=textureSampleLevel(reflectionMap,reflectionSampler,uv+vec2f(r.x,0),0)*.15;
 c+=textureSampleLevel(reflectionMap,reflectionSampler,uv-vec2f(r.x,0),0)*.15;
 c+=textureSampleLevel(reflectionMap,reflectionSampler,uv+vec2f(0,r.y),0)*.15;
 c+=textureSampleLevel(reflectionMap,reflectionSampler,uv-vec2f(0,r.y),0)*.15;
 return mix(sky,c.rgb/max(c.a,.001),clamp(c.a*edge*level*reflection.params.y,0,1));
}
`;
export const PLANAR_GLSL=`
uniform sampler2D reflectionMap;
uniform mat4 reflectionView;
uniform vec4 reflectionParams;
uniform vec3 reflectionSize;
vec3 sceneReflection(vec3 world,vec3 n,float rough,vec3 sky){
 if(reflectionSize.z<.5)return sky;
 vec4 q=reflectionView*vec4(world.x,reflectionParams.x,world.z,1);
 if(q.w<=0.)return sky;
 vec2 uv=q.xy/q.w*.5+.5+n.xz*reflectionParams.w*.025;
 float edge=smoothstep(0.,.04,min(min(uv.x,uv.y),min(1.-uv.x,1.-uv.y)));
 float level=1.-smoothstep(1.,5.,abs(world.y-reflectionParams.x));
 vec2 r=(reflectionParams.z+rough*3.)/reflectionSize.xy;
 vec4 c=texture(reflectionMap,uv)*.4;
 c+=texture(reflectionMap,uv+vec2(r.x,0))*.15;
 c+=texture(reflectionMap,uv-vec2(r.x,0))*.15;
 c+=texture(reflectionMap,uv+vec2(0,r.y))*.15;
 c+=texture(reflectionMap,uv-vec2(0,r.y))*.15;
 // RGBA8 capture stores linear radiance / 8 for portable WebGL framebuffers.
 return mix(sky,c.rgb*8./max(c.a,.001),clamp(c.a*edge*level*reflectionParams.y,0.,1.));
}
`;
