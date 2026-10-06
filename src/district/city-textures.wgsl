@group(0) @binding(0) var source:texture_2d_array<f32>;
@group(0) @binding(1) var destination:texture_storage_2d_array<rgba8unorm,write>;
@compute @workgroup_size(8,8)
fn main(@builtin(global_invocation_id) p:vec3u){
  let size=textureDimensions(destination);if any(p.xy>=size){return;}
  let ratio=textureDimensions(source)/size;let xy=vec2i(p.xy*ratio);let layer=i32(p.z);
  var color=textureLoad(source,xy,layer,0);
  if ratio.x>1u {color=(color+textureLoad(source,xy+vec2i(1,0),layer,0)+textureLoad(source,xy+vec2i(0,1),layer,0)+textureLoad(source,xy+vec2i(1,1),layer,0))*.25;}
  textureStore(destination,vec2i(p.xy),layer,color);
}
