// Deterministic primary visibility, refreshed only when the camera/scene changes.
// Reuses binding 1 with a separate buffer; path sampling and its RNG are untouched.
@compute @workgroup_size(8,8)
fn guideMain(@builtin(global_invocation_id) gid:vec3u){
  let size=vec2u(u.viewport.xy);if any(gid.xy>=size){return;}
  let i=(gid.x+gid.y*size.x)*3u;
  let uv=(vec2f(gid.xy)+.5)/u.viewport.xy*2-1;
  let rd=normalize(u.forward.xyz+u.right.xyz*uv.x*(u.viewport.x/u.viewport.y)*u.right.w-u.up.xyz*uv.y*u.right.w);
  let hit=traceMesh(u.camera.xyz,rd,false);
  if hit.t>=INF {
    meshAccumulation[i]=vec4f(rd,-1);
    meshAccumulation[i+1u]=vec4f(0);
    meshAccumulation[i+2u]=vec4f(1);
    return;
  }
  let m=meshSurface(hit,hit.t);let n=select(-m.normal,m.normal,dot(rd,m.normal)<0);
  let packed=word(hit.page,hit.a+6u);
  // Metals and sharp dielectric coatings require view-dependent reflection history.
  // This first implementation rejects that history while the camera moves.
  var rough=select(m.rough,min(m.rough,.2),m.metal>.5);
  if m.kind==4u {rough=-1;}
  meshAccumulation[i]=vec4f(u.camera.xyz+rd*hit.t,hit.t);
  // Numeric IDs avoid encoding atlas IDs as denormal float bit patterns, which
  // some GPUs flush to zero. Procedural patch IDs are also below 2^24.
  meshAccumulation[i+1u]=vec4f(n,f32(packed&0x7fffffffu));
  meshAccumulation[i+2u]=vec4f(m.color,rough);
}
