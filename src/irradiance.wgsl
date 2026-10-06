@group(0) @binding(1) var<storage,read> radiance:array<vec4f>;
@group(0) @binding(2) var<storage,read_write> irradiance:array<vec4f>;
@compute @workgroup_size(64)
fn main(@builtin(global_invocation_id) gid:vec3u){
  let index=gid.x;if index>=1152u*6u{return;}
  let probe=index/6u;let axis=index%6u;
  let normals=array<vec3f,6>(vec3f(1,0,0),vec3f(-1,0,0),vec3f(0,1,0),vec3f(0,-1,0),vec3f(0,0,1),vec3f(0,0,-1));
  var value=vec3f(0);var normalization=0.0;
  for(var i=0u;i<16u;i++){
    let phi=(f32(i%4u)+0.5)/4.0*2.0*PI;let c=1.0-2.0*(f32(i/4u)+0.5)/4.0;let s=sqrt(1.0-c*c);
    let dir=vec3f(s*cos(phi),c,s*sin(phi));
    let cosine=max(0.0,dot(normals[axis],dir));
    value+=cosine*radiance[probe*16u+i].rgb;normalization+=cosine;
  }
  // Constant radiance should integrate to pi on every axis, even at this low angular resolution.
  irradiance[index]=vec4f(value*PI/max(normalization,0.001),1);
}
