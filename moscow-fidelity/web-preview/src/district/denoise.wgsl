struct Guide { position:vec4f, normal:vec4f, albedo:vec4f };
@group(0) @binding(0) var<uniform> params:vec4f; // width, height, dilation, tan(FOV/2)
@group(0) @binding(1) var<storage,read> input:array<vec4f>;
@group(0) @binding(2) var<storage,read> guides:array<Guide>;
@group(0) @binding(3) var<storage,read_write> output:array<vec4f>;
fn luma(c:vec3f)->f32 {return dot(c,vec3f(.2126,.7152,.0722));}
fn idx(q:vec2i)->u32 {return u32(q.x)+u32(q.y)*u32(params.x);}
@compute @workgroup_size(8,8)
fn denoiseMain(@builtin(global_invocation_id) gid:vec3u){
  if any(gid.xy>=vec2u(params.xy)){return;}
  let q=vec2i(gid.xy);let i=idx(q);let center=input[i];let a=guides[i];
  // Specular/refraction paths have no reliable surface guide beyond their first hit.
  // Keep those pixels and the sky sharp; no diffusion across these surfaces.
  if a.position.w<0||a.albedo.w<.3 {output[i]=center;return;}
  var sum=center.rgb;var weights=1.0;
  let footprint=max(.003,a.position.w*params.w*2/params.y);
  let step=i32(params.z);let lum=luma(center.rgb);
  let sigma=max(.02,(lum+.1)*2/sqrt(max(1.0,center.a)));
  for(var y=-1;y<=1;y++){for(var x=-1;x<=1;x++){
    if x==0&&y==0 {continue;}
    let at=q+vec2i(x,y)*step;
    if any(at<vec2i(0))||any(at>=vec2i(params.xy)){continue;}
    let j=idx(at);let b=guides[j];
    if b.position.w<0||b.albedo.w<.3||a.normal.w!=b.normal.w{continue;}
    let delta=b.position.xyz-a.position.xyz;
    let plane=abs(dot(delta,a.normal.xyz));
    if plane>max(.003,footprint*.2)||length(delta)>footprint*params.z*4 {continue;}
    let n=pow(max(0.0,dot(a.normal.xyz,b.normal.xyz)),64.0);
    let albedo=exp(-distance(a.albedo.rgb,b.albedo.rgb)*24);
    let edge=exp(-abs(luma(input[j].rgb)-lum)/sigma);
    let kernel=select(.5,.25,x!=0&&y!=0);
    let w=kernel*n*albedo*edge;
    sum+=input[j].rgb*w;weights+=w;
  }}
  // Gradually restore original detail as independent samples converge.
  let strength=clamp(1-center.a/128,0.0,1.0);
  output[i]=vec4f(mix(center.rgb,sum/weights,strength),center.a);
}
