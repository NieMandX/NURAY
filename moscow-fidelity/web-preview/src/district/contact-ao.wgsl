struct Settings { inverse:mat4x4f, camera:vec4f, size:vec4f };
@group(0) @binding(0) var<uniform> settings:Settings;
@group(0) @binding(1) var color:texture_2d<f32>;
@group(0) @binding(2) var depth:texture_depth_2d;
@group(0) @binding(3) var contact:texture_2d<f32>;
@vertex fn vertex(@builtin(vertex_index) id:u32)->@builtin(position) vec4f {
 let x=f32((id<<1u)&2u);let y=f32(id&2u);return vec4f(x*2-1,y*2-1,0,1);
}
fn point(p:vec2i)->vec3f {
 let uv=(vec2f(p)+.5)/settings.size.xy;let z=textureLoad(depth,p,0);
 let h=settings.inverse*vec4f(uv*vec2f(2,-2)+vec2f(-1,1),z,1);return h.xyz/h.w;
}
fn clampPixel(p:vec2i)->vec2i{return clamp(p,vec2i(0),vec2i(settings.size.xy)-1);}
@fragment fn fragment(@builtin(position) pos:vec4f)->@location(0) vec4f {
 let p=vec2i(pos.xy);if textureLoad(depth,p,0)<=0 {return vec4f(0);}
 let world=point(p);
 let xp=point(clampPixel(p+vec2i(1,0)))-world;let xm=world-point(clampPixel(p-vec2i(1,0)));
 let yp=point(clampPixel(p+vec2i(0,1)))-world;let ym=world-point(clampPixel(p-vec2i(0,1)));
 let dx=select(xp,xm,dot(xm,xm)<dot(xp,xp));let dy=select(yp,ym,dot(ym,ym)<dot(yp,yp));
 let crossN=cross(dx,dy);if dot(crossN,crossN)<1e-16 {return vec4f(0);}
 var n=normalize(crossN);if dot(n,settings.camera.xyz-world)<0 {n=-n;}
 let radius=settings.size.z;let pixel=max(.0001,min(length(dx),length(dy)));let radiusPixels=clamp(radius/pixel,1.0,90.0);
 if radiusPixels<1.5 {return vec4f(0);}
 var occlusion=0.0;
 // Keep the strongest horizon in each direction. Averaging all samples
 // washes out thin trunks; short first steps retain their ground contact.
 for(var i=0;i<8;i++){
  let angle=f32(i)*.785398163+6.2831853*fract(sin(dot(vec2f(p),vec2f(12.9898,78.233)))*43758.5453);var horizon=0.0;
  for(var j=0;j<4;j++){
  let step=(f32(j)+.5)/4.0;let ring=step*step;
  let q=p+vec2i(round(vec2f(cos(angle),sin(angle))*radiusPixels*ring));
  if any(q<vec2i(0))||any(q>=vec2i(settings.size.xy)) {continue;}
  if textureLoad(depth,q,0)<=0 {continue;}
  let delta=point(q)-world;let distance=length(delta);
  if distance<.025||distance>radius {continue;}
  horizon=max(horizon,max(0.0,dot(n,delta)/distance-.12)*(1-smoothstep(radius*.25,radius,distance)));
  }
  occlusion+=horizon;
 }
 return vec4f(min(.28,occlusion/8*settings.size.w)*smoothstep(1.5,4.0,radiusPixels));
}

// Edge-aware spatial filter: random ray directions should never appear as
// spokes around a thin trunk, or bleed across foreground silhouettes.
@fragment fn composite(@builtin(position) pos:vec4f)->@location(0) vec4f {
 let p=vec2i(pos.xy);let base=textureLoad(color,p,0);if textureLoad(depth,p,0)<=0 {return base;}
 let distance=length(point(p));let tolerance=max(.08,distance*.004);var total=0.0;var weight=0.0;
 for(var y=-2;y<=2;y++){for(var x=-2;x<=2;x++){
  let q=clampPixel(p+vec2i(x,y)*2);if textureLoad(depth,q,0)<=0 {continue;}
  let w=exp(-f32(x*x+y*y)*.32)*(1-smoothstep(tolerance,tolerance*3,abs(length(point(q))-distance)));
  total+=textureLoad(contact,q,0).r*w;weight+=w;
 }}
 return vec4f(base.rgb*(1-total/max(weight,.0001)),base.a);
}
