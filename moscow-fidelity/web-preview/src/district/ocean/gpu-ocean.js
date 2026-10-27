import {HosekCache} from '../hosek/model.js?v=moscow-defaults-1';
import {hosekWGSL} from '../hosek/shaders.js?v=moscow-defaults-1';
import {SEASCAPE_SKY_WGSL} from '../seascape/seascape-wgsl.js?v=shore-water-1';
import * as SIM from './vendor/sim.js?v=moscow-defaults-1';
import * as SKY from './vendor/sky.js?v=moscow-defaults-1';
import {SKY_BG} from './vendor/ocean.js?v=moscow-defaults-1';
import {BLOOM_DOWN,BLOOM_UP,COMPOSITE} from './vendor/post.js?v=moscow-defaults-1';
import {normalize,cross} from '../math.js?v=moscow-defaults-1';
import {absorptionCoefficients,linearColor} from './optics.js?v=shore-water-1';
// Classic city fragments already contain the original ACES/sRGB result.
// Copy them after contact AO without applying the Ocean grade a second time.
const LIGHTING_COMPOSITE=COMPOSITE.replace('var c = textureLoad(hdr, pc, 0).rgb;',
 'var c = textureLoad(hdr, pc, 0).rgb; if (U.q.w > .5) {return vec4f(c,1.0);}');
const CITY_SKY=SKY_BG.replace('let pixAng =', 'if(F.windP[1].y>3.5){return vec4f(hwGrade(hwSky(dir,F.sunDir.xyz)+hwDisc(dir,F.sunDir.xyz,2.0*length(F.camUp.xyz)/F.screen.y)*F.viewProj[1].w),1); } if (F.windP[1].y > 1.5) {let t=select(1.0,F.viewProj[1].y,F.windP[1].y>2.5);return vec4f(mix(vec3f(.70,.735,.745),seaGrade(seaSky(dir,F.sunDir.xyz),F.viewProj[1].x),t),1.0);}\n  let pixAng =')+SEASCAPE_SKY_WGSL+hosekWGSL(0,4);
const L=[1103,211.3,39.7,7.43,1.393,.2617],C=6,N=256,FM=11,FR=1024,DEG=Math.PI/180;
const level=(t,m,dimension='2d-array')=>t.createView({dimension,baseMipLevel:m,mipLevelCount:1});
const array=t=>t.createView({dimension:'2d-array'});
export class GpuOcean {
 constructor(owner){this.owner=owner;this.d=owner.device;this.resources=[];this.foamCur=0;this.foamFirst=true;this.foamSnap=new Int32Array(4);this.frameIndex=0;this.updates=0;}
 buffer(size,usage,label){const b=this.d.createBuffer({size,usage,label});this.resources.push(b);return b;}
 texture(size,format,mips=1,render=false){const t=this.d.createTexture({size,format,mipLevelCount:mips,usage:GPUTextureUsage.TEXTURE_BINDING|(render?GPUTextureUsage.RENDER_ATTACHMENT:GPUTextureUsage.STORAGE_BINDING)});this.resources.push(t);return t;}
 async shader(code,label){const m=this.d.createShaderModule({code,label});const errors=(await m.getCompilationInfo()).messages.filter(x=>x.type==='error');if(errors.length)throw Error(label+': '+errors.map(x=>x.lineNum+': '+x.message).join('\n'));return m;}
 async compute(code,label){const module=await this.shader(code,label);return this.d.createComputePipelineAsync({label,layout:'auto',compute:{module,entryPoint:'main'}});}
 group(pipe,resources,index=0){return this.d.createBindGroup({layout:pipe.getBindGroupLayout(index),entries:resources.map((resource,binding)=>({binding,resource}))});}
 async render(code,label,format='rgba16float',extra={}){const module=await this.shader(code,label);return this.d.createRenderPipelineAsync({label,layout:'auto',vertex:{module,entryPoint:'vs'},fragment:{module,entryPoint:'fs',targets:[{format,...extra.target}]},...extra.pipeline});}
 async init(){
  const U=GPUBufferUsage,uniform=n=>this.buffer(n,U.UNIFORM|U.COPY_DST,'ocean uniform'),storage=n=>this.buffer(n,U.STORAGE,'ocean spectrum');
  this.sim=uniform(224);this.frame=uniform(384);this.hosek=uniform(448);this.hosekCache=new HosekCache();this.atmo=uniform(16);this.foam=uniform(144);this.sunVis=storage(16);
  const names=['SIM_INIT','SIM_EVOLVE','FFT_ROWS','FFT_COLS','SIM_MIPS','FOAM_TEX','RGBA8_MIPS','FOAM_UPDATE','ARRAY16_MIPS','TRANS_LUT','MS_LUT','SKYVIEW_LUT','ENV_CUBE','CUBE_MIPS','SUN_VIS'];
  const pipes=await Promise.all(names.map(n=>this.compute(SIM[n]??SKY[n],n)));this.p=Object.fromEntries(names.map((n,i)=>[n,pipes[i]]));
  const [h0,a,b,ta,tb]=Array.from({length:5},()=>storage(N*N*C*16));
  [this.disp,this.deriv,this.mom]=Array.from({length:3},()=>this.texture([N,N,C],'rgba16float',9));
  const buf=buffer=>({buffer}),g=(n,r)=>this.group(this.p[n],r);
  this.initG=g('SIM_INIT',[buf(this.sim),buf(h0)]);this.evolveG=g('SIM_EVOLVE',[buf(this.sim),buf(h0),buf(a),buf(b)]);this.rowsG=g('FFT_ROWS',[buf(a),buf(b),buf(ta),buf(tb)]);this.colsG=g('FFT_COLS',[buf(ta),buf(tb),level(this.disp,0),level(this.deriv,0),level(this.mom,0)]);
  this.simMips=Array.from({length:8},(_,i)=>g('SIM_MIPS',[...[this.disp,this.deriv,this.mom].map(t=>level(t,i)),...[this.disp,this.deriv,this.mom].map(t=>level(t,i+1))]));
  this.repeat=this.d.createSampler({magFilter:'linear',minFilter:'linear',mipmapFilter:'linear',addressModeU:'repeat',addressModeV:'repeat',maxAnisotropy:4});this.clamp=this.d.createSampler({magFilter:'linear',minFilter:'linear',mipmapFilter:'linear'});
  this.foamTex=this.texture([512,512],'rgba8unorm',10);this.foamWorld=[0,1].map(()=>this.texture([FR,FR,2],'rgba16float',FM));
  this.foamG=[0,1].map(i=>g('FOAM_UPDATE',[buf(this.foam),level(this.foamWorld[1-i],0),level(this.foamWorld[i],0),array(this.disp),array(this.deriv),this.repeat,this.repeat]));
  this.foamMips=[0,1].map(i=>Array.from({length:FM-1},(_,m)=>g('ARRAY16_MIPS',[level(this.foamWorld[i],m),level(this.foamWorld[i],m+1)])));
  const enc=this.d.createCommandEncoder(),cp=enc.beginComputePass();this.dispatch(cp,'FOAM_TEX',g('FOAM_TEX',[level(this.foamTex,0,'2d')]),64,64);
  for(let m=1;m<10;m++)this.dispatch(cp,'RGBA8_MIPS',g('RGBA8_MIPS',[level(this.foamTex,m-1,'2d'),level(this.foamTex,m,'2d')]),Math.ceil((512>>m)/8),Math.ceil((512>>m)/8));cp.end();this.d.queue.submit([enc.finish()]);
  this.trans=this.texture([256,64],'rgba16float');this.ms=this.texture([32,32],'rgba16float');this.sky=this.texture([256,144],'rgba16float');this.env=this.texture([256,256,6],'rgba16float',9);
  this.transG=g('TRANS_LUT',[buf(this.atmo),this.trans.createView()]);this.msG=g('MS_LUT',[buf(this.atmo),this.trans.createView(),this.clamp,this.ms.createView()]);
  this.skyG=g('SKYVIEW_LUT',[buf(this.frame),this.trans.createView(),this.ms.createView(),this.clamp,this.sky.createView()]);
  this.envG=g('ENV_CUBE',[buf(this.frame),this.trans.createView(),this.sky.createView(),this.clamp,level(this.env,0)]);
  this.sunG=g('SUN_VIS',[buf(this.frame),this.trans.createView(),this.sky.createView(),this.clamp,buf(this.sunVis)]);
  this.envMips=Array.from({length:8},(_,m)=>g('CUBE_MIPS',[level(this.env,m),level(this.env,m+1)]));
  [this.skyPipe,this.downPipe,this.upPipe,this.composite]=await Promise.all([
   this.render(CITY_SKY,'Selectable atmosphere','rgba16float',{pipeline:{depthStencil:{format:'depth32float',depthWriteEnabled:false,depthCompare:'equal'}}}),
   this.render(BLOOM_DOWN,'Ocean bloom down'),this.render(BLOOM_UP,'Ocean bloom up','rgba16float',{target:{blend:{color:{srcFactor:'one',dstFactor:'one'},alpha:{srcFactor:'one',dstFactor:'one'}}}}),this.render(LIGHTING_COMPOSITE,'City lighting composite',this.owner.format)
  ]);
  this.backgroundG=this.group(this.skyPipe,[buf(this.frame),this.trans.createView(),this.sky.createView(),this.clamp,buf(this.hosek)]);
  this.compositeU=uniform(32);this.bloomU=Array.from({length:16},()=>uniform(16));
  this.owner.stats.oceanBytes=5*N*N*C*16+3*N*N*C*8*4/3+2*FR*FR*2*8*4/3+256*256*6*8*4/3+512*512*4*4/3+256*144*8+256*64*8+32*32*8;
 }
 bindCity(pipe){this.cityGroups=[0,1].map(i=>this.group(pipe,[{buffer:this.frame},this.trans.createView(),this.sky.createView(),this.clamp,array(this.disp),array(this.deriv),array(this.mom),this.foamTex.createView(),this.env.createView({dimension:'cube'}),this.repeat,array(this.foamWorld[i]),{buffer:this.sunVis},{buffer:this.hosek}],1));}
 dispatch(cp,name,group,x,y=1,z=1){cp.setPipeline(this.p[name]);cp.setBindGroup(0,group);cp.dispatchWorkgroups(x,y,z);}
 prepare(encoder,slot,dt){
  const o=this.owner,P=o.waterSettings,t=o.waterClock.time,eye=o.eye;this.frameIndex++;
  if(P.lighting==='hosek')this.d.queue.writeBuffer(this.hosek,0,this.hosekCache.update(o.sun,P));
  const frame=new Float32Array(96),aspect=o.canvas.width/o.canvas.height,tanY=Math.tan(44*Math.PI/360)*Math.max(1,1.1/aspect),fwd=normalize(o.camera.target.map((x,i)=>x-eye[i])),right=normalize(cross(fwd,[0,1,0])),up=cross(right,fwd);
  frame.set([P.seaHeight,P.seaFrequency,P.seaChoppy,P.seaSpeed,P.seaExposure,P.lightingMix/100,P.turbidity,P.sunIntensity/100,P.shadowStrength/100],0);frame.set([...eye,t],16);frame.set(right.map(x=>x*tanY*aspect),20);frame.set(up.map(x=>x*tanY),24);frame.set(fwd,28);frame.set([...o.sun,14],32);frame.set([o.canvas.width,o.canvas.height,1/o.canvas.width,1/o.canvas.height],36);
  frame.set([...absorptionCoefficients(P),P.waterIOR],12);
  frame.set(L,40);frame.set(L.map(x=>1/x),48);frame.set([Math.cos(P.windDir*DEG),Math.sin(P.windDir*DEG),P.windSpeed,0],56);frame[60]=P.shoreFoam;frame[61]=P.lighting==='classic'?1:P.lighting==='seascape'?2:P.lighting==='blend'?3:P.lighting==='hosek'?4:0;frame[62]=P.waterModel==='seascape'?1:0;
  frame.set([16,32,128,1024],64);frame.set([P.exposure,P.bloom,this.frameIndex,0],68);frame.set([P.haze,Math.max(eye[1],10)*.001,P.veil,.9],72);
  frame.set([.016*P.turbidity,.08*P.turbidity,.096*P.turbidity,.0024],76);frame.set([...linearColor(P.scatteringColor),2.6],80);frame.set([.36+.12*P.foam,2.5,P.foam,1],84);
  frame.set([(5.802e-3+4.4e-3*P.haze)*1e-3,(13.558e-3+4.4e-3*P.haze)*1e-3,(33.1e-3+4.4e-3*P.haze)*1e-3,1.1e-4],88);frame.set([1.5,P.clouds,2.2,t],92);this.d.queue.writeBuffer(this.frame,0,frame);
  const sk=JSON.stringify([P.windSpeed,P.windDir,P.fetchKm,P.swellHs,P.swellLength,P.swellDir,P.swellSpread,P.choppy]),spec=sk!==this.specKey;
  const envKey=JSON.stringify([o.sun,Math.round(eye[1]*10),P.haze,P.clouds,P.veil,P.turbidity]);const envChanged=envKey!==this.envKey;const env=P.lighting==='ocean'&&(envChanged||t!==this.envTime);
  const spectral=P.waterModel==='ocean',changedModel=this.lastWaterModel!==P.waterModel;this.lastWaterModel=P.waterModel;if(spectral&&changedModel)this.foamFirst=true;
  const camKey=eye.map((x,i)=>i===1?0:Math.floor(x*8)).join(',');const foam=spectral&&(dt>0||spec||changedModel||camKey!==this.foamCamKey||P.foam!==this.prevFoam);
  const waves=spectral&&(dt>0||spec||changedModel||t!==this.simTime);if(waves||env||foam){
   const cp=encoder.beginComputePass({...o.timer.pass(slot,'oceanSimulation')});
   if(waves){const s=new Float32Array(56);for(let c=0;c<C;c++){s[c]=L[c];s[8+c]=c===0?Math.PI/L[c]:2*Math.PI*6/L[c];s[16+c]=c<C-1?2*Math.PI*6/L[c+1]:Math.PI*N/L[c]*.98;}for(let c=1;c<C;c++)s[8+c]=s[16+c-1];
    s.set([P.windSpeed,P.windDir*DEG,P.fetchKm*1000,3.3],40);s.set([P.swellHs,P.swellDir*DEG,Math.sqrt(9.81*2*Math.PI/P.swellLength),P.swellSpread],44);s.set([P.choppy,.0012,600,1,t%600,dt,2.2,1],48);this.d.queue.writeBuffer(this.sim,0,s);
    if(spec)this.dispatch(cp,'SIM_INIT',this.initG,16,16,6);this.dispatch(cp,'SIM_EVOLVE',this.evolveG,16,16,6);this.dispatch(cp,'FFT_ROWS',this.rowsG,256,1,6);this.dispatch(cp,'FFT_COLS',this.colsG,256,1,6);
    for(let m=1;m<9;m++)this.dispatch(cp,'SIM_MIPS',this.simMips[m-1],Math.ceil((N>>m)/8),Math.ceil((N>>m)/8),6);this.specKey=sk;this.simTime=t;this.updates++;
   }
   if(foam){const a=new ArrayBuffer(144),f=new Float32Array(a),ints=new Int32Array(a);for(let l=0;l<2;l++){const size=[128,1024][l]/FR,cx=Math.floor(eye[0]/size),cz=Math.floor(eye[2]/size);ints.set([cx,cz,this.foamFirst?cx+100000:this.foamSnap[l*2],this.foamFirst?cz+100000:this.foamSnap[l*2+1]],l*4);this.foamSnap.set([cx,cz],l*2);f[8+l]=size;}
    f.set([dt,.22,.52+.16*P.foam,2,1,0],10);f.set(L,16);f.set(L.map(x=>1/x),24);f.set([Math.cos(P.windDir*DEG)*.03*P.windSpeed,Math.sin(P.windDir*DEG)*.03*P.windSpeed],32);this.d.queue.writeBuffer(this.foam,0,a);
    this.foamCur=1-this.foamCur;this.dispatch(cp,'FOAM_UPDATE',this.foamG[this.foamCur],FR/8,FR/8,2);for(let m=1;m<FM;m++)this.dispatch(cp,'ARRAY16_MIPS',this.foamMips[this.foamCur][m-1],Math.ceil((FR>>m)/8),Math.ceil((FR>>m)/8),2);this.foamFirst=false;this.foamCamKey=camKey;this.prevFoam=P.foam;
   }
   if(env&&P.haze!==this.haze){this.d.queue.writeBuffer(this.atmo,0,new Float32Array([P.haze,0,0,0]));this.dispatch(cp,'TRANS_LUT',this.transG,32,8);this.dispatch(cp,'MS_LUT',this.msG,4,4);this.haze=P.haze;}
   if(env){this.dispatch(cp,'SKYVIEW_LUT',this.skyG,32,18);this.dispatch(cp,'SUN_VIS',this.sunG,1);this.dispatch(cp,'ENV_CUBE',this.envG,32,32,envChanged?6:1);for(let m=1;m<9;m++)this.dispatch(cp,'CUBE_MIPS',this.envMips[m-1],Math.ceil((256>>m)/8),Math.ceil((256>>m)/8),6);this.envKey=envKey;this.envTime=t;}cp.end();
  }
  o.canvas.dataset.water=JSON.stringify({time:t,renders:this.frameIndex,updates:this.updates,animated:P.animated,backend:spectral?'FFT':'Seascape',waterModel:P.waterModel,lighting:P.lighting,lightingMix:P.lightingMix,sunIntensity:P.sunIntensity,shadowStrength:P.shadowStrength,settings:o.waterRevision||0});
 }
 resize(w,h){
  this.hdr?.destroy();this.bloom?.destroy();this.hdr=this.texture([w,h],'rgba16float',1,true);const bw=Math.max(1,w>>1),bh=Math.max(1,h>>1);this.levels=Math.min(8,Math.floor(Math.log2(Math.max(bw,bh)))+1);this.bloom=this.texture([bw,bh],'rgba16float',this.levels,true);
  this.bloomViews=Array.from({length:this.levels},(_,m)=>level(this.bloom,m,'2d'));this.downG=[];this.upG=[];
  for(let m=0;m<this.levels;m++){this.d.queue.writeBuffer(this.bloomU[m],0,new Float32Array([1/(m?Math.max(1,bw>>(m-1)):w),1/(m?Math.max(1,bh>>(m-1)):h),m===0?1:0,0]));this.downG.push(this.group(this.downPipe,[m?this.bloomViews[m-1]:this.hdr.createView(),this.clamp,{buffer:this.bloomU[m]}]));}
  for(let m=1;m<this.levels;m++){this.d.queue.writeBuffer(this.bloomU[8+m],0,new Float32Array([1/Math.max(1,bw>>m),1/Math.max(1,bh>>m),1,1]));this.upG[m]=this.group(this.upPipe,[this.bloomViews[m],this.clamp,{buffer:this.bloomU[8+m]}]);}
  this.compositeG=this.group(this.composite,[this.hdr.createView(),this.bloomViews[0],this.clamp,{buffer:this.compositeU}]);
 }
 drawSky(pass){if(this.owner.waterSettings.lighting==='classic')return;pass.setPipeline(this.skyPipe);pass.setBindGroup(0,this.backgroundG);pass.draw(3);}
 post(encoder,slot){
  const o=this.owner,P=o.waterSettings,classic=P.lighting==='classic',copy=P.lighting!=='ocean',bloom=!copy&&P.bloom>0;const draw=(pipe,group,view,loadOp='clear',timer={})=>{const p=encoder.beginRenderPass({...timer,colorAttachments:[{view,loadOp,storeOp:'store'}]});p.setPipeline(pipe);p.setBindGroup(0,group);p.draw(3);p.end();};
  if(bloom){const timing=o.timer.pass(slot,'oceanBloom').timestampWrites;
   const first=timing?{timestampWrites:{querySet:timing.querySet,beginningOfPassWriteIndex:timing.beginningOfPassWriteIndex}}:{};
   const last=timing?{timestampWrites:{querySet:timing.querySet,endOfPassWriteIndex:timing.endOfPassWriteIndex}}:{};
   for(let m=0;m<this.levels;m++)draw(this.downPipe,this.downG[m],this.bloomViews[m],'clear',m===0?(this.levels===1&&timing?{timestampWrites:timing}:first):{});
   for(let m=this.levels-1;m>0;m--)draw(this.upPipe,this.upG[m],this.bloomViews[m-1],'load',m===1?last:{});
  }
  o.stats.draws+=(classic?1:2)+(bloom?2*this.levels-1:0);
  this.d.queue.writeBuffer(this.compositeU,0,new Float32Array([P.exposure,P.bloom,0,0,1.05,1.06,-.08,copy?1:0]));
  draw(this.composite,this.compositeG,o.context.getCurrentTexture().createView(),'clear',o.timer.pass(slot,'oceanComposite'));
 }
 dispose(){for(const r of this.resources)r.destroy();}
}
