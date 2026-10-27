import {reflectionState,reflectionChunks,reflectionParameters} from './planar-math.js?v=ground-reflections-1';
// Explicit layouts can be shared by the normal and reflected-camera pipelines.
export function cityReflectionLayouts(d){
 const F=GPUShaderStage.FRAGMENT,V=GPUShaderStage.VERTEX;
 const buffer=(binding,type='uniform',visibility=F)=>({binding,visibility,buffer:{type}});
 const texture=(binding,viewDimension='2d',sampleType='float')=>({binding,visibility:F,texture:{viewDimension,sampleType}});
 const sampler=(binding,type='filtering')=>({binding,visibility:F,sampler:{type}});
 return [
  [buffer(0,'uniform',V|F),buffer(1,'read-only-storage'),texture(2,'2d-array'),texture(3,'2d-array'),texture(4,'2d-array'),sampler(5),texture(6,'2d-array','depth'),sampler(7,'comparison'),buffer(8,'read-only-storage',V),buffer(9),buffer(10,'read-only-storage')],
  [buffer(0),texture(1),texture(2),sampler(3),texture(4,'2d-array'),texture(5,'2d-array'),texture(6,'2d-array'),texture(7),texture(8,'cube'),sampler(9),texture(10,'2d-array'),buffer(11,'read-only-storage'),buffer(12)],
  [texture(0),sampler(1),buffer(2)],
  [texture(0),sampler(1),buffer(2)],
 ].map(entries=>d.createBindGroupLayout({entries}));
}
export class PlanarReflection {
 constructor(owner,ground=false){this.ground=ground;this.name=ground?'groundReflection':'reflection';this.o=owner;this.d=owner.device;this.updates=0;}
 async init(module,vertexLayout){
  const o=this.o,d=this.d;
  this.frame=d.createBuffer({size:192,usage:GPUBufferUsage.UNIFORM|GPUBufferUsage.COPY_DST});
  this.uniform=d.createBuffer({size:96,usage:GPUBufferUsage.UNIFORM|GPUBufferUsage.COPY_DST});
  this.sampler=d.createSampler({magFilter:'linear',minFilter:'linear'});
  this.pipeline=this.ground?o.reflection.pipeline:await d.createRenderPipelineAsync({label:'Water · mirrored city',layout:d.createPipelineLayout({bindGroupLayouts:o.cityLayouts.slice(0,2)}),
   vertex:{module,entryPoint:'vertex',buffers:[vertexLayout]},fragment:{module,entryPoint:'captureFragment',targets:[{format:'rgba16float'}]},
   primitive:{cullMode:'back',frontFace:'cw'},depthStencil:{format:'depth32float',depthWriteEnabled:true,depthCompare:'greater'}});
  this.resize([1,1]);
 }
 resize(size){
  if(String(size)===String(this.size))return;
  this.color?.destroy();this.depth?.destroy();this.size=size;this.key=null;
  this.color=this.d.createTexture({label:'Water reflection · linear HDR',size,format:'rgba16float',usage:GPUTextureUsage.TEXTURE_BINDING|GPUTextureUsage.RENDER_ATTACHMENT});
  this.depth=this.d.createTexture({size,format:'depth32float',usage:GPUTextureUsage.RENDER_ATTACHMENT});
  this.group=this.d.createBindGroup({layout:this.o.pipeline.getBindGroupLayout(this.ground?3:2),entries:[{binding:0,resource:this.color.createView()},{binding:1,resource:this.sampler},{binding:2,resource:{buffer:this.uniform}}]});
 }
 bind(){this.cityGroup=this.d.createBindGroup({layout:this.o.pipeline.getBindGroupLayout(0),entries:this.o.rasterEntries(this.frame)});this.key=null;}
 draw(encoder,slot,matrix){
  const o=this.o,p=reflectionParameters(o.waterSettings,this.ground),state=reflectionState(o,matrix,o.eye,this.ground),data=new Float32Array(24);
  if(state){
   this.resize(state.size);data.set(state.matrix);data.set([state.height,p.strength,p.blur,p.distortion],16);data.set([...state.size,1,0],20);
   if(state.key!==this.key||this.chunks!==o.chunks){
    const frame=new Float32Array(o.frameData);frame.set(state.matrix);frame.set([...state.eye,0],32);frame[47]=state.height;
    this.d.queue.writeBuffer(this.frame,0,frame);
    const pass=encoder.beginRenderPass({...o.timer.pass(slot,this.name),colorAttachments:[{view:this.color.createView(),clearValue:[0,0,0,0],loadOp:'clear',storeOp:'store'}],depthStencilAttachment:{view:this.depth.createView(),depthClearValue:0,depthLoadOp:'clear',depthStoreOp:'store'}});
    pass.setPipeline(this.pipeline);pass.setBindGroup(0,this.cityGroup);pass.setBindGroup(1,o.ocean.cityGroups[o.ocean.foamCur]);
    const meshes=reflectionChunks(o,state.matrix,state.height,this.ground);this.triangles=0;
    for(const c of meshes){pass.setVertexBuffer(0,c.vertex,c.vertexOffset??0,c.vertexBytes);pass.setIndexBuffer(c.index,'uint32',c.indexOffset??0,c.indexBytes);pass.drawIndexed(c.triangles*3,c.instanceCount,0,0,c.instanceFirst);this.triangles+=c.triangles*c.instanceCount;}
    pass.end();o.stats.draws+=meshes.length;this.updates++;this.key=state.key;this.chunks=o.chunks;
   }
  }
  this.d.queue.writeBuffer(this.uniform,0,data);
  o.canvas.dataset[this.name]=JSON.stringify({enabled:!!state,height:state?.height,size:this.size,updates:this.updates,triangles:this.triangles??0,gpuMs:o[this.name+'Ms']??null,bytes:this.size[0]*this.size[1]*12});
  o.syncReflectionStatus?.();
 }
 dispose(){for(const r of [this.frame,this.uniform,this.color,this.depth])r?.destroy();}
}
