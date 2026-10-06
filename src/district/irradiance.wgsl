@group(0) @binding(0) var<storage,read> radiance:array<vec4f>;
@group(0) @binding(1) var<storage,read_write> irradiance:array<vec4f>;
@compute @workgroup_size(64)
fn main(@builtin(global_invocation_id) gid:vec3u){
  let index=gid.x;if index>=2048u*6u{return;}
  let probe=index/6u;let axis=index%6u;
  let normals=array<vec3f,6>(vec3f(1,0,0),vec3f(-1,0,0),vec3f(0,1,0),vec3f(0,-1,0),vec3f(0,0,1),vec3f(0,0,-1));
  var value=vec3f(0);var weight=0.0;
  for(var i=0u;i<16u;i++){
    let phi=(f32(i%4u)+.5)/4.0*6.28318530718;let c=1-2*(f32(i/4u)+.5)/4.0;let s=sqrt(1-c*c);
    let dir=vec3f(s*cos(phi),c,s*sin(phi));let cosine=max(0.0,dot(normals[axis],dir));
    // Match the incident Fresnel factor of the dielectric diffuse BRDF.
    let r0=0.04;let transmission=1-(r0+(1-r0)*pow(1-cosine,5.0));
    value+=cosine*transmission*radiance[probe*16u+i].rgb;weight+=cosine;
  }
  irradiance[index]=vec4f(value*3.14159265359/max(weight,.001),1);
}
