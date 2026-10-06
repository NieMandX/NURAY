import {CASCADE_LEVELS,CACHE_LIMIT,cacheField,cascadeBytes} from './cascade-config.js';
export class MeshCascadeCache {
  constructor(tracer){this.tracer=tracer;this.samples=0;this.limit=CACHE_LIMIT;this.version=0;this.updates=0;this.key='';this.ms=null;}
  async init(common,mesh,cascades,irradiance){
    const d=this.tracer.owner.device;
    const compile=async(code,label,entryPoint)=>{
      const module=d.createShaderModule({code,label});
      const errors=(await module.getCompilationInfo()).messages.filter(x=>x.type==='error');
      if(errors.length)throw new Error(label+': '+errors.map(x=>`${x.lineNum}: ${x.message}`).join('\n'));
      return d.createComputePipelineAsync({label,layout:'auto',compute:{module,entryPoint}});
    };
    this.pipeline=await compile(common+'\n'+mesh+'\n'+cascades,'Mesh radiance cascades','cascadeMain');
    this.convolution=await compile(irradiance,'Mesh irradiance convolution','main');
    this.levels=CASCADE_LEVELS.map(dims=>d.createBuffer({size:dims[0]*dims[1]*dims[2]*dims[3]*dims[3]*16,usage:GPUBufferUsage.STORAGE}));
    this.irradiance=d.createBuffer({size:2048*6*16,usage:GPUBufferUsage.STORAGE|GPUBufferUsage.COPY_SRC});
    this.fieldUniform=d.createBuffer({size:32,usage:GPUBufferUsage.UNIFORM|GPUBufferUsage.COPY_DST});
    this.levelUniforms=CASCADE_LEVELS.map(()=>d.createBuffer({size:80,usage:GPUBufferUsage.UNIFORM|GPUBufferUsage.COPY_DST}));
    this.empty=d.createBuffer({size:16,usage:GPUBufferUsage.STORAGE});
    this.groups=CASCADE_LEVELS.map((_,i)=>d.createBindGroup({layout:this.pipeline.getBindGroupLayout(1),entries:[
      {binding:0,resource:{buffer:this.levelUniforms[i]}},{binding:1,resource:{buffer:this.levels[i+1]??this.empty}},{binding:2,resource:{buffer:this.levels[i]}},
    ]}));
    this.convolutionGroup=d.createBindGroup({layout:this.convolution.getBindGroupLayout(0),entries:[
      {binding:0,resource:{buffer:this.levels[0]}},{binding:1,resource:{buffer:this.irradiance}},
    ]});
    this.bytes=cascadeBytes();
  }
  bind(){
    const t=this.tracer,d=t.owner.device;
    this.geometry=d.createBindGroup({layout:this.pipeline.getBindGroupLayout(0),entries:t.geometryEntries().filter(e=>e.binding!==1)});
    this.pathGroup=d.createBindGroup({layout:t.pipeline.getBindGroupLayout(1),entries:[
      {binding:0,resource:{buffer:this.fieldUniform}},{binding:1,resource:{buffer:this.irradiance}},
    ]});
  }
  invalidate(){this.key='';this.samples=0;this.ms=null;}
  sync(){
    const o=this.tracer.owner,s=o.state;
    const field=cacheField(o.camera,o.sceneName==='moscow',this.field);
    const key=JSON.stringify([field.key,o.sun,s.materials,s.textures,s.ior,s.bounces]);
    if(key===this.key)return false;
    this.key=key;this.field=field;this.samples=0;this.version++;this.ms=null;
    const d=o.device;d.queue.writeBuffer(this.fieldUniform,0,Float32Array.from([...field.min,0,...field.size,0]));
    const step=field.size[0]/16,ends=[0,step,step*3,step*9,1e20];
    CASCADE_LEVELS.forEach((dims,i)=>{
      const data=new ArrayBuffer(80),f=new Float32Array(data),u=new Uint32Array(data);
      f.set([...field.min,0,...field.size,0]);u.set(dims,8);u.set(CASCADE_LEVELS[i+1]??[1,1,1,1],12);
      f.set([ends[i],ends[i+1],i<3?1:0,0],16);d.queue.writeBuffer(this.levelUniforms[i],0,data);
    });
    return true;
  }
  encode(encoder,slot){
    const timer=this.tracer.owner.timer;
    for(let i=3;i>=0;i--){
      const p=encoder.beginComputePass(timer.pass(slot,'cascade'));p.setPipeline(this.pipeline);p.setBindGroup(0,this.geometry);p.setBindGroup(1,this.groups[i]);
      const a=CASCADE_LEVELS[i];p.dispatchWorkgroups(Math.ceil(a[0]*a[1]*a[2]*a[3]*a[3]/64));p.end();
    }
    const p=encoder.beginComputePass(timer.pass(slot,'irradiance'));p.setPipeline(this.convolution);p.setBindGroup(0,this.convolutionGroup);p.dispatchWorkgroups(192);p.end();
  }
}
