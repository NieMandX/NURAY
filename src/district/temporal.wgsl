struct Params {
  size:vec4f, // width, height, history valid, camera moved
  eye:vec4f, right:vec4f, up:vec4f, forward:vec4f, // previous camera
  current:vec4f, // current eye, tan(FOV/2)
  sampling:vec4f, // fresh batch size
};
struct Guide { position:vec4f, normal:vec4f, albedo:vec4f };
@group(0) @binding(0) var<uniform> p:Params;
@group(0) @binding(1) var<storage,read> raw:array<vec4f>;
@group(0) @binding(2) var<storage,read> guides:array<Guide>;
@group(0) @binding(3) var<storage,read> previousGuides:array<Guide>;
@group(0) @binding(4) var<storage,read> history:array<vec4f>;
@group(0) @binding(5) var<storage,read_write> result:array<vec4f>;
fn pixel(q:vec2i)->u32 {return u32(q.x)+u32(q.y)*u32(p.size.x);}
fn inImage(q:vec2i)->bool {return all(q>=vec2i(0))&&all(q<vec2i(p.size.xy));}
fn compatible(a:Guide,b:Guide)->bool {
  if a.position.w<0 {return b.position.w<0;}
  if b.position.w<0||a.normal.w!=b.normal.w||dot(a.normal.xyz,b.normal.xyz)<.96{return false;}
  let footprint=max(.003,a.position.w*p.current.w*2/p.size.y);
  let delta=b.position.xyz-a.position.xyz;
  // Tangential distance permits pixel footprints; the much stricter plane test
  // rejects nearby, parallel surfaces (e.g. a facade revealed behind a railing).
  if length(delta)>footprint*3||abs(dot(delta,a.normal.xyz))>max(.003,footprint*.15){return false;}
  return distance(a.albedo.rgb,b.albedo.rgb)<.18;
}
@compute @workgroup_size(8,8)
fn temporalMain(@builtin(global_invocation_id) gid:vec3u){
  if any(gid.xy>=vec2u(p.size.xy)){return;}
  let q=vec2i(gid.xy);let i=pixel(q);let g=guides[i];
  let fresh=raw[i+u32(p.size.x*p.size.y)].rgb;
  var old=vec4f(0);var weight=0.0;
  let moving=p.size.w>.5;
  let canReuse=p.size.z>.5&&(!moving||g.albedo.w>=.3);
  if canReuse {
    var uv=vec2f(q);
    if moving {
      let v=select(g.position.xyz-p.eye.xyz,g.position.xyz,g.position.w<0);
      let z=dot(v,p.forward.xyz);
      if z>0 {
        let ndc=vec2f(dot(v,p.right.xyz)/(z*p.right.w*(p.size.x/p.size.y)),-dot(v,p.up.xyz)/(z*p.right.w));
        uv=(ndc*.5+.5)*p.size.xy-.5;
      }else{uv=vec2f(-10);}
    }
    let base=vec2i(floor(uv));let fraction=fract(uv);
    for(var y=0;y<2;y++){for(var x=0;x<2;x++){
      let at=base+vec2i(x,y);if !inImage(at){continue;}
      let j=pixel(at);if !compatible(g,previousGuides[j]){continue;}
      let w=select(1-fraction.x,fraction.x,x==1)*select(1-fraction.y,fraction.y,y==1);
      old+=history[j]*w;weight+=w;
    }}
  }
  if weight>.05 {old/=weight;}else{old=vec4f(0);}
  if moving&&old.a>0 {
    // Clamp only reprojected history, never the fixed-camera Monte Carlo average.
    // Compatible neighbours keep sky/foreground and different materials separate.
    var mean=vec3f(0);var square=vec3f(0);var count=0.0;
    for(var y=-1;y<=1;y++){for(var x=-1;x<=1;x++){
      let at=q+vec2i(x,y);if !inImage(at){continue;}
      let j=pixel(at);if !compatible(g,guides[j]){continue;}
      let c=raw[j+u32(p.size.x*p.size.y)].rgb;mean+=c;square+=c*c;count+=1;
    }}
    mean/=max(count,1);let sigma=sqrt(max(vec3f(0),square/max(count,1)-mean*mean));
    // Do not clamp against an unreliable single noisy pixel at silhouettes.
    if count>=3 {old=vec4f(clamp(old.rgb,max(vec3f(0),mean-3*sigma-.02),mean+3*sigma+.02),old.a);}
    old.a=min(old.a,16.0);
  }
  let n=min(old.a,256.0);let batch=p.sampling.x;
  result[i]=vec4f((old.rgb*n+fresh*batch)/(n+batch),min(256.0,n+batch));
}
