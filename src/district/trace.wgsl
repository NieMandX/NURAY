// Appended to ../common.wgsl: same RNG, exact dielectric/conductor Fresnel,
// GGX VNDF sampler, masking and display pipeline as the sphere engine.
struct MeshMaterial { color:vec4f, physical:vec4f, scale:vec4f };
@group(0) @binding(1) var<storage,read_write> meshAccumulation:array<vec4f>;
@group(0) @binding(2) var<storage,read> meshMaterials:array<MeshMaterial>;
@group(0) @binding(3) var<storage,read> meshScene:array<u32>;
@group(0) @binding(4) var<storage,read> page0:array<u32>;
@group(0) @binding(5) var<storage,read> page1:array<u32>;
@group(0) @binding(6) var<storage,read> page2:array<u32>;
@group(0) @binding(7) var<storage,read> page3:array<u32>;
@group(0) @binding(8) var meshAlbedo:texture_2d_array<f32>;
@group(0) @binding(9) var meshProperties:texture_2d_array<f32>;
@group(0) @binding(10) var meshSampler:sampler;
fn word(page:u32,index:u32)->u32 {
  switch page {case 0u:{return page0[index];}case 1u:{return page1[index];}case 2u:{return page2[index];}default:{return page3[index];}}
}
fn vector(page:u32,index:u32)->vec3f {return bitcast<vec3f>(vec3u(word(page,index),word(page,index+1u),word(page,index+2u)));}
fn inverseRay(rd:vec3f)->vec3f {return 1.0/select(select(vec3f(-1e-9),vec3f(1e-9),rd>=vec3f(0)),rd,abs(rd)>vec3f(1e-9));}
fn boxHit(lo:vec3f,hi:vec3f,ro:vec3f,inv:vec3f,limit:f32)->bool {
  let a=(lo-ro)*inv;let b=(hi-ro)*inv;let near=min(a,b);let far=max(a,b);
  return max(EPS,max(near.x,max(near.y,near.z)))<=min(limit,min(far.x,min(far.y,far.z)));
}
struct MeshHit { t:f32,page:u32,a:u32,b:u32,c:u32,bary:vec2f,descriptor:u32 };
fn emptyMeshHit()->MeshHit {return MeshHit(INF,0u,0u,0u,0u,vec2f(0),0u);}
fn instanceRow(d:u32,r:u32)->vec4f {let o=d+8u+r*4u;return bitcast<vec4f>(vec4u(meshScene[o],meshScene[o+1u],meshScene[o+2u],meshScene[o+3u]));}
fn localRay(d:u32,v:vec3f,w:f32)->vec3f {let p=vec4f(v,w);return vec3f(dot(instanceRow(d,0u),p),dot(instanceRow(d,1u),p),dot(instanceRow(d,2u),p));}
fn hitUV(page:u32,a:u32,b:u32,c:u32,bary:vec2f)->vec2f {
  let x=bitcast<vec2f>(vec2u(word(page,a+4u),word(page,a+5u)));
  let y=bitcast<vec2f>(vec2u(word(page,b+4u),word(page,b+5u)));
  let z=bitcast<vec2f>(vec2u(word(page,c+4u),word(page,c+5u)));
  return x*(1-bary.x-bary.y)+y*bary.x+z*bary.y;
}
fn opaqueHit(page:u32,a:u32,b:u32,c:u32,bary:vec2f)->bool {
  let packed=word(page,a+6u);if (packed&0x80000000u)==0u{return true;}
  let id=packed&0x7fffffffu;let cutoff=meshMaterials[id].physical.w;
  if cutoff<=0{return true;}
  return textureSampleLevel(meshAlbedo,meshSampler,hitUV(page,a,b,c,bary),i32(id),0).a>=cutoff;
}
fn traceHouse(descriptor:u32,ro:vec3f,rd:vec3f,inv:vec3f,previous:MeshHit,anyHit:bool)->MeshHit {
  let page=meshScene[descriptor];let vertices=meshScene[descriptor+1u];let indices=meshScene[descriptor+2u];
  let root=meshScene[descriptor+3u];let count=meshScene[descriptor+4u];var hit=previous;var node=0u;
  while node<count {
    let o=root+node*8u;let length=word(page,o+7u);let first=word(page,o+3u);
    if !boxHit(vector(page,o),vector(page,o+4u),ro,inv,hit.t){node=select(first,node+1u,length>0u);continue;}
    if length==0u {node++;continue;}
    for(var i=0u;i<length;i++){
      let tri=indices+(first+i)*3u;let ia=vertices+word(page,tri)*8u;let ib=vertices+word(page,tri+1u)*8u;let ic=vertices+word(page,tri+2u)*8u;
      let a=vector(page,ia);let e1=vector(page,ib)-a;let e2=vector(page,ic)-a;
      let p=cross(rd,e2);let det=dot(e1,p);if abs(det)<1e-12 {continue;}
      let delta=ro-a;let x=dot(delta,p)/det;if x<0.0||x>1.0 {continue;}
      let q=cross(delta,e1);let y=dot(rd,q)/det;if y<0.0||x+y>1.0 {continue;}
      let t=dot(e2,q)/det;
      if t>EPS&&t<hit.t&&opaqueHit(page,ia,ib,ic,vec2f(x,y)) {hit=MeshHit(t,page,ia,ib,ic,vec2f(x,y),descriptor);if anyHit{return hit;}}
    }
    node++;
  }
  return hit;
}
fn traceMeshLimit(ro:vec3f,rd:vec3f,anyHit:bool,limit:f32)->MeshHit {
  let inv=inverseRay(rd);var hit=emptyMeshHit();hit.t=limit;var node=0u;
  while node<meshScene[0] {
    let o=4u+node*8u;let length=meshScene[o+7u];let first=meshScene[o+3u];
    let lo=bitcast<vec3f>(vec3u(meshScene[o],meshScene[o+1u],meshScene[o+2u]));
    let hi=bitcast<vec3f>(vec3u(meshScene[o+4u],meshScene[o+5u],meshScene[o+6u]));
    if !boxHit(lo,hi,ro,inv,hit.t){node=select(first,node+1u,length>0u);continue;}
    if length>0u {
      let d=meshScene[1]+first*select(8u,meshScene[3],meshScene[3]>0u);
      if meshScene[3]>0u {
        let lr=localRay(d,ro,1);let ld=localRay(d,rd,0);
        hit=traceHouse(d,lr,ld,inverseRay(ld),hit,anyHit);
      }else{hit=traceHouse(d,ro,rd,inv,hit,anyHit);}
      if anyHit&&hit.t<limit{return hit;}
    }
    node++;
  }
  if hit.t>=limit {return emptyMeshHit();}
  return hit;
}
fn traceMesh(ro:vec3f,rd:vec3f,anyHit:bool)->MeshHit {return traceMeshLimit(ro,rd,anyHit,INF);}
struct Surface { color:vec3f,rough:f32,metal:f32,ior:f32,kind:u32,normal:vec3f };
fn meshSurface(hit:MeshHit,travel:f32)->Surface {
  let packed=word(hit.page,hit.a+6u);let kind=packed&15u;let seed=packed>>4u;let count=u32(u.settings.x);
  var id=0u;if (packed&0x80000000u)>0u {id=packed&0x7fffffffu;}else if count>1u {id=kind+11u*(seed%((count+10u-kind)/11u));}
  let m=meshMaterials[id];let a=vector(hit.page,hit.a);let b=vector(hit.page,hit.b);let c=vector(hit.page,hit.c);
  var normal=normalize(cross(b-a,c-a));var color=m.color.rgb;var rough=m.color.w;
  if meshScene[3]>0u {
    let r0=instanceRow(hit.descriptor,0u).xyz;let r1=instanceRow(hit.descriptor,1u).xyz;let r2=instanceRow(hit.descriptor,2u).xyz;
    normal=normalize(r0*normal.x+r1*normal.y+r2*normal.z);
  }
  if u.settings.z>.5 {
    let uv0=bitcast<vec2f>(vec2u(word(hit.page,hit.a+4u),word(hit.page,hit.a+5u)));
    let uv1=bitcast<vec2f>(vec2u(word(hit.page,hit.b+4u),word(hit.page,hit.b+5u)));
    let uv2=bitcast<vec2f>(vec2u(word(hit.page,hit.c+4u),word(hit.page,hit.c+5u)));
    let uv=(uv0*(1-hit.bary.x-hit.bary.y)+uv1*hit.bary.x+uv2*hit.bary.y)*m.scale.xy;
    // Imported UVs are atlases, not metres; keep facade detail at city scale.
    var footprint=travel*u.right.w*256.0/u.viewport.y*max(m.scale.x,m.scale.y);
    if (packed&0x80000000u)>0u {
      let area=length(cross(b-a,c-a));let uvArea=abs((uv1.x-uv0.x)*(uv2.y-uv0.y)-(uv1.y-uv0.y)*(uv2.x-uv0.x));
      footprint=travel*u.right.w*2.0/u.viewport.y*f32(textureDimensions(meshAlbedo).x)*sqrt(uvArea/max(area,1e-12));
    }
    let lod=clamp(log2(max(1.0,footprint)),0.0,f32(textureNumLevels(meshAlbedo)-1u));
    color*=textureSampleLevel(meshAlbedo,meshSampler,uv,i32(id),lod).rgb;
    rough=textureSampleLevel(meshProperties,meshSampler,uv,i32(id),min(lod,f32(textureNumLevels(meshProperties)-1u))).g;
  }
  return Surface(color,rough,m.physical.x,select(m.physical.y,u.glass.x,u32(m.physical.z)==4u),u32(m.physical.z),normal);
}
fn meshFresnel(m:Surface,c:f32)->vec3f {
  if m.kind==8u {return fresnelCopper(c);}
  if m.metal>.5 {return m.color+(1-m.color)*pow(1-clamp(c,0.0,1.0),5.0);}
  return vec3f(fresnelDielectric(c,m.ior));
}
fn meshBrdf(m:Surface,n:vec3f,wo:vec3f,wi:vec3f)->vec3f {
  let nv=dot(n,wo);let nl=dot(n,wi);if nv<=0.0||nl<=0.0{return vec3f(0);}
  let h=normalize(wo+wi);let a=max(.002,m.rough*m.rough);
  let spec=meshFresnel(m,max(0.0,dot(wo,h)))*ggxD(max(0.0,dot(n,h)),a)*ggxG1(nv,a)*ggxG1(nl,a)/(4*nv*nl);
  return spec+m.color*(1-m.metal)/PI*(1-fresnelDielectric(nv,m.ior))*(1-fresnelDielectric(nl,m.ior));
}
fn meshPdf(m:Surface,n:vec3f,wo:vec3f,wi:vec3f)->f32 {
  let nv=dot(n,wo);let nl=dot(n,wi);if nv<=0.0||nl<=0.0{return 0;}
  let h=normalize(wo+wi);let a=max(.002,m.rough*m.rough);let probability=select(.25,1.0,m.metal>.5);
  return probability*ggxD(max(0.0,dot(n,h)),a)*ggxG1(nv,a)/(4*nv)+(1-probability)*nl/PI;
}
const SUN_COS=0.9998;
fn meshSky(rd:vec3f)->vec3f {
  let sky=mix(vec3f(.08,.09,.10),vec3f(.30,.43,.65),clamp(rd.y*.5+.5,0.0,1.0));
  return sky+select(vec3f(0),vec3f(4.2,3.77,3.1)/(2*PI*(1-SUN_COS)),dot(rd,u.light.xyz)>=SUN_COS);
}
fn skyPdf(rd:vec3f)->f32 {return .25/(4*PI)+select(0.0,.75/(2*PI*(1-SUN_COS)),dot(rd,u.light.xyz)>=SUN_COS);}
fn sampleSky()->vec3f {
  if random()<.75 {
    let z=mix(SUN_COS,1.0,random());let angle=2*PI*random();let r=sqrt(max(0.0,1-z*z));
    return basis(u.light.xyz)*vec3f(r*cos(angle),r*sin(angle),z);
  }
  let z=random()*2-1;let a=random()*2*PI;let r=sqrt(max(0.0,1-z*z));return vec3f(r*cos(a),z,r*sin(a));
}
