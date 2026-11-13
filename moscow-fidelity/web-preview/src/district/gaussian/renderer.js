import {compactMeshInstances,replacementSet} from './model.js?v=gs-16';

export class GaussianVegetation {
  constructor(owner){this.owner=owner;this.enabled=false;this.active=new Set();this.replaced=new Set();this.resources=[];this.reflections=new Map();this.count=0;this.budget=350000;}
  async open(url){
    const d=this.owner.device;d.pushErrorScope('validation');
    try{await this.load(url);}finally{const error=await d.popErrorScope();if(error)throw Error(error.message);}
  }
  async load(url){
    const d=this.owner.device;
    const response=await fetch(url,{cache:'no-store'});if(!response.ok)throw Error('Не найден каталог сплатов');
    this.manifest=await response.json();
    if(this.manifest.format!=='nuray-vegetation-splats-v1')throw Error('Неверный каталог сплатов');
    if(this.manifest.sourceHeaderSha256!==this.owner.mergedHeaderSha256)throw Error('Сплаты подготовлены для другой версии сцены');
    const all=[],models=[];let offset=0;
    for(const file of this.manifest.models){
      const r=await fetch(new URL(file,url),{cache:'no-store'});if(!r.ok)throw Error('Не найден шаблон сплатов');
      const model=await r.json(),b=await fetch(new URL(model.file,url));if(!b.ok)throw Error('Не найдены сплаты растения');
      const bytes=await b.arrayBuffer();
      const hash=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes)),x=>x.toString(16).padStart(2,'0')).join('');
      if(bytes.byteLength!==model.bytes||hash!==model.sha256||bytes.byteLength%64)throw Error('Повреждён шаблон сплатов');
      all.push(new Float32Array(bytes));models.push({...model,offset});offset+=bytes.byteLength/64;
    }
    const points=new Float32Array(offset*16);let at=0;for(const p of all){points.set(p,at);at+=p.length;}
    const buffer=(label,bytes,usage)=>{const b=d.createBuffer({label,size:Math.max(16,bytes.byteLength??bytes),usage:usage|GPUBufferUsage.COPY_DST});if(bytes.byteLength)d.queue.writeBuffer(b,0,bytes);this.resources.push(b);return b;};
    this.points=buffer('Shared Gaussian plant templates',points,GPUBufferUsage.STORAGE);
    const matrices=new Float32Array(this.manifest.instances.flatMap(i=>i.matrix));
    this.transforms=buffer('Gaussian plant transforms',matrices,GPUBufferUsage.STORAGE);
    this.replaced=replacementSet(this.manifest,this.owner.chunks,models);
    {
      const compact=compactMeshInstances(this.owner.chunks,this.owner.mergedTransforms,this.replaced);
      this.meshCounts=compact.counts;
      this.meshTransforms=buffer('Main-pass instances without plant proxies',compact.transforms,GPUBufferUsage.STORAGE);
    }
    this.order=buffer('Visible Gaussian order',this.budget*8,GPUBufferUsage.STORAGE);
    this.uniform=buffer('Gaussian view',80,GPUBufferUsage.UNIFORM);
    const source=await fetch(new URL('./gaussian.wgsl',import.meta.url),{cache:'no-store'});
    if(!source.ok)throw Error('Не найден Gaussian shader');
    const module=d.createShaderModule({label:'Vegetation 3DGS',code:await source.text()});
    const errors=(await module.getCompilationInfo()).messages.filter(m=>m.type==='error');if(errors.length)throw Error(errors.map(e=>`${e.lineNum}: ${e.message}`).join('\n'));
    this.pipeline=await d.createRenderPipelineAsync({label:'Gaussian vegetation',layout:'auto',vertex:{module,entryPoint:'vertex'},fragment:{module,entryPoint:'fragment',targets:[{format:this.owner.sceneFormat,blend:{color:{srcFactor:'one',dstFactor:'one-minus-src-alpha'},alpha:{srcFactor:'one',dstFactor:'one-minus-src-alpha'}}}]},primitive:{topology:'triangle-list'},depthStencil:{format:'depth32float',depthWriteEnabled:false,depthCompare:'greater-equal'}});
    this.group=d.createBindGroup({layout:this.pipeline.getBindGroupLayout(0),entries:[this.uniform,this.points,this.transforms,this.order].map((buffer,binding)=>({binding,resource:{buffer}}))});
    this.worker=new Worker(new URL('./worker.js?v=gs-16',import.meta.url),{type:'module'});
    this.worker.onerror=e=>this.fail(e.message);
    this.worker.onmessage=({data})=>{
      if(data.type==='error'){this.fail(data.message);return;}
      if(data.type==='ready'){this.workerReady=true;this.owner.revision++;return;}
      if(data.type==='sorted'&&data.channel!=='main'){
        const r=this.reflections.get(data.channel);if(!r)return;
        r.busy=false;r.count=data.pairs.length/2;
        if(r.count)d.queue.writeBuffer(r.order,0,data.pairs);
        r.capture.key=null;this.owner.revision++;return;
      }
      if(data.type!=='sorted')return;this.busy=false;
      this.count=data.pairs.length/2;this.sortMs=data.ms;this.detail=data.detail;
      if(this.count)d.queue.writeBuffer(this.order,0,data.pairs);
      const active=new Set(data.active.map(i=>this.manifest.instances[i].sourceInstance));
      this.active=active;
      this.owner.revision++;this.updateStatus();
    };
    this.worker.postMessage({type:'init',points,models,instances:this.manifest.instances},[points.buffer]);
    this.bytes=this.resources.reduce((n,b)=>n+b.size,0);this.updateStatus();
  }
  fail(message){console.error('Gaussian vegetation:',message);this.enabled=false;this.error=message;this.active.clear();this.owner.revision++;this.updateStatus();}
  available(){return this.enabled&&this.owner.state.engine==='raster'&&this.owner.sceneLayers?.vegetation!==false;}
  setEnabled(value){this.enabled=!!value;this.owner.revision++;this.updateStatus();}
  prepare(matrix){
    if(!this.available())return;
    const o=this.owner,data=new Float32Array(20);data.set(matrix);data.set([o.canvas.width,o.canvas.height,0,0],16);o.device.queue.writeBuffer(this.uniform,0,data);
    const key=Array.from(matrix).join(',')+','+o.canvas.width+','+o.canvas.height;
    if(!this.workerReady||this.busy||key===this.lastKey)return;
    this.busy=true;this.lastKey=key;this.worker.postMessage({type:'view',key,matrix,width:o.canvas.width,height:o.canvas.height,budget:this.budget,eye:o.eye});
  }
  chunks(chunks){
    if(!this.available()||!this.replaced.size)return chunks;
    return chunks.map(c=>this.meshCounts?.has(c.id)?{...c,instanceCount:this.meshCounts.get(c.id)}:c).filter(c=>c.instanceCount>0);
  }
  meshGroup(original){
    if(!this.available()||!this.replaced.size)return original;
    if(this.originalGroup!==original){
      this.originalGroup=original;
      const o=this.owner,entries=o.rasterEntries(o.uniform).map(e=>e.binding===8?{binding:8,resource:{buffer:this.meshTransforms}}:e);
      this.compactGroup=o.device.createBindGroup({layout:o.pipeline.getBindGroupLayout(0),entries});
    }
    return this.compactGroup;
  }
  draw(encoder,slot){
    if(!this.available()||!this.count)return;
    const o=this.owner,pass=encoder.beginRenderPass({...o.timer.pass(slot,'gaussian'),label:'Gaussian plants',colorAttachments:[{view:o.ocean?o.ocean.hdr.createView():o.context.getCurrentTexture().createView(),loadOp:'load',storeOp:'store'}],depthStencilAttachment:{view:o.depth.createView(),depthReadOnly:true}});
    pass.setPipeline(this.pipeline);pass.setBindGroup(0,this.group);pass.draw(6,this.count);pass.end();o.stats.draws++;
  }
  reflectionGroup(capture){
    if(!this.available())return capture.cityGroup;
    if(capture.gsOwner!==this){
      capture.gsOwner=this;
      capture.gsCityGroup=this.owner.device.createBindGroup({layout:this.owner.pipeline.getBindGroupLayout(0),entries:this.owner.rasterEntries(capture.frame).map(e=>e.binding===8?{binding:8,resource:{buffer:this.meshTransforms}}:e)});
    }
    return capture.gsCityGroup;
  }
  drawReflection(encoder,capture,state){
    if(!this.available()||!this.count)return;
    const o=this.owner,d=o.device,channel=capture.name;
    let r=this.reflections.get(channel);
    if(!r){
      const make=(size,usage)=>{const b=d.createBuffer({size,usage:usage|GPUBufferUsage.COPY_DST});this.resources.push(b);return b;};
      r={capture,count:0,uniform:make(80,GPUBufferUsage.UNIFORM),order:make(this.budget*8,GPUBufferUsage.STORAGE)};
      r.group=d.createBindGroup({layout:this.pipeline.getBindGroupLayout(0),entries:[r.uniform,this.points,this.transforms,r.order].map((buffer,binding)=>({binding,resource:{buffer}}))});
      this.reflections.set(channel,r);this.bytes=this.resources.reduce((n,b)=>n+b.size,0);
    }
    const data=new Float32Array(20);data.set(state.matrix);data.set([...state.size,state.height,1],16);d.queue.writeBuffer(r.uniform,0,data);
    const key=Array.from(state.matrix).join(',')+','+state.size;
    if(this.workerReady&&!r.busy&&r.key!==key){r.busy=true;r.key=key;this.worker.postMessage({type:'view',channel,key,matrix:state.matrix,width:state.size[0],height:state.size[1],budget:this.budget,eye:state.eye});}
    if(!r.count)return;
    const pass=encoder.beginRenderPass({label:'Reflected Gaussian plants',colorAttachments:[{view:capture.color.createView(),loadOp:'load',storeOp:'store'}],depthStencilAttachment:{view:capture.depth.createView(),depthReadOnly:true}});
    pass.setPipeline(this.pipeline);pass.setBindGroup(0,r.group);pass.draw(6,r.count);pass.end();o.stats.draws++;
  }
  updateStatus(){
    this.owner.stats.gaussians=this.available()?this.count:0;this.owner.stats.gaussianBytes=this.bytes??0;
    this.owner.stats.gaussianPlants=this.available()?this.active.size:0;
    this.owner.canvas.dataset.gaussians=JSON.stringify({enabled:this.enabled,active:this.available(),plants:this.active.size,replaced:this.replaced.size,count:this.count,bytes:this.bytes,sortMs:this.sortMs,detail:this.detail,error:this.error??null});
    this.onStatus?.();
  }
  dispose(){this.worker?.terminate();for(const b of this.resources)b.destroy();this.resources=[];}
}
