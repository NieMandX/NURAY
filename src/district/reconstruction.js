// Temporal history contains fresh path samples only, never the spatially filtered
// display image. This avoids feeding blur back into later frames.
export class MeshReconstruction {
  constructor(tracer){this.tracer=tracer;this.bytes=0;this.version=0;this.ms=0;this.guideMs=0;this.invalidate();}
  invalidate(){this.valid=false;this.guideValid=false;this.previous=null;this.version++;}
  async init(common,mesh,guide,temporal,denoise){
    const d=this.tracer.owner.device;
    const compile=async(code,label,entryPoint)=>{
      const module=d.createShaderModule({code,label});
      const errors=(await module.getCompilationInfo()).messages.filter(x=>x.type==='error');
      if(errors.length)throw new Error(label+': '+errors.map(x=>`${x.lineNum}: ${x.message}`).join('\n'));
      return d.createComputePipelineAsync({label,layout:'auto',compute:{module,entryPoint}});
    };
    this.guidePipeline=await compile(common+'\n'+mesh+'\n'+guide,'Reprojection primary surfaces','guideMain');
    this.temporalPipeline=await compile(temporal,'Validated temporal reprojection','temporalMain');
    this.filterPipeline=await compile(denoise,'Edge-aware reconstruction','denoiseMain');
    this.uniform=d.createBuffer({size:112,usage:GPUBufferUsage.UNIFORM|GPUBufferUsage.COPY_DST});
    this.filterUniforms=[1,2,4].map(()=>d.createBuffer({size:16,usage:GPUBufferUsage.UNIFORM|GPUBufferUsage.COPY_DST}));
  }
  release(){
    for(const b of [...this.guides??[],...this.history??[],...this.scratch??[]])b.destroy();
    this.guides=null;this.history=null;this.scratch=null;this.bytes=0;this.groups=new Map();this.invalidate();
  }
  ensure(){
    if(this.guides)return;
    const t=this.tracer,o=t.owner,d=o.device,n=o.canvas.width*o.canvas.height;
    const buffer=(size,label)=>d.createBuffer({size,label,usage:GPUBufferUsage.STORAGE|GPUBufferUsage.COPY_SRC});
    this.guides=[0,1].map(()=>buffer(n*48,'Reprojection surfaces'));
    this.history=[0,1].map(()=>buffer(n*16,'Unfiltered temporal radiance'));
    this.scratch=[0,1].map(()=>buffer(n*16,'Spatial reconstruction'));
    this.bytes=n*160;this.gi=0;this.hi=0;this.groups=new Map();this.bind();
  }
  bind(){
    if(!this.guides||!this.tracer.scene)return;
    const t=this.tracer,d=t.owner.device;
    this.guideGroups=this.guides.map(buffer=>d.createBindGroup({layout:this.guidePipeline.getBindGroupLayout(0),entries:t.geometryEntries().map(e=>e.binding===1?{binding:1,resource:{buffer}}:e)}));
    this.displayGroup=d.createBindGroup({layout:t.display.getBindGroupLayout(0),entries:[{binding:0,resource:{buffer:t.uniform}},{binding:1,resource:{buffer:this.scratch[0]}}]});
    this.groups.clear();this.invalidate();
  }
  group(key,pipeline,buffers){
    if(!this.groups.has(key))this.groups.set(key,this.tracer.owner.device.createBindGroup({layout:pipeline.getBindGroupLayout(0),entries:buffers.map((buffer,binding)=>({binding,resource:{buffer}}))}));
    return this.groups.get(key);
  }
  encode(encoder,slot,data){
    this.ensure();const o=this.tracer.owner,d=o.device,w=data[0],h=data[1];
    const camera=Array.from(data.slice(4,20));
    const moved=!!this.previous&&camera.some((x,i)=>x!==this.previous[i]);
    let usable=this.valid;
    if(moved){
      const a=camera,b=this.previous;
      const dot=a[12]*b[12]+a[13]*b[13]+a[14]*b[14];
      const shift=Math.hypot(a[0]-b[0],a[1]-b[1],a[2]-b[2]);
      // Camera cuts and large teleports start fresh rather than borrowing unrelated views.
      usable&&=dot>.9&&shift<o.camera.distance*.2&&Math.abs(a[7]/b[7]-1)<.15;
    }
    const previousGuide=this.gi;
    const updateGuide=moved||!this.guideValid;
    if(updateGuide){
      this.gi=1-this.gi;
      const pass=encoder.beginComputePass(o.timer.pass(slot,'guides'));
      pass.setPipeline(this.guidePipeline);pass.setBindGroup(0,this.guideGroups[this.gi]);pass.dispatchWorkgroups(Math.ceil(w/8),Math.ceil(h/8));pass.end();
    }
    const params=new Float32Array(28);params.set([w,h,usable?1:0,moved?1:0]);params.set(this.previous??camera,4);
    params.set([...camera.slice(0,3),camera[7]],20);params.set([this.tracer.batch,0,0,0],24);d.queue.writeBuffer(this.uniform,0,params);
    const next=1-this.hi;
    const group=this.group(`t${this.hi}${this.gi}${previousGuide}`,this.temporalPipeline,[this.uniform,this.tracer.accumulation,this.guides[this.gi],this.guides[previousGuide],this.history[this.hi],this.history[next]]);
    const pass=encoder.beginComputePass(o.timer.pass(slot,'reconstruct'));pass.setPipeline(this.temporalPipeline);pass.setBindGroup(0,group);pass.dispatchWorkgroups(Math.ceil(w/8),Math.ceil(h/8));pass.end();
    for(let i=0;i<3;i++){
      d.queue.writeBuffer(this.filterUniforms[i],0,Float32Array.of(w,h,1<<i,camera[7]));
      const source=i===0?this.history[next]:this.scratch[(i-1)%2],target=this.scratch[i%2];
      const filter=this.group(`f${next}${this.gi}${i}`,this.filterPipeline,[this.filterUniforms[i],source,this.guides[this.gi],target]);
      const p=encoder.beginComputePass(o.timer.pass(slot,'reconstruct'));p.setPipeline(this.filterPipeline);p.setBindGroup(0,filter);p.dispatchWorkgroups(Math.ceil(w/8),Math.ceil(h/8));p.end();
    }
    this.hi=next;this.previous=camera;this.valid=true;this.guideValid=true;this.reprojected=usable&&moved;
  }
}
