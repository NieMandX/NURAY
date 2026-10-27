export class ContactAO {
 constructor(owner){this.owner=owner;}
 async init(){
  const o=this.owner,d=o.device,r=await fetch(new URL('./contact-ao.wgsl',import.meta.url),{cache:'no-store'});
  if(!r.ok)throw Error('Не найден шейдер контактных теней');const module=d.createShaderModule({code:await r.text()});
  const errors=(await module.getCompilationInfo()).messages.filter(m=>m.type==='error');if(errors.length)throw Error(errors.map(e=>e.message).join('\n'));
  this.pipeline=await d.createRenderPipelineAsync({layout:'auto',vertex:{module,entryPoint:'vertex'},fragment:{module,entryPoint:'fragment',targets:[{format:'r8unorm'}]},primitive:{topology:'triangle-list'}});
  this.composite=await d.createRenderPipelineAsync({layout:'auto',vertex:{module,entryPoint:'vertex'},fragment:{module,entryPoint:'composite',targets:[{format:o.sceneFormat||o.format}]},primitive:{topology:'triangle-list'}});
  this.uniform=d.createBuffer({size:96,usage:GPUBufferUsage.UNIFORM|GPUBufferUsage.COPY_DST});
 }
 resize(width,height){
  const o=this.owner,d=o.device;this.color?.destroy();this.contact?.destroy();
  this.color=d.createTexture({size:[width,height],format:o.sceneFormat||o.format,usage:GPUTextureUsage.RENDER_ATTACHMENT|GPUTextureUsage.TEXTURE_BINDING});
  this.contact=d.createTexture({size:[width,height],format:'r8unorm',usage:GPUTextureUsage.RENDER_ATTACHMENT|GPUTextureUsage.TEXTURE_BINDING});
  this.group=d.createBindGroup({layout:this.pipeline.getBindGroupLayout(0),entries:[{binding:0,resource:{buffer:this.uniform}},{binding:2,resource:o.depth.createView()}]});
  this.compositeGroup=d.createBindGroup({layout:this.composite.getBindGroupLayout(0),entries:[{binding:0,resource:{buffer:this.uniform}},{binding:1,resource:this.color.createView()},{binding:2,resource:o.depth.createView()},{binding:3,resource:this.contact.createView()}]});
 }
 draw(encoder,slot,inverse,eye){
  const o=this.owner,data=new Float32Array(24);data.set(inverse);data.set([...eye,0],16);data.set([o.canvas.width,o.canvas.height,2.4,1.2],20);o.device.queue.writeBuffer(this.uniform,0,data);
  const pass=encoder.beginRenderPass({...o.timer.pass(slot,'contactAO'),colorAttachments:[{view:this.contact.createView(),loadOp:'clear',storeOp:'store'}]});
  pass.setPipeline(this.pipeline);pass.setBindGroup(0,this.group);pass.draw(3);pass.end();
  const composite=encoder.beginRenderPass({...o.timer.pass(slot,'contactComposite'),colorAttachments:[{view:o.ocean?o.ocean.hdr.createView():o.context.getCurrentTexture().createView(),loadOp:'clear',storeOp:'store'}]});
  composite.setPipeline(this.composite);composite.setBindGroup(0,this.compositeGroup);composite.draw(3);composite.end();
 }
}
