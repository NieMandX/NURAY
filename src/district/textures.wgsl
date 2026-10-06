struct Material { color:vec4f, physical:vec4f, scale:vec4f };
@group(0) @binding(0) var albedo:texture_storage_2d_array<rgba8unorm,write>;
@group(0) @binding(1) var normals:texture_storage_2d_array<rgba8unorm,write>;
@group(0) @binding(2) var properties:texture_storage_2d_array<rgba8unorm,write>;
@group(0) @binding(3) var<storage,read> materials:array<Material>;
fn hash(p:vec2f)->f32 { return fract(sin(dot(p,vec2f(127.1,311.7)))*43758.5453); }
@compute @workgroup_size(8,8)
fn main(@builtin(global_invocation_id) id:vec3u){
  let size=textureDimensions(albedo);if any(id.xy>=size){return;}
  let uv=(vec2f(id.xy)+.5)/vec2f(size);let material=materials[id.z];let kind=u32(material.physical.z);
  let seed=f32(id.z)*37.3;let grain=hash(vec2f(id.xy)+seed);var shade=.90+grain*.10;var ao=1.0;
  if kind==0u {
    let q=vec2f(uv.x*4.0+floor(uv.y*4.0)*.5,uv.y*4.0);let f=fract(q);
    let mortar=min(min(f.x,1-f.x)*.47,min(f.y,1-f.y)*.22)<.012;
    shade=select(.70+hash(floor(q)+seed)*.30,.45,mortar);ao=select(1.0,.83,mortar);
  }
  if kind==2u {shade*=.83+.17*cos(uv.x*25.1327);}
  if kind==5u {shade*=.80+.20*(hash(floor(uv*12.0)+seed)*.6+hash(floor(uv*64.0)+seed)*.4);}
  if kind==6u {shade*=.65+.35*pow(abs(sin(uv.x*70.0+sin(uv.y*11.0))),.3);}
  if kind==4u || material.physical.x>.5 {shade=1.0;}
  let strength=select(.07,.015,material.physical.x>.5||kind==4u);
  let n=normalize(vec3f((grain-.5)*strength,(hash(vec2f(id.yx)+seed+19.0)-.5)*strength,1));
  let roughness=clamp(material.color.w+(grain-.5)*select(.10,.018,kind==4u),.025,.98);
  textureStore(albedo,vec2i(id.xy),i32(id.z),vec4f(vec3f(shade),1));
  textureStore(normals,vec2i(id.xy),i32(id.z),vec4f(n*.5+.5,1));
  textureStore(properties,vec2i(id.xy),i32(id.z),vec4f(ao,roughness,material.physical.x,1));
}
