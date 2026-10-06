import { GpuTimer } from './gpu-timer.js';
import { chooseBatch } from './sampling.js';
const MAX_SAMPLES = 2048;
const CACHE_SAMPLES = 256;
const LEVELS = [
  { dims: [12, 8, 12, 4], interval: [0, 0.65] },
  { dims: [6, 4, 6, 8], interval: [0.65, 1.95] },
  { dims: [3, 2, 3, 16], interval: [1.95, 5.85] },
  { dims: [2, 1, 2, 32], interval: [5.85, 24] },
];
const normalize = v => { const d = Math.hypot(...v); return v.map(x => x / d); };
const cross = (a,b) => [a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]];

export const defaults = () => ({mode:0, indirect:true, animate:false, lightX:0, lightY:3.85,
  power:18, ior:1.5, metal:0.18, stone:0.75, yaw:0, pitch:0.10, distance:9.3, batch:0});

export class Renderer {
  constructor(canvas, onStatus, onError, {autoStart=true,timestamps=true,cacheLimit=CACHE_SAMPLES,maxSamples=MAX_SAMPLES}={}) {
    this.canvas=canvas; this.onStatus=onStatus; this.onError=onError;this.state=defaults();
    this.samples=0;this.frameSeed=0;this.uniformData=new Float32Array(36);this.running=false;
    this.lastTime=0;this.averageMs=0;this.lastStatus=0;this.inFlight=0;this.generation=0;
    this.autoStart=autoStart;this.timestamps=timestamps;this.cacheLimit=cacheLimit;
    this.maxSamples=maxSamples;
    this.cacheSamples=0;this.cacheUpdates=0;this.cacheVersion=0;this.lightingKey='';
    this.batchSize=1;this.pathPerSample=0;this.cacheMs=0;this.displayMs=0;this.gpu=null;
  }
  async init() {
    if (!navigator.gpu) throw new Error('WebGPU недоступен в этом браузере. Откройте прототип в актуальном Chrome, Edge или Safari с поддержкой WebGPU.');
    const adapter=await navigator.gpu.requestAdapter({powerPreference:'high-performance'});
    if(!adapter)throw new Error('Не удалось получить WebGPU-адаптер. Проверьте поддержку WebGPU и аппаратное ускорение браузера.');
    const requiredFeatures=this.timestamps&&adapter.features.has('timestamp-query')?['timestamp-query']:[];
    this.device=await adapter.requestDevice({requiredFeatures});
    this.timer=new GpuTimer(this.device,(times,meta)=>this.recordTiming(times,meta),()=>{
      this.gpu=null;this.pathPerSample=0;this.publishStatus(performance.now(),true);
    });
    this.device.addEventListener('uncapturederror',e=>this.fail(e.error.message));
    this.device.lost.then(info=>{if(info.reason!=='destroyed')this.fail(`Соединение с GPU потеряно: ${info.message}`);});
    this.context=this.canvas.getContext('webgpu');
    this.format=navigator.gpu.getPreferredCanvasFormat();
    this.context.configure({device:this.device,format:this.format,alphaMode:'opaque'});
    this.uniform=this.device.createBuffer({label:'Frame uniforms',size:144,usage:GPUBufferUsage.UNIFORM|GPUBufferUsage.COPY_DST});
    this.irradiance=this.device.createBuffer({label:'Six irradiance lobes per probe',size:1152*6*16,usage:GPUBufferUsage.STORAGE|GPUBufferUsage.COPY_SRC});
    const files=['common','path','display','cascades','irradiance'];
    const source=Object.fromEntries(await Promise.all(files.map(async name=>{
      const r=await fetch(new URL(`${name}.wgsl`,import.meta.url),{cache:'no-store'});if(!r.ok)throw new Error(`Не найден шейдер ${name}`);return [name,await r.text()];
    })));
    const modules={};
    for(const name of ['path','display','cascades','irradiance']){
      const code=name==='display'?source[name]:source.common+'\n'+source[name];
      modules[name]=this.device.createShaderModule({label:name,code});
      const info=await modules[name].getCompilationInfo();
      const errors=info.messages.filter(m=>m.type==='error');
      if(errors.length)throw new Error(`${name}.wgsl\n`+errors.map(m=>`${m.lineNum}:${m.linePos} ${m.message}`).join('\n'));
    }
    this.pathPipeline=await this.device.createComputePipelineAsync({label:'Reference path tracer',layout:'auto',compute:{module:modules.path,entryPoint:'main'}});
    this.displayPipeline=await this.device.createRenderPipelineAsync({label:'Linear HDR to sRGB',layout:'auto',vertex:{module:modules.display,entryPoint:'vertex'},fragment:{module:modules.display,entryPoint:'fragment',targets:[{format:this.format}]},primitive:{topology:'triangle-list'}});
    this.cascadePipeline=await this.device.createComputePipelineAsync({label:'Radiance interval cascade',layout:'auto',compute:{module:modules.cascades,entryPoint:'main'}});
    this.irradiancePipeline=await this.device.createComputePipelineAsync({label:'Directional irradiance convolution',layout:'auto',compute:{module:modules.irradiance,entryPoint:'main'}});
    this.setupCascades();
    this.resizeObserver=new ResizeObserver(()=>this.resize());this.resizeObserver.observe(this.canvas);
    this.resize();this.running=true;if(this.autoStart)this.raf=requestAnimationFrame(t=>this.frame(t));
    return adapter.info?.description || adapter.info?.architecture || 'WebGPU';
  }
  group(pipeline, buffers){return this.device.createBindGroup({layout:pipeline.getBindGroupLayout(0),entries:buffers.map(([binding,buffer])=>({binding,resource:{buffer}}))});}
  setupCascades(){
    this.levelBuffers=LEVELS.map(l=>this.device.createBuffer({label:`Cascade ${l.dims[3]} directions/axis`,size:l.dims.reduce((a,b)=>a*b,1)*l.dims[3]*16,usage:GPUBufferUsage.STORAGE}));
    this.dummy=this.device.createBuffer({size:16,usage:GPUBufferUsage.STORAGE});
    this.levelGroups=LEVELS.map((l,i)=>{
      const data=new ArrayBuffer(48);const words=new Uint32Array(data);const floats=new Float32Array(data);
      words.set(l.dims,0);words.set(LEVELS[i+1]?.dims??[1,1,1,1],4);floats.set([...l.interval,i<3?1:0,0],8);
      const uniform=this.device.createBuffer({label:`Cascade ${i} parameters`,size:48,usage:GPUBufferUsage.UNIFORM,mappedAtCreation:true});new Uint8Array(uniform.getMappedRange()).set(new Uint8Array(data));uniform.unmap();
      return this.group(this.cascadePipeline,[[0,this.uniform],[1,uniform],[2,this.levelBuffers[i+1]??this.dummy],[3,this.levelBuffers[i]]]);
    });
    this.irradianceGroup=this.group(this.irradiancePipeline,[[1,this.levelBuffers[0]],[2,this.irradiance]]);
  }
  resize(){
    if(!this.device)return;
    const rect=this.canvas.getBoundingClientRect();
    // Bounded pixel budget keeps the same portable shader viable on integrated GPUs.
    const maxPixels=720000;const scale=Math.min(window.devicePixelRatio||1,Math.sqrt(maxPixels/Math.max(1,rect.width*rect.height)));
    const w=Math.max(1,Math.round(rect.width*scale)),h=Math.max(1,Math.round(rect.height*scale));
    if(this.canvas.width===w&&this.canvas.height===h&&this.accumulation)return;
    this.canvas.width=w;this.canvas.height=h;
    this.accumulation?.destroy();
    this.accumulation=this.device.createBuffer({label:'Progressive HDR accumulation',size:w*h*16,usage:GPUBufferUsage.STORAGE|GPUBufferUsage.COPY_SRC});
    this.pathGroup=this.group(this.pathPipeline,[[0,this.uniform],[1,this.accumulation],[2,this.irradiance]]);
    this.displayGroup=this.group(this.displayPipeline,[[0,this.uniform],[1,this.accumulation]]);
    this.pathPerSample=0;this.batchSize=1;
    this.resetAccumulation();
  }
  resetAccumulation(){
    if(this.samples>=this.maxSamples){this.lastTime=0;this.averageMs=0;}
    this.samples=0;this.generation++;
    this.gpu=null;
  }
  set(key,value){
    if(this.state[key]===value)return;
    this.state[key]=value;
    // Changing batch size preserves both the sample sequence and accumulated image.
    if(key!=='batch'){this.resetAccumulation();this.pathPerSample=0;this.batchSize=1;}
  }
  reset(){this.state=defaults();this.lightingKey='';this.pathPerSample=0;this.batchSize=1;this.resetAccumulation();}
  syncLighting(){
    const s=this.state;
    const key=[s.lightX,s.lightY,s.power,s.ior,s.metal,s.stone].join('|');
    if(key===this.lightingKey)return;
    this.lightingKey=key;this.cacheSamples=0;this.cacheVersion++;this.cacheMs=0;
  }
  writeUniforms(batch){
    const s=this.state;const target=[0,1.8,-0.25];
    const position=[Math.sin(s.yaw)*Math.cos(s.pitch)*s.distance+target[0],Math.sin(s.pitch)*s.distance+target[1],Math.cos(s.yaw)*Math.cos(s.pitch)*s.distance+target[2]];
    const forward=normalize(target.map((v,i)=>v-position[i]));const right=normalize(cross(forward,[0,1,0]));const up=cross(right,forward);
    const d=this.uniformData;
    d.set([this.canvas.width,this.canvas.height,this.samples,this.frameSeed],0);
    const aspect=this.canvas.width/this.canvas.height;
    const fovScale=Math.max(1,1.15/aspect);
    d.set([...position,0],4);d.set([...right,Math.tan(40*Math.PI/360)*fovScale],8);d.set([...up,0],12);d.set([...forward,0],16);
    d.set([s.lightX,s.lightY,-0.35,s.power],20);d.set([s.mode,s.indirect?1:0,s.metal,s.stone],24);d.set([s.ior,0.7,1.1,20],28);
    d.set([batch,this.cacheSamples,0,0],32);
    this.device.queue.writeBuffer(this.uniform,0,d);
  }
  frame(time){
    if(!this.running)return;
    this.raf=requestAnimationFrame(t=>this.frame(t));
    this.renderFrame(time);
  }
  renderFrame(time){
    if(!this.running)return false;
    if(document.hidden){this.lastTime=0;return;}
    // A bounded queue overlaps CPU/GPU work without building unbounded input latency.
    if(this.inFlight>=2)return false;
    if(this.state.animate){this.state.lightX=Math.sin(time*0.00055)*1.55;this.resetAccumulation();}
    this.syncLighting();
    const useCache=this.state.mode===1&&this.state.indirect;
    const updateCache=useCache&&this.cacheSamples<this.cacheLimit;
    // When the fixed cache is ready, discard images made with its provisional values.
    if(updateCache&&this.cacheSamples===this.cacheLimit-1)this.resetAccumulation();
    if(this.samples>=this.maxSamples&&!updateCache)return false;
    const dt=this.lastTime?time-this.lastTime:16.7;this.lastTime=time;
    this.averageMs=this.averageMs?this.averageMs*0.94+dt*0.06:dt;
    const batch=chooseBatch({requested:this.state.batch,remaining:this.maxSamples-this.samples,
      pathPerSample:this.pathPerSample,overhead:(updateCache?this.cacheMs:0)+this.displayMs,current:this.batchSize});
    this.batchSize=batch;
    this.writeUniforms(batch);const encoder=this.device.createCommandEncoder();
    const slot=this.timer.begin({generation:this.generation,batch,updateCache});
    if(updateCache){
      for(let i=3;i>=0;i--){const p=encoder.beginComputePass(this.timer.pass(slot,'cascade'));p.setPipeline(this.cascadePipeline);p.setBindGroup(0,this.levelGroups[i]);const d=LEVELS[i].dims;p.dispatchWorkgroups(Math.ceil(d[0]*d[1]*d[2]*d[3]*d[3]/64));p.end();}
      const p=encoder.beginComputePass(this.timer.pass(slot,'irradiance'));p.setPipeline(this.irradiancePipeline);p.setBindGroup(0,this.irradianceGroup);p.dispatchWorkgroups(Math.ceil(1152*6/64));p.end();
    }
    const p=encoder.beginComputePass(this.timer.pass(slot,'path'));p.setPipeline(this.pathPipeline);p.setBindGroup(0,this.pathGroup);p.dispatchWorkgroups(Math.ceil(this.canvas.width/8),Math.ceil(this.canvas.height/8));p.end();
    const display=encoder.beginRenderPass({...this.timer.pass(slot,'display'),colorAttachments:[{view:this.context.getCurrentTexture().createView(),loadOp:'clear',storeOp:'store',clearValue:{r:0.03,g:0.03,b:0.03,a:1}}]});display.setPipeline(this.displayPipeline);display.setBindGroup(0,this.displayGroup);display.draw(3);display.end();
    this.timer.resolve(encoder,slot);
    this.device.queue.submit([encoder.finish()]);this.samples+=batch;this.frameSeed+=batch;this.inFlight++;
    if(updateCache){this.cacheSamples++;this.cacheUpdates++;}
    this.lastTimingRead=this.timer.read(slot);
    this.device.queue.onSubmittedWorkDone().then(()=>{this.inFlight--;}).catch(e=>{if(this.running)this.fail(e.message);});
    this.publishStatus(time,this.samples===batch||this.samples===this.maxSamples);
    return true;
  }
  recordTiming(times,meta){
    if(meta.generation!==this.generation)return;
    this.gpu=times;
    const smooth=(previous,next)=>previous?previous*0.8+next*0.2:next;
    if(times.path>0&&meta.batch>0)this.pathPerSample=smooth(this.pathPerSample,times.path/meta.batch);
    if(meta.updateCache)this.cacheMs=smooth(this.cacheMs,times.cascade+times.irradiance);
    this.displayMs=smooth(this.displayMs,times.display);
    this.publishStatus(performance.now(),this.samples>=this.maxSamples);
  }
  publishStatus(time,force=false){
    if(!force&&time-this.lastStatus<220)return;
    this.onStatus({samples:this.samples,ms:this.averageMs,width:this.canvas.width,height:this.canvas.height,state:this.state,
      gpu:this.gpu,timerAvailable:this.timer.enabled,batch:this.batchSize,cacheSamples:this.cacheSamples,cacheLimit:this.cacheLimit,
      cacheVersion:this.cacheVersion,cacheUpdates:this.cacheUpdates});this.lastStatus=time;
  }
  fail(message){if(!this.running&&this.failed)return;this.failed=true;this.running=false;cancelAnimationFrame(this.raf);this.onError(message);}
  dispose(){this.running=false;cancelAnimationFrame(this.raf);this.resizeObserver?.disconnect();this.timer?.dispose();this.device?.destroy();}
}
