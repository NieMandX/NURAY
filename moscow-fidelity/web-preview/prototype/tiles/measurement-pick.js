// Read the surface already rendered at the cursor. Neither a second city mesh
// nor a full-size position/normal framebuffer is required for measurements.
import {cross,normalize} from '../../src/district/math.js';
import {inverseMatrix} from '../../src/district/sun-shadows.js';

const dot=(a,b)=>a[0]*b[0]+a[1]*b[1]+a[2]*b[2];
const sub=(a,b)=>a.map((v,i)=>v-b[i]);
const along=(a,dir,t)=>a.map((v,i)=>v+t*dir[i]);
const nextFrame=()=>new Promise(resolve=>requestAnimationFrame(resolve));

function view(renderer){
  const {camera:c,canvas}=renderer;
  const cp=Math.cos(c.pitch),sp=Math.sin(c.pitch),sy=Math.sin(c.yaw),cy=Math.cos(c.yaw);
  const back=[sy*cp,sp,cy*cp],right=[cy,0,-sy];
  const aspect=canvas.width/canvas.height;
  const tanY=Math.tan(44*Math.PI/360)*Math.max(1,1.1/aspect);
  return {eye:along(c.target,back,c.distance),right,up:cross(back,right),forward:back.map(v=>-v),
    tanX:tanY*aspect,tanY,width:canvas.clientWidth,height:canvas.clientHeight};
}
function ray(v,x,y){
  const dx=(x/v.width*2-1)*v.tanX,dy=(1-y/v.height*2)*v.tanY;
  return normalize(v.forward.map((f,i)=>f+dx*v.right[i]+dy*v.up[i]));
}
function projected(v,point){
  const delta=sub(point,v.eye),z=dot(delta,v.forward);
  if(z<=0)return null;
  return [(1+dot(delta,v.right)/(z*v.tanX))*v.width/2,(1-dot(delta,v.up)/(z*v.tanY))*v.height/2];
}
function projectToAxis(v,anchor,x,y,direction){
  if(!direction)return null;
  const axis=normalize(direction),r=ray(v,x,y),delta=sub(anchor,v.eye),c=dot(axis,r);
  // Closest points of a line and the cursor ray. An end-on axis does not
  // define a screen-space motion; leave the previous preview in place.
  const denom=1-c*c;
  if(denom<1e-6)return null;
  const t=(c*dot(r,delta)-dot(axis,delta))/denom;
  const p=along(anchor,axis,t);
  return dot(sub(p,v.eye),v.forward)>=1?p:null;
}

const span=5,center=12;
function glDepthResources(r){
  if(r.measurementGL)return r.measurementGL;
  const gl=r.gl;
  const vertex=`#version 300 es
  void main(){vec2 p=vec2((gl_VertexID<<1)&2,gl_VertexID&2);gl_Position=vec4(p*2.-1.,0.,1.);}`;
  const fragment=`#version 300 es
  precision highp float; precision highp int; uniform highp sampler2D depths;
  uniform ivec2 origin; out vec4 result;
  void main(){
    // Return rows in DOM (top to bottom) order.
    ivec2 d=ivec2(gl_FragCoord.xy)-ivec2(2);
    ivec2 p=clamp(origin+ivec2(d.x,-d.y),ivec2(0),textureSize(depths,0)-1);
    uint z=floatBitsToUint(texelFetch(depths,p,0).r);
    result=vec4(uvec4(z,z>>8u,z>>16u,z>>24u)&255u)/255.;
  }`;
  const p=gl.createProgram();
  for(const [type,source] of [[gl.VERTEX_SHADER,vertex],[gl.FRAGMENT_SHADER,fragment]]){
    const s=gl.createShader(type);gl.shaderSource(s,source);gl.compileShader(s);
    if(!gl.getShaderParameter(s,gl.COMPILE_STATUS))throw Error(gl.getShaderInfoLog(s));
    gl.attachShader(p,s);gl.deleteShader(s);
  }
  gl.linkProgram(p);if(!gl.getProgramParameter(p,gl.LINK_STATUS))throw Error(gl.getProgramInfoLog(p));
  const target=gl.createFramebuffer(),color=gl.createRenderbuffer();
  gl.bindRenderbuffer(gl.RENDERBUFFER,color);gl.renderbufferStorage(gl.RENDERBUFFER,gl.RGBA8,span,span);
  gl.bindFramebuffer(gl.FRAMEBUFFER,target);
  gl.framebufferRenderbuffer(gl.FRAMEBUFFER,gl.COLOR_ATTACHMENT0,gl.RENDERBUFFER,color);
  r.measurementGL={p,target,color,origin:gl.getUniformLocation(p,'origin'),depths:gl.getUniformLocation(p,'depths')};
  return r.measurementGL;
}

async function glDepths(r,px,py){
  const gl=r.gl,framebuffer=gl.getParameter(gl.FRAMEBUFFER_BINDING),viewport=gl.getParameter(gl.VIEWPORT);
  const previousProgram=gl.getParameter(gl.CURRENT_PROGRAM),previousTexture=gl.getParameter(gl.TEXTURE_BINDING_2D);
  const pack=gl.getParameter(gl.PIXEL_PACK_BUFFER_BINDING),buffer=gl.createBuffer();
  const dither=gl.isEnabled(gl.DITHER),depth=gl.isEnabled(gl.DEPTH_TEST);
  let sync;
  try{
    const g=glDepthResources(r);
    gl.bindFramebuffer(gl.FRAMEBUFFER,g.target);gl.viewport(0,0,span,span);
    gl.disable(gl.DITHER);gl.disable(gl.DEPTH_TEST);gl.useProgram(g.p);
    gl.bindTexture(gl.TEXTURE_2D,r.contactDepth);
    gl.uniform1i(g.depths,gl.getParameter(gl.ACTIVE_TEXTURE)-gl.TEXTURE0);
    gl.uniform2i(g.origin,px,r.canvas.height-1-py);
    gl.drawArrays(gl.TRIANGLES,0,3);
    gl.bindBuffer(gl.PIXEL_PACK_BUFFER,buffer);gl.bufferData(gl.PIXEL_PACK_BUFFER,span*span*4,gl.STREAM_READ);
    gl.readPixels(0,0,span,span,gl.RGBA,gl.UNSIGNED_BYTE,0);
    sync=gl.fenceSync(gl.SYNC_GPU_COMMANDS_COMPLETE,0);gl.flush();
  }finally{
    gl.bindBuffer(gl.PIXEL_PACK_BUFFER,pack);gl.bindFramebuffer(gl.FRAMEBUFFER,framebuffer);
    gl.viewport(...viewport);gl.useProgram(previousProgram);gl.bindTexture(gl.TEXTURE_2D,previousTexture);
    if(dither)gl.enable(gl.DITHER);if(depth)gl.enable(gl.DEPTH_TEST);
    if(!sync)gl.deleteBuffer(buffer);
  }
  try{
    for(;;){
      const status=gl.clientWaitSync(sync,0,0);
      if(status===gl.WAIT_FAILED||gl.isContextLost())return null;
      if(status!==gl.TIMEOUT_EXPIRED)break;
      await nextFrame();
    }
    const bytes=new Uint8Array(span*span*4),bound=gl.getParameter(gl.PIXEL_PACK_BUFFER_BINDING);
    gl.bindBuffer(gl.PIXEL_PACK_BUFFER,buffer);gl.getBufferSubData(gl.PIXEL_PACK_BUFFER,0,bytes);
    gl.bindBuffer(gl.PIXEL_PACK_BUFFER,bound);
    const data=new DataView(bytes.buffer);
    return Array.from({length:span*span},(_,i)=>data.getFloat32(i*4,true));
  }finally{gl.deleteSync(sync);gl.deleteBuffer(buffer);}
}

const depthKernel=`
@group(0) @binding(0) var depths:texture_depth_2d;
@group(0) @binding(1) var<storage,read_write> samples:array<f32>;
@compute @workgroup_size(1) fn readDepths(){
  let center=vec2i(i32(samples[0]),i32(samples[1]));
  for(var i=0u;i<25u;i++){
    let pixel=clamp(center+vec2i(i32(i%5u)-2,i32(i/5u)-2),vec2i(0),vec2i(textureDimensions(depths))-1);
    samples[i]=textureLoad(depths,pixel,0);
  }
}`;
async function gpuQuery(device,pipeline,inputs,size,entries){
  const result=device.createBuffer({label:'Measurement query',size,usage:GPUBufferUsage.STORAGE|GPUBufferUsage.COPY_SRC|GPUBufferUsage.COPY_DST});
  const staging=device.createBuffer({label:'Measurement readback',size,usage:GPUBufferUsage.COPY_DST|GPUBufferUsage.MAP_READ});
  try{
    device.queue.writeBuffer(result,0,inputs);
    const group=device.createBindGroup({layout:pipeline.getBindGroupLayout(0),entries:entries(result)});
    const encoder=device.createCommandEncoder(),pass=encoder.beginComputePass();
    pass.setPipeline(pipeline);pass.setBindGroup(0,group);pass.dispatchWorkgroups(1);pass.end();
    encoder.copyBufferToBuffer(result,0,staging,0,size);device.queue.submit([encoder.finish()]);
    await staging.mapAsync(GPUMapMode.READ);
    return new Float32Array(staging.getMappedRange()).slice();
  }finally{staging.destroy();result.destroy();}
}

function rasterHit(depths,frame,px,py){
  if(!depths)return null;
  const {matrix,eye,width,height,reverse}=frame,inv=inverseMatrix(matrix,eye);
  function at(i){
    const d=depths[i],x=px+i%span-2,y=py+Math.floor(i/span)-2;
    if((reverse?d<=0:d>=1)||x<0||y<0||x>=width||y>=height)return null;
    const nx=(x+.5)/width*2-1,ny=1-(y+.5)/height*2;
    const h=[0,1,2,3].map(j=>inv[j]*nx+inv[4+j]*ny+inv[8+j]*d+inv[12+j]);
    return eye.map((e,j)=>e+h[j]/h[3]);
  }
  const point=at(center);
  if(!point)return null;
  // Window depth is affine within a projected triangle. A one-sided
  // extrapolation identifies the same face at a roof edge or silhouette.
  function tangent(step){
    let best=null,minError=Infinity;
    for(const sign of [-1,1]){
      const i=center+sign*step,q=at(i);
      if(!q)continue;
      const j=i+sign*step;
      const error=at(j)?Math.abs(depths[j]-2*depths[i]+depths[center]):1+Math.abs(depths[i]-depths[center]);
      if(error<minError){best=sub(q,point).map(v=>v*sign);minError=error;}
    }
    return best;
  }
  const x=tangent(1),y=tangent(span);
  let normal=x&&y?cross(x,y):null;
  if(normal&&Math.hypot(...normal)>1e-12){
    normal=normalize(normal);if(dot(normal,sub(eye,point))<0)normal=normal.map(v=>-v);
  }else normal=null;
  return {point,normal};
}

async function traceHit(r,v,x,y){
  const t=r.tracer,d=r.device;
  if(!t.group||!t.pickModule)return null;
  t.pickPipeline??=d.createComputePipelineAsync({label:'Measurement BVH ray',layout:'auto',compute:{module:t.pickModule,entryPoint:'pickSurface'}});
  const pipe=await t.pickPipeline;
  if(!r.ready||!t.scene)return null;
  const inputs=Float32Array.of(...v.eye,0,...ray(v,x,y),0);
  const result=await gpuQuery(d,pipe,inputs,32,buffer=>t.geometryEntries()
    .filter(({binding})=>binding!==9)
    .map(e=>e.binding===1?{binding:1,resource:{buffer}}:e));
  return result[3]>0?{point:Array.from(result.slice(0,3)),normal:Array.from(result.slice(4,7))}:null;
}

export function createMeasurementGeometry(getRenderer){
  return {
    near:1,
    project(point){const r=getRenderer();return r?.camera?projected(view(r),point):null;},
    depth(point){const r=getRenderer();if(!r?.camera)return -Infinity;const v=view(r);return dot(sub(point,v.eye),v.forward);},
    constrain(anchor,x,y,mode){
      const r=getRenderer();if(!r?.camera)return null;
      return projectToAxis(view(r),anchor.point,x,y,mode==='vertical'?[0,1,0]:anchor.normal);
    },
    async pick(x,y){
      const r=getRenderer();if(!r?.ready)return null;
      const v=view(r);if(x<0||y<0||x>=v.width||y>=v.height)return null;
      if(r.state.engine!=='raster')return traceHit(r,v,x,y);
      if(r.gl&&!r.measurementDepthFrame){
        // AO-off WebGL normally renders to the non-preserved back buffer.
        // Ask the next geometry pass to retain its depth for this query.
        r.requestMeasurementDepth=true;r.waterFrameSignature=null;
        await nextFrame();
      }
      const frame=r.measurementDepthFrame;
      if(!frame||!r.ready||r.state.engine!=='raster'||r.canvas.width!==frame.width||r.canvas.height!==frame.height)return null;
      const px=Math.floor(x*frame.width/v.width),py=Math.floor(y*frame.height/v.height);
      let depths;
      if(r.gl)depths=await glDepths(r,px,py);
      else{
        const d=r.device;
        r.measurementDepthPipeline??=d.createComputePipeline({label:'Read measurement depth',layout:'auto',
          compute:{module:d.createShaderModule({code:depthKernel}),entryPoint:'readDepths'}});
        depths=await gpuQuery(d,r.measurementDepthPipeline,Float32Array.of(px,py),100,buffer=>[
          {binding:0,resource:r.depth.createView()},{binding:1,resource:{buffer}}]);
      }
      return rasterHit(depths,frame,px,py);
    },
  };
}
