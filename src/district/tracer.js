import {normalize} from './math.js';
const cross=(a,b)=>[a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]];
export class MeshTracer {
  constructor(owner){this.owner=owner;this.pages=[];this.samples=0;this.seed=0;this.key='';this.limit=256;}
  async init(){
    const d=this.owner.device;
    const read=async path=>{const r=await fetch(new URL(path,import.meta.url),{cache:'no-store'});if(!r.ok)throw new Error(`Не найден ${path}`);return r.text();};
    const [common,mesh,display]=await Promise.all([read('../common.wgsl'),read('./trace.wgsl'),read('../display.wgsl')]);
    const modules=[d.createShaderModule({label:'Mesh transport: shared sphere optics + BVH',code:common+'\n'+mesh}),d.createShaderModule({code:display})];
    for(const m of modules){const errors=(await m.getCompilationInfo()).messages.filter(e=>e.type==='error');if(errors.length)throw new Error(errors.map(e=>`${e.lineNum}: ${e.message}`).join('\n'));}
    this.pipeline=await d.createComputePipelineAsync({layout:'auto',compute:{module:modules[0],entryPoint:'meshMain'}});
    this.display=await d.createRenderPipelineAsync({layout:'auto',vertex:{module:modules[1],entryPoint:'vertex'},fragment:{module:modules[1],entryPoint:'fragment',targets:[{format:this.owner.format}]},primitive:{topology:'triangle-list'}});
    this.uniform=d.createBuffer({size:144,usage:GPUBufferUsage.UNIFORM|GPUBufferUsage.COPY_DST});
    this.dummy=d.createBuffer({size:4,usage:GPUBufferUsage.STORAGE});
  }
  allocate(plan){
    const d=this.owner.device;
    this.pages=plan.sizes.map(size=>d.createBuffer({label:'Mesh + BLAS page',size,usage:GPUBufferUsage.STORAGE|GPUBufferUsage.COPY_DST}));
    this.scene=d.createBuffer({size:plan.scene.byteLength,usage:GPUBufferUsage.STORAGE|GPUBufferUsage.COPY_DST});d.queue.writeBuffer(this.scene,0,plan.scene);
    this.owner.stats.bvhBytes=plan.scene.byteLength;
  }
  upload(chunk){
    const d=chunk.descriptor,queue=this.owner.device.queue,page=this.pages[d.page];
    queue.writeBuffer(page,d.vertex*4,chunk.vertices);queue.writeBuffer(page,d.index*4,chunk.indices);queue.writeBuffer(page,d.nodes*4,chunk.nodes);
    this.owner.stats.bvhBytes+=chunk.nodes.byteLength;
  }
  resize(){
    const o=this.owner,d=o.device;this.accumulation?.destroy();
    this.accumulation=d.createBuffer({size:o.canvas.width*o.canvas.height*16,usage:GPUBufferUsage.STORAGE|GPUBufferUsage.COPY_SRC});
    this.displayGroup=d.createBindGroup({layout:this.display.getBindGroupLayout(0),entries:[{binding:0,resource:{buffer:this.uniform}},{binding:1,resource:{buffer:this.accumulation}}]});
    this.bind();this.reset();
  }
  bind(){
    if(!this.scene||!this.accumulation)return;const o=this.owner;
    this.group=o.device.createBindGroup({layout:this.pipeline.getBindGroupLayout(0),entries:[
      ...[this.uniform,this.accumulation,o.materialBuffer,this.scene,...Array.from({length:4},(_,i)=>this.pages[i]??this.dummy)].map((buffer,binding)=>({binding,resource:{buffer}})),
      {binding:8,resource:o.textures[0].createView({dimension:'2d-array'})},{binding:9,resource:o.textures[2].createView({dimension:'2d-array'})},{binding:10,resource:o.sampler},
    ]});this.reset();
  }
  reset(){this.samples=0;this.key='';this.owner.gpu=null;this.owner.revision++;}
  release(){this.pages.forEach(p=>p.destroy());this.pages=[];this.scene?.destroy();this.scene=null;this.group=null;this.reset();}
  frame(time){
    const o=this.owner;if(o.inFlight>=1||!this.group)return;
    const c=o.camera,s=o.state;const key=JSON.stringify([c,s.materials,s.textures,s.indirect,s.bounces,s.ior,s.exposure]);
    if(key!==this.key){this.reset();this.key=key;o.lastTime=0;}
    if(this.samples>=this.limit){o.publish();return;}
    const eye=[Math.sin(c.yaw)*Math.cos(c.pitch)*c.distance+c.target[0],Math.sin(c.pitch)*c.distance+c.target[1],Math.cos(c.yaw)*Math.cos(c.pitch)*c.distance+c.target[2]];
    const forward=normalize(c.target.map((n,i)=>n-eye[i])),right=normalize(cross(forward,[0,1,0])),up=cross(right,forward);
    const data=new Float32Array(36),w=o.canvas.width,h=o.canvas.height;
    data.set([w,h,this.samples,this.seed],0);data.set([...eye,0],4);data.set([...right,Math.tan(44*Math.PI/360)*Math.max(1,1.1/(w/h))],8);
    data.set([...up,0],12);data.set([...forward,0],16);data.set([...o.sun,1],20);
    data.set([s.materials,s.indirect?1:0,s.textures?1:0,0],24);data.set([s.ior,1,s.exposure,s.bounces],28);data.set([1,0,0,0],32);
    o.device.queue.writeBuffer(this.uniform,0,data);
    const dt=o.lastTime?time-o.lastTime:16.7;o.lastTime=time;o.frameMs=o.frameMs*.9+dt*.1;
    const encoder=o.device.createCommandEncoder(),slot=o.timer.begin({revision:o.revision,dt,trace:true});
    const pass=encoder.beginComputePass(o.timer.pass(slot,'path'));pass.setPipeline(this.pipeline);pass.setBindGroup(0,this.group);pass.dispatchWorkgroups(Math.ceil(w/8),Math.ceil(h/8));pass.end();
    const show=encoder.beginRenderPass({...o.timer.pass(slot,'display'),colorAttachments:[{view:o.context.getCurrentTexture().createView(),loadOp:'clear',storeOp:'store'}]});
    show.setPipeline(this.display);show.setBindGroup(0,this.displayGroup);show.draw(3);show.end();o.timer.resolve(encoder,slot);
    o.device.queue.submit([encoder.finish()]);this.samples++;this.seed++;o.inFlight++;
    o.timer.read(slot);o.device.queue.onSubmittedWorkDone().then(()=>{o.inFlight--;o.publish(true);}).catch(e=>o.fail(e.message));
    o.stats.submitted=o.stats.expanded??o.stats.triangles;o.stats.draws=0;o.publish();
  }
}
