import {TRACE_ENVIRONMENT,traceEnvironmentGroup} from './trace-environment.js?v=shore-water-1';
import {chooseBatch} from '../sampling.js?v=moscow-defaults-1';
import {MeshCascadeCache} from './cascade-cache.js?v=shore-water-1';
import {MeshReconstruction} from './reconstruction.js?v=shore-water-1';
import {normalize} from './math.js?v=moscow-defaults-1';
const cross=(a,b)=>[a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]];
export class MeshTracer {
  constructor(owner){this.owner=owner;this.pages=[];this.samples=0;this.seed=0;this.key='';this.limit=5000;this.cache=new MeshCascadeCache(this);this.reconstruction=new MeshReconstruction(this);this.batch=1;this.pathMs=0;this.displayMs=0;}
  async init(){
    const d=this.owner.device;
    const read=async path=>{const r=await fetch(new URL(path,import.meta.url),{cache:'no-store'});if(!r.ok)throw new Error(`Не найден ${path}`);return r.text();};
    let [common,mesh,path,display,cascades,irradiance,guide,temporal,denoise]=await Promise.all(['../common.wgsl','./trace.wgsl','./path.wgsl','../display.wgsl','./cascades.wgsl','./irradiance.wgsl','./guides.wgsl','./temporal.wgsl','./denoise.wgsl'].map(read));
    const [waterTransport,transport]=await Promise.all(['./water-transport.wgsl','./transport.wgsl'].map(read));
    if(this.owner.ocean){
      mesh=mesh.replace('fn traceSunCos()->f32 {return .9998;}','').replace(/fn meshSky\([\s\S]*?\n}/,'fn meshSky(rd:vec3f)->vec3f {return cityTraceSky(rd);}')
        .replace('// CITY_WATER_HOOK','if u32(m.physical.z)==12u {return traceWater(Surface(color,rough,0,1.333,12u,normal,0),p,travel);}')
        .replace('fn cityHasWater()->bool {return false;}','fn cityHasWater()->bool {return true;}')
        .replace('fn waterAbsorption()->vec3f {return vec3f(0);}','fn waterAbsorption()->vec3f {return F.viewProj[3].xyz;}')
        .replace('fn waterScatteringRate()->f32 {return 0;}','fn waterScatteringRate()->f32 {return max(0.0,F.viewProj[1].z)*.12;}')
        .replace('fn waterScatteringTint()->vec3f {return vec3f(1);}','fn waterScatteringTint()->vec3f {return F.sssCol.rgb;}')
        .replace('fn waterIndex()->f32 {return 1.333;}','fn waterIndex()->f32 {return waterIOR();}')+'\n'+TRACE_ENVIRONMENT;
    }
    mesh+='\n'+waterTransport;
    if(this.owner.ocean)display=display.replace('return vec4f(srgb(toneMap(accumulation[i].rgb*u.glass.z)),1);',`let light=accumulation[i].rgb;
      let classic=srgb(toneMap(light*u.glass.z));
      let sea=clamp(pow(max(vec3f(0),light*u.camera.w),vec3f(.65)),vec3f(0),vec3f(1));
      let t=select(select(0.0,1.0,u.up.w>1.5&&u.up.w<2.5),u.forward.w,u.up.w>2.5&&u.up.w<3.5);
      return vec4f(mix(classic,sea,t),1);`);
    const modules=[d.createShaderModule({label:'Mesh transport: refractive water + BVH',code:common+'\n'+mesh+'\n'+transport+'\n'+path}),d.createShaderModule({code:display})];
    for(const m of modules){const errors=(await m.getCompilationInfo()).messages.filter(e=>e.type==='error');if(errors.length)throw new Error(errors.map(e=>`${e.lineNum}: ${e.message}`).join('\n'));}
    this.pipeline=await d.createComputePipelineAsync({layout:'auto',compute:{module:modules[0],entryPoint:'meshMain'}});
    this.display=await d.createRenderPipelineAsync({layout:'auto',vertex:{module:modules[1],entryPoint:'vertex'},fragment:{module:modules[1],entryPoint:'fragment',targets:[{format:this.owner.format}]},primitive:{topology:'triangle-list'}});
    this.uniform=d.createBuffer({size:144,usage:GPUBufferUsage.UNIFORM|GPUBufferUsage.COPY_DST});
    await this.cache.init(common,mesh,transport+'\n'+cascades,irradiance);
    await this.reconstruction.init(common,mesh,guide,temporal,denoise);
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
    this.reconstruction.release();
    this.accumulation=d.createBuffer({size:o.canvas.width*o.canvas.height*32,usage:GPUBufferUsage.STORAGE|GPUBufferUsage.COPY_SRC});
    this.displayGroup=d.createBindGroup({layout:this.display.getBindGroupLayout(0),entries:[{binding:0,resource:{buffer:this.uniform}},{binding:1,resource:{buffer:this.accumulation}}]});
    this.bind();this.reset();
  }
  geometryEntries(){
    const o=this.owner;return [
      ...[this.uniform,this.accumulation,o.materialBuffer,this.scene,...Array.from({length:4},(_,i)=>this.pages[i]??this.dummy)].map((buffer,binding)=>({binding,resource:{buffer}})),
      {binding:8,resource:o.textures[0].createView({dimension:'2d-array'})},{binding:9,resource:o.textures[2].createView({dimension:'2d-array'})},{binding:10,resource:o.sampler},
    ];
  }
  bind(){
    if(!this.scene||!this.accumulation)return;const o=this.owner;
    this.group=o.device.createBindGroup({layout:this.pipeline.getBindGroupLayout(0),entries:this.geometryEntries()});
    if(o.ocean)this.environment=traceEnvironmentGroup(o,this.pipeline);
    this.cache.bind();this.reconstruction.bind();this.reset();
  }
  recordTiming(times,meta){
    const smooth=(a,b)=>a?a*.8+b*.2:b;
    this.pathMs=smooth(this.pathMs,times.path/meta.batch);this.displayMs=smooth(this.displayMs,times.display);
    if(meta.updateCache)this.cache.ms=smooth(this.cache.ms,times.cascade+times.irradiance);
    if(meta.reconstruction)this.reconstruction.ms=smooth(this.reconstruction.ms,times.reconstruct??0);
    if(times.guides!==undefined)this.reconstruction.guideMs=smooth(this.reconstruction.guideMs,times.guides);
  }
  reset({history=true}={}){this.samples=0;this.key='';this.owner.gpu=null;this.owner.revision++;this.pathMs=0;this.batch=1;if(history)this.reconstruction.invalidate();}
  release(){this.reconstruction.release();this.cache.invalidate();this.cache.field=null;this.pages.forEach(p=>p.destroy());this.pages=[];this.scene?.destroy();this.scene=null;this.group=null;this.reset();}
  frame(time){
    const o=this.owner;if(o.inFlight>=1||!this.group)return;
    const c=o.camera,s=o.state;
    const waterDt=o.ocean?o.waterClock.tick(time,o.waterSettings.animated):0;
    const movingWater=!!o.ocean&&o.waterSettings.animated;
    const stateKey=JSON.stringify([s.materials,s.textures,s.indirect,s.bounces,s.ior,s.engine,s.reconstruction,o.sun,o.sunPower,o.waterSettings]);
    const key=JSON.stringify([c,stateKey,s.exposure]);
    if(key!==this.key){this.reset({history:stateKey!==this.stateKey});this.key=key;this.stateKey=stateKey;o.lastTime=0;}
    // Each moving-water frame is fresh, but retain timing/camera keys so
    // animation does not masquerade as a camera cut on every frame.
    if(movingWater){this.samples=0;this.reconstruction.invalidate();this.cache.invalidate();}
    if(!s.reconstruction&&this.reconstruction.guides)this.reconstruction.release();
    const useCache=s.engine==='cascade'&&s.indirect&&!movingWater;
    if(useCache&&this.cache.sync())this.reset();
    const updateCache=useCache&&this.cache.samples<this.cache.limit;
    if(updateCache&&this.cache.samples===this.cache.limit-1)this.reset();
    if(updateCache)this.reconstruction.invalidate();
    // reset() clears the camera key; commit it after cache invalidation as well.
    this.key=key;
    if(this.samples>=this.limit&&!updateCache){o.publish();return;}
    this.batch=chooseBatch({remaining:this.limit-this.samples,pathPerSample:this.pathMs,overhead:(updateCache?this.cache.ms??0:0)+this.displayMs+(s.reconstruction?this.reconstruction.ms:0),current:this.batch});
    if(movingWater)this.batch=1;
    const eye=[Math.sin(c.yaw)*Math.cos(c.pitch)*c.distance+c.target[0],Math.sin(c.pitch)*c.distance+c.target[1],Math.cos(c.yaw)*Math.cos(c.pitch)*c.distance+c.target[2]];
    o.eye=eye;
    const forward=normalize(c.target.map((n,i)=>n-eye[i])),right=normalize(cross(forward,[0,1,0])),up=cross(right,forward);
    const data=new Float32Array(36),w=o.canvas.width,h=o.canvas.height;
    data.set([w,h,this.samples,this.seed],0);data.set([...eye,o.waterSettings.seaExposure],4);data.set([...right,Math.tan(44*Math.PI/360)*Math.max(1,1.1/(w/h))],8);
    data.set([...up,o.ocean?({ocean:0,classic:1,seascape:2,blend:3,hosek:4}[o.waterSettings.lighting]):1],12);data.set([...forward,o.waterSettings.lightingMix/100],16);data.set([...o.sun,o.sunPower??1],20);
    data.set([s.materials,s.indirect?1:0,s.textures?1:0,useCache?1:0],24);data.set([s.ior,1,o.ocean?(o.waterSettings.lighting==='hosek'?o.waterSettings.hwExposure:o.waterSettings.lighting==='ocean'?o.waterSettings.exposure:s.exposure):s.exposure,s.bounces],28);data.set([this.batch,this.cache.samples,s.reconstruction?1:0,0],32);
    o.device.queue.writeBuffer(this.uniform,0,data);
    const dt=o.lastTime?time-o.lastTime:16.7;o.lastTime=time;o.frameMs=o.frameMs*.9+dt*.1;
    const encoder=o.device.createCommandEncoder(),slot=o.timer.begin({revision:o.revision,dt,trace:true,batch:this.batch,updateCache,reconstruction:!!s.reconstruction});
    o.ocean?.prepare(encoder,slot,waterDt);
    if(updateCache)this.cache.encode(encoder,slot);
    const pass=encoder.beginComputePass(o.timer.pass(slot,'path'));pass.setPipeline(this.pipeline);pass.setBindGroup(0,this.group);pass.setBindGroup(1,this.cache.pathGroup);if(this.environment)pass.setBindGroup(2,this.environment);pass.dispatchWorkgroups(Math.ceil(w/8),Math.ceil(h/8));pass.end();
    if(s.reconstruction)this.reconstruction.encode(encoder,slot,data);
    const show=encoder.beginRenderPass({...o.timer.pass(slot,'display'),colorAttachments:[{view:o.context.getCurrentTexture().createView(),loadOp:'clear',storeOp:'store'}]});
    show.setPipeline(this.display);show.setBindGroup(0,s.reconstruction?this.reconstruction.displayGroup:this.displayGroup);show.draw(3);show.end();o.timer.resolve(encoder,slot);
    o.device.queue.submit([encoder.finish()]);this.samples+=this.batch;this.seed+=this.batch;o.inFlight++;
    if(updateCache){this.cache.samples++;this.cache.updates++;}
    o.timer.read(slot);o.device.queue.onSubmittedWorkDone().then(()=>{o.inFlight--;o.publish(true);}).catch(e=>o.fail(e.message));
    o.stats.submitted=o.stats.expanded??o.stats.triangles;o.stats.draws=0;o.publish();
  }
}
