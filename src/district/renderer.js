import {GpuTimer} from '../gpu-timer.js?v=temporal-1';
import {makeMaterials,TEXTURE_SIZE,textureBytes} from './materials.js';
import {lookAt,perspective,orthographic,multiply,normalize,visible} from './math.js?v=city-2';
import {MeshTracer} from './tracer.js?v=temporal-1';
import {loadCityMaterials} from './city-materials.js?v=nuray-cloud-1';
import {identityTransform} from './bvh.js';
import {cityManifest} from './city-config.js?v=nuray-cloud-1';
import {renderSize} from './resolution.js?v=temporal-1';
export const cameraDefaults=()=>({yaw:.64,pitch:.78,distance:160,target:[0,3,0]});
const vertexLayout={arrayStride:32,attributes:[{shaderLocation:0,offset:0,format:'float32x3'},{shaderLocation:1,offset:12,format:'snorm16x2'},{shaderLocation:2,offset:16,format:'float32x2'},{shaderLocation:3,offset:24,format:'uint32'}]};
const median=values=>{const a=[...values].sort((x,y)=>x-y);return a[Math.floor(a.length/2)];};
export class DistrictRenderer {
  constructor(canvas,onStatus,onError){
    this.canvas=canvas;this.onStatus=onStatus;this.onError=onError;
    this.camera=cameraDefaults();this.state={materials:15,textures:true,culling:true,shadows:true,engine:'trace',reconstruction:true,indirect:true,bounces:8,ior:1.5,pixels:180000,exposure:1.03};this.sceneName='district';
    this.tracer=new MeshTracer(this);
    this.chunks=[];this.revision=0;this.inFlight=0;this.running=false;this.ready=false;this.loading=false;
    this.lastTime=0;this.frameMs=16.7;this.lastStatus=0;this.stats={triangles:0,vertices:0,geometryBytes:0,textureBytes:0,buildMs:0,uploadMs:0,submitted:0,draws:0};
    this.shadowDirty=true;this.shadowMs=0;this.gpu=null;this.measurement=null;
  }
  async init(){
    if(!navigator.gpu)throw new Error('Этот браузер не предоставляет WebGPU.');
    const adapter=await navigator.gpu.requestAdapter({powerPreference:'high-performance'});
    if(!adapter)throw new Error('WebGPU-адаптер недоступен.');
    this.pageLimit=Math.min(268435456,adapter.limits.maxStorageBufferBindingSize,adapter.limits.maxBufferSize);
    this.device=await adapter.requestDevice({requiredFeatures:adapter.features.has('timestamp-query')?['timestamp-query']:[],requiredLimits:{maxStorageBufferBindingSize:this.pageLimit,maxBufferSize:this.pageLimit}});
    this.device.addEventListener('uncapturederror',e=>this.fail(e.error.message));
    this.device.lost.then(info=>{if(info.reason!=='destroyed')this.fail(`GPU: ${info.message}`);});
    this.timer=new GpuTimer(this.device,(times,meta)=>this.timing(times,meta),()=>{this.gpu=null;this.publish(true);});
    this.context=this.canvas.getContext('webgpu');this.format=navigator.gpu.getPreferredCanvasFormat();
    this.context.configure({device:this.device,format:this.format,alphaMode:'opaque'});
    this.uniform=this.device.createBuffer({size:192,usage:GPUBufferUsage.UNIFORM|GPUBufferUsage.COPY_DST});
    const shaders=await Promise.all(['district','textures'].map(async name=>{
      const response=await fetch(new URL(`${name}.wgsl`,import.meta.url),{cache:'no-store'});
      if(!response.ok)throw new Error(`Не найден ${name}.wgsl`);
      const module=this.device.createShaderModule({label:name,code:await response.text()});
      const errors=(await module.getCompilationInfo()).messages.filter(m=>m.type==='error');
      if(errors.length)throw new Error(`${name}: `+errors.map(e=>`${e.lineNum}: ${e.message}`).join('\n'));return module;
    }));
    this.pipeline=await this.device.createRenderPipelineAsync({label:'District PBR raster',layout:'auto',vertex:{module:shaders[0],entryPoint:'vertex',buffers:[vertexLayout]},fragment:{module:shaders[0],entryPoint:'fragment',targets:[{format:this.format}]},primitive:{topology:'triangle-list',cullMode:'back'},depthStencil:{format:'depth32float',depthWriteEnabled:true,depthCompare:'greater'}});
    this.shadowPipeline=await this.device.createRenderPipelineAsync({label:'Static sunlight shadow map',layout:'auto',vertex:{module:shaders[0],entryPoint:'shadowVertex',buffers:[{arrayStride:32,attributes:[vertexLayout.attributes[0]]}]},primitive:{topology:'triangle-list',cullMode:'back'},depthStencil:{format:'depth32float',depthWriteEnabled:true,depthCompare:'less',depthBias:2,depthBiasSlopeScale:1.5}});
    this.texturePipeline=await this.device.createComputePipelineAsync({label:'Material texture arrays',layout:'auto',compute:{module:shaders[1],entryPoint:'main'}});
    this.shadowTexture=this.device.createTexture({size:[2048,2048],format:'depth32float',usage:GPUTextureUsage.RENDER_ATTACHMENT|GPUTextureUsage.TEXTURE_BINDING});
    this.setInstances(new Float32Array(identityTransform()).buffer);
    this.sampler=this.device.createSampler({magFilter:'linear',minFilter:'linear',mipmapFilter:'linear',addressModeU:'repeat',addressModeV:'repeat',maxAnisotropy:4});
    this.shadowSampler=this.device.createSampler({compare:'less-equal',magFilter:'linear',minFilter:'linear'});
    this.sun=normalize([-.62,1,.45]);this.shadowMatrix=multiply(orthographic(77,.1,330),lookAt(this.sun.map(x=>x*165),[0,0,0]));
    await this.tracer.init();
    await this.setMaterials(15);
    this.resizeObserver=new ResizeObserver(()=>this.resize());this.resizeObserver.observe(this.canvas);this.resize();
    this.running=true;this.raf=requestAnimationFrame(t=>this.frame(t));
    return adapter.info?.description||adapter.info?.architecture||'WebGPU';
  }
  resize(){
    if(!this.device)return;const r=this.canvas.getBoundingClientRect();
    const {width,height,limited}=renderSize(r.width,r.height,devicePixelRatio,this.state.pixels,this.device.limits,this.state.reconstruction?48:32);
    this.resolutionLimited=limited;this.pixelRatio=devicePixelRatio;
    if(width===this.canvas.width&&height===this.canvas.height&&this.depth)return;
    this.canvas.width=width;this.canvas.height=height;this.depth?.destroy();
    this.depth=this.device.createTexture({size:[width,height],format:'depth32float',usage:GPUTextureUsage.RENDER_ATTACHMENT});
    this.tracer.resize();
    this.gpu=null;this.revision++;this.cancelMeasurement('Размер окна изменился.');
  }
  async setMaterials(count){
    this.cancelMeasurement('Материалы изменились.');this.changing=true;this.revision++;this.gpu=null;
    await this.device.queue.onSubmittedWorkDone();
    this.materialBuffer?.destroy();this.textures?.forEach(t=>t.destroy());
    const data=makeMaterials(count);this.materialBuffer=this.device.createBuffer({size:data.byteLength,usage:GPUBufferUsage.STORAGE,mappedAtCreation:true});
    new Float32Array(this.materialBuffer.getMappedRange()).set(data);this.materialBuffer.unmap();
    const levels=Math.log2(TEXTURE_SIZE)+1;
    this.textures=Array.from({length:3},()=>this.device.createTexture({size:[TEXTURE_SIZE,TEXTURE_SIZE,count],mipLevelCount:levels,format:'rgba8unorm',usage:GPUTextureUsage.STORAGE_BINDING|GPUTextureUsage.TEXTURE_BINDING}));
    const encoder=this.device.createCommandEncoder();
    for(let mip=0;mip<levels;mip++){
      const entries=this.textures.map((t,binding)=>({binding,resource:t.createView({dimension:'2d-array',baseMipLevel:mip,mipLevelCount:1})}));
      entries.push({binding:3,resource:{buffer:this.materialBuffer}});
      const group=this.device.createBindGroup({layout:this.texturePipeline.getBindGroupLayout(0),entries});
      const p=encoder.beginComputePass();p.setPipeline(this.texturePipeline);p.setBindGroup(0,group);p.dispatchWorkgroups(Math.max(1,Math.ceil((TEXTURE_SIZE>>mip)/8)),Math.max(1,Math.ceil((TEXTURE_SIZE>>mip)/8)),count);p.end();
    }
    this.device.queue.submit([encoder.finish()]);
    this.bindRaster();
    this.state.materials=count;this.stats.textureBytes=textureBytes(count)+data.byteLength;
    await this.device.queue.onSubmittedWorkDone();this.tracer.cache.invalidate();this.tracer.bind();this.changing=false;this.publish(true);
  }
  setInstances(data){
    this.instanceBuffer?.destroy();this.instanceBuffer=this.device.createBuffer({size:data.byteLength,usage:GPUBufferUsage.STORAGE,mappedAtCreation:true});
    new Uint8Array(this.instanceBuffer.getMappedRange()).set(new Uint8Array(data));this.instanceBuffer.unmap();
    this.shadowGroup=this.device.createBindGroup({layout:this.shadowPipeline.getBindGroupLayout(0),entries:[{binding:0,resource:{buffer:this.uniform}},{binding:8,resource:{buffer:this.instanceBuffer}}]});
    if(this.textures)this.bindRaster();
  }
  bindRaster(){
    this.mainGroup=this.device.createBindGroup({layout:this.pipeline.getBindGroupLayout(0),entries:[
      {binding:0,resource:{buffer:this.uniform}},{binding:1,resource:{buffer:this.materialBuffer}},
      ...this.textures.map((t,i)=>({binding:i+2,resource:t.createView({dimension:'2d-array'})})),
      {binding:5,resource:this.sampler},{binding:6,resource:this.shadowTexture.createView()},{binding:7,resource:this.shadowSampler},
      {binding:8,resource:{buffer:this.instanceBuffer}},
    ]});
  }
  async load(triangles){
    this.cancelBuild();this.cancelMeasurement('Геометрия изменилась.');this.ready=false;this.loading=true;this.revision++;this.gpu=null;
    await this.device.queue.onSubmittedWorkDone();
    for(const c of this.chunks){c.vertex?.destroy();c.index?.destroy();}this.chunks=[];this.tracer.release();this.stats.bvhBytes=0;
    const city=triangles==='moscow',changed=this.sceneName!==(city?'moscow':'district');
    this.sceneName=city?'moscow':'district';
    if(city){
      if(!this.city){const r=await fetch(cityManifest);if(!r.ok)throw new Error('Не найден экспорт Москва-Сити');this.city=await r.json();}
      if(changed){this.state.exposure=.72;await loadCityMaterials(this,this.city);}
    }else if(changed){this.state.exposure=1.03;await this.setMaterials(15);}
    if(changed)this.resetCamera();
    this.setInstances(new Float32Array(identityTransform()).buffer);
    const extent=city?this.city.extentMetres*.75:77,dist=city?this.city.extentMetres*1.5:165;
    this.shadowMatrix=multiply(orthographic(extent,.1,dist*2),lookAt(this.sun.map(x=>x*dist),[0,0,0]));
    this.stats.geometryBytes=0;this.stats.uploadMs=0;this.stats.buildMs=0;this.shadowMs=0;this.stats.submitted=0;this.stats.draws=0;this.stats.triangles=0;this.stats.vertices=0;this.progress=0;this.plannedTriangles=triangles;
    return new Promise((resolve,reject)=>{
      this.buildReject=reject;const worker=new Worker(new URL(city?'./city-worker.js?v=nuray-cloud-1':'./worker.js',import.meta.url),{type:'module'});this.worker=worker;
      const abort=error=>{
        worker.terminate();this.worker=null;this.buildReject=null;this.loading=false;this.ready=false;
        for(const c of this.chunks){c.vertex?.destroy();c.index?.destroy();}this.chunks=[];this.tracer.release();
        this.stats.geometryBytes=0;this.stats.bvhBytes=0;this.stats.triangles=0;this.stats.vertices=0;this.publish(true);reject(error);
      };
      worker.onerror=e=>abort(new Error(e.message));
      worker.onmessage=({data})=>{
        if(this.worker!==worker)return;
        try{
        if(data.type==='plan'){this.plannedTriangles=data.triangles;this.plannedGroups=data.groups;this.plannedBytes=data.bytes;this.stats.expanded=data.expanded??data.triangles;if(data.transforms)this.setInstances(data.transforms);this.publish(true);}
        if(data.type==='progress'){this.progress=data.completed/this.plannedGroups*.8;this.phase='Строим BVH';this.publish(true);}
        if(data.type==='trace-plan'){this.tracer.allocate(data);this.phase='Загружаем на GPU';}
        if(data.type==='trace-chunk'){
          const start=performance.now();this.tracer.upload(data);
          this.chunks.push({bounds:data.bounds,triangles:data.triangles,id:data.id,instanceCount:data.instanceCount??1});
          this.stats.triangles+=data.triangles;this.stats.vertices+=data.vertexCount;
          this.stats.geometryBytes+=data.vertices.byteLength+data.indices.byteLength;this.stats.uploadMs+=performance.now()-start;
          this.progress=.8+.2*data.completed/this.plannedGroups;this.publish(true);worker.postMessage({type:'ack'});
        }
        if(data.type==='chunk'){
          try{
            const start=performance.now();
            const vertex=this.device.createBuffer({label:`House ${data.id} vertices`,size:data.vertices.byteLength,usage:GPUBufferUsage.VERTEX,mappedAtCreation:true});
            new Uint8Array(vertex.getMappedRange()).set(new Uint8Array(data.vertices));vertex.unmap();
            const index=this.device.createBuffer({label:`House ${data.id} indices`,size:data.indices.byteLength,usage:GPUBufferUsage.INDEX,mappedAtCreation:true});
            new Uint8Array(index.getMappedRange()).set(new Uint8Array(data.indices));index.unmap();
            this.chunks.push({vertex,index,bounds:data.renderBounds??data.bounds,triangles:data.triangles,id:data.id,instanceFirst:data.instanceFirst??0,instanceCount:data.instanceCount??1});
            this.stats.triangles+=data.triangles;this.stats.vertices+=data.vertexCount;
            this.stats.geometryBytes+=data.vertices.byteLength+data.indices.byteLength;this.stats.uploadMs+=performance.now()-start;
            this.progress=data.completed/this.plannedGroups;this.publish(true);worker.postMessage({type:'ack'});
          }catch(error){abort(error);}
        }
        if(data.type==='done'){
          worker.terminate();this.worker=null;this.buildReject=null;this.loading=false;this.ready=true;this.shadowDirty=true;
          if(this.state.engine!=='raster')this.tracer.bind();
          this.stats.buildMs=data.elapsed;this.lastTime=0;this.publish(true);resolve();
        }
        if(data.type==='error')abort(new Error(data.message));
        }catch(error){abort(error);}
      };
      this.phase=city?'Читаем Москва-Сити':'Собираем геометрию';worker.postMessage({type:'build',triangles,trace:this.state.engine!=='raster',limit:this.pageLimit,scene:city?this.city:undefined});
    });
  }
  cancelBuild(){
    if(!this.worker)return;
    this.worker.terminate();this.worker=null;this.buildReject?.(new Error('Сборка отменена.'));this.buildReject=null;this.loading=false;this.ready=false;
    for(const c of this.chunks){c.vertex?.destroy();c.index?.destroy();}this.chunks=[];this.tracer.release();this.stats.bvhBytes=0;
    this.stats.geometryBytes=0;this.stats.triangles=0;this.stats.vertices=0;this.stats.submitted=0;this.stats.draws=0;this.publish(true);
  }
  matrices(){
    const c=this.camera;const eye=[Math.sin(c.yaw)*Math.cos(c.pitch)*c.distance+c.target[0],Math.sin(c.pitch)*c.distance+c.target[1],Math.cos(c.yaw)*Math.cos(c.pitch)*c.distance+c.target[2]];
    const aspect=this.canvas.width/this.canvas.height;const fov=2*Math.atan(Math.tan(44*Math.PI/360)*Math.max(1,1.1/aspect));
    const matrix=multiply(perspective(fov,aspect,this.sceneName==='moscow'?1:.3,this.sceneName==='moscow'?this.city.extentMetres*6:550,true),lookAt(eye,c.target));
    const data=new Float32Array(48);data.set(matrix);data.set(this.shadowMatrix,16);data.set([...eye,0],32);data.set([...this.sun,0],36);
    data.set([this.state.materials,this.state.textures?1:0,this.state.shadows?1:0,0],40);data.set([this.state.exposure,this.sceneName==='moscow'?0:.00055,0,0],44);
    this.device.queue.writeBuffer(this.uniform,0,data);return matrix;
  }
  frame(time){
    if(!this.running)return;this.raf=requestAnimationFrame(t=>this.frame(t));
    if(document.hidden){this.lastTime=0;this.cancelMeasurement('Вкладка скрыта; повторите замер в активной вкладке.');return;}
    if(this.pixelRatio!==devicePixelRatio)this.resize();
    if(!this.ready||this.changing||this.inFlight>=2)return;
    if(this.state.engine!=='raster'){this.tracer.frame(time);return;}
    const dt=this.lastTime?time-this.lastTime:16.7;this.lastTime=time;this.frameMs=this.frameMs*.92+dt*.08;
    const matrix=this.matrices();const chunks=this.state.culling?this.chunks.filter(c=>(this.sceneName!=='moscow'&&c.id===48)||visible(c.bounds,matrix)):this.chunks;
    this.stats.submitted=chunks.reduce((n,c)=>n+c.triangles*c.instanceCount,0);this.stats.draws=chunks.length;
    const encoder=this.device.createCommandEncoder();const slot=this.timer.begin({revision:this.revision,dt,submitted:this.stats.submitted});
    if(this.shadowDirty&&this.state.shadows){
      const pass=encoder.beginRenderPass({...this.timer.pass(slot,'shadow'),colorAttachments:[],depthStencilAttachment:{view:this.shadowTexture.createView(),depthLoadOp:'clear',depthStoreOp:'store',depthClearValue:1}});
      pass.setPipeline(this.shadowPipeline);pass.setBindGroup(0,this.shadowGroup);
      for(const c of this.chunks){pass.setVertexBuffer(0,c.vertex);pass.setIndexBuffer(c.index,'uint32');pass.drawIndexed(c.triangles*3,c.instanceCount,0,0,c.instanceFirst);}pass.end();this.shadowDirty=false;
    }
    const pass=encoder.beginRenderPass({...this.timer.pass(slot,'geometry'),colorAttachments:[{view:this.context.getCurrentTexture().createView(),clearValue:{r:.70,g:.735,b:.745,a:1},loadOp:'clear',storeOp:'store'}],depthStencilAttachment:{view:this.depth.createView(),depthClearValue:0,depthLoadOp:'clear',depthStoreOp:'store'}});
    pass.setPipeline(this.pipeline);pass.setBindGroup(0,this.mainGroup);
    for(const c of chunks){pass.setVertexBuffer(0,c.vertex);pass.setIndexBuffer(c.index,'uint32');pass.drawIndexed(c.triangles*3,c.instanceCount,0,0,c.instanceFirst);}pass.end();
    this.timer.resolve(encoder,slot);this.device.queue.submit([encoder.finish()]);this.inFlight++;
    this.timer.read(slot);
    this.device.queue.onSubmittedWorkDone().then(()=>{this.inFlight--;if(!this.timer.enabled)this.collect(null,{revision:this.revision,dt});}).catch(e=>{if(this.running)this.fail(e.message);});
    this.publish();
  }
  timing(times,meta){if(meta.revision!==this.revision)return;if(meta.trace){this.gpu=times.total;this.tracer.recordTiming(times,meta);return;}this.gpu=times.geometry??null;if(times.shadow)this.shadowMs=times.shadow;this.collect(times.geometry,meta);}
  collect(gpu,meta){
    const m=this.measurement;if(!m||m.revision!==meta.revision)return;
    if(m.warm-->0)return;
    if(gpu!==null)m.gpu.push(gpu);m.frames.push(meta.dt);
    if(m.frames.length>=m.count){
      this.measurement=null;m.resolve({gpu:m.gpu.length?median(m.gpu):null,frame:median(m.frames),...this.stats,materials:this.state.materials,resolution:`${this.canvas.width} × ${this.canvas.height}`,shadowMs:this.shadowMs});
    }
  }
  measure(count=48){
    this.cancelMeasurement('Новый замер.');
    return new Promise((resolve,reject)=>{this.measurement={revision:this.revision,warm:8,count,gpu:[],frames:[],resolve,reject};});
  }
  cancelMeasurement(reason){if(this.measurement){this.measurement.reject(new Error(reason));this.measurement=null;}}
  publish(force=false){
    const now=performance.now();if(!force&&now-this.lastStatus<200)return;this.lastStatus=now;
    this.onStatus({...this.stats,gpu:this.gpu,shadowMs:this.shadowMs,frameMs:this.frameMs,timer:!!this.timer?.enabled,
      resolutionLimited:!!this.resolutionLimited,ready:this.ready,loading:this.loading,phase:this.phase,progress:this.progress??0,targetTriangles:this.plannedTriangles,width:this.canvas.width,height:this.canvas.height,materials:this.state.materials,engine:this.state.engine,samples:this.tracer.samples,sampleLimit:this.tracer.limit,cacheSamples:this.tracer.cache.samples,cacheLimit:this.tracer.cache.limit,cacheVersion:this.tracer.cache.version,cacheUpdates:this.tracer.cache.updates,cacheMs:this.tracer.cache.ms,cacheBytes:this.tracer.cache.bytes,reconstructionMs:this.tracer.reconstruction.ms,guideMs:this.tracer.reconstruction.guideMs,reconstructionBytes:this.tracer.reconstruction.bytes,reconstructionVersion:this.tracer.reconstruction.version,pathMs:this.tracer.pathMs,batch:this.tracer.batch,cacheSpan:this.tracer.cache.field?.size[0]});
  }
  resetCamera(){this.camera=this.sceneName==='moscow'?{yaw:.45,pitch:.95,distance:this.city.extentMetres*11/6,target:[0,20,0]}:cameraDefaults();}
  focus(id,material){
    if(this.sceneName==='moscow'){
      const views=[{yaw:.72,pitch:.28,distance:1100,target:[0,155,0]}, {yaw:1.5,pitch:.48,distance:1800,target:[100,55,380]}, {yaw:0,pitch:1.44,distance:this.city.extentMetres*1.4,target:[0,0,0]}];
      this.camera=views[id]??views[0];return;
    }
    const roof=['Медь','Сталь','Алюминий'].includes(material);
    const stone=material==='Камень',glass=material==='Стекло';
    this.camera={yaw:.52,pitch:roof?.65:stone?.30:glass?.22:.38,distance:roof?18:stone?12:16,
      target:[(id%6-2.5)*10.5,roof?6.4:stone?1.0:3.8,(Math.floor(id/6)-3.5)*11.5+(stone||glass?2.7:0)]};
  }
  fail(message){this.running=false;cancelAnimationFrame(this.raf);this.cancelBuild();this.cancelMeasurement(message);this.onError(message);}
  dispose(){this.running=false;cancelAnimationFrame(this.raf);this.cancelBuild();this.cancelMeasurement('Страница закрыта.');this.resizeObserver?.disconnect();this.timer?.dispose();this.device?.destroy();}
}
