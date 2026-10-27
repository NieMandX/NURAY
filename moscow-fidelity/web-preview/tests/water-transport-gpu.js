// GPU tests exercise the production WGSL, production BVH traversal and transport.
import {absorptionCoefficients} from '../src/district/ocean/optics.js';
const $=id=>document.getElementById(id),status=$('status'),results=$('results');
try{
 const adapter=await navigator.gpu.requestAdapter();if(!adapter)throw Error('WebGPU unavailable');
 const device=await adapter.requestDevice(),read=async p=>(await fetch('../src/'+p,{cache:'no-store'})).text();
 let [common,mesh,water,transport]=await Promise.all(['common.wgsl','district/trace.wgsl','district/water-transport.wgsl','district/transport.wgsl'].map(read));
 mesh=mesh.replace('fn cityHasWater()->bool {return false;}','fn cityHasWater()->bool {return true;}')
  .replace('fn waterAbsorption()->vec3f {return vec3f(0);}','fn waterAbsorption()->vec3f {return testP.absorption.xyz;}')
  .replace('fn waterScatteringRate()->f32 {return 0;}','fn waterScatteringRate()->f32 {return testP.tint.w;}')
  .replace('fn waterScatteringTint()->vec3f {return vec3f(1);}','fn waterScatteringTint()->vec3f {return testP.tint.xyz;}')
  .replace('fn waterIndex()->f32 {return 1.333;}','fn waterIndex()->f32 {return testP.absorption.w;}')
  .replace(/fn meshSky\([\s\S]*?\n}/,'fn meshSky(rd:vec3f)->vec3f {return vec3f(1);}')
  .replace('// CITY_WATER_HOOK',`if u32(m.physical.z)==12u {return Surface(vec3f(0),.06,0,waterIndex(),12u,normal,0);}
   if p.y<0 {color*=select(.12,.9,(i32(floor(p.x))+i32(floor(p.z)))%2==0);}`);
 const support=`struct TestParams {absorption:vec4f,tint:vec4f};
 @group(1) @binding(0) var<uniform> testP:TestParams;
 fn cachedIrradiance(p:vec3f,n:vec3f)->vec4f {return vec4f(0);}
 `;
 const entry=`
 @compute @workgroup_size(64) fn checks(@builtin(global_invocation_id) id:vec3u){
 let i=id.x;if i>=16384u{return;}rng=(i*1973u+89173u)|1u;
 let n=vec3f(0,1,0);let m=Surface(vec3f(0),0,0,waterIndex(),12u,n,0);
 let s=sampleWaterInterface(m,n,n,n,waterIndex());
 meshAccumulation[i*7u]=vec4f(s.weight,select(0.0,1.0,s.transmitted));
 let angle=80.0*PI/180.0;let tir=sampleWaterInterface(m,n,n,vec3f(sin(angle),cos(angle),0),1/waterIndex());
 meshAccumulation[i*7u+1u]=vec4f(tir.weight,select(0.0,1.0,tir.transmitted));
 let r=vec3f(-7,4,0);let d=normalize(vec3f(.3,-1,0));let h=traceMesh(r,d,false);let p=r+d*h.t;
 let next=refract(d,n,1/waterIndex());let at=rayOffset(p,n,next);let bed=traceMesh(at,next,false);
 let path=bed.t+distance(p,at);let q=at+next*bed.t;
 meshAccumulation[i*7u+2u]=vec4f(q.x,q.y,path,select(0.0,1.0,pointInWater(vec3f(-6,-1,0))));
 let med=sampleWaterMedium(2.0);
 meshAccumulation[i*7u+3u]=vec4f(med.weight,select(0.0,1.0,med.scatter));
 let deepOrigin=vec3f(3,4,0);let deepHit=traceMesh(deepOrigin,d,false);let dp=deepOrigin+d*deepHit.t;
 let deepAt=rayOffset(dp,n,next);let deepBed=traceMesh(deepAt,next,false);let deepPath=deepBed.t+distance(dp,deepAt);
 meshAccumulation[i*7u+4u]=vec4f(waterAbsorb(deepPath),deepPath);
 let below=vec3f(3,-8,0);let noFloor=meshTransport(below,vec3f(0,-1,0),traceMesh(below,vec3f(0,-1,0),false),false);
 meshAccumulation[i*7u+5u]=vec4f(noFloor,select(0.0,1.0,pointInWater(vec3f(3,4,0))));
 let exiting=sampleWaterInterface(m,-n,-n,-n,1/waterIndex());
 meshAccumulation[i*7u+6u]=vec4f(exiting.weight,select(0.0,1.0,exiting.transmitted));
 }
 @compute @workgroup_size(8,8) fn picture(@builtin(global_invocation_id) id:vec3u){
 let size=vec2u(u.viewport.xy);if any(id.xy>=size){return;}let i=id.x+id.y*size.x;
 var value=vec3f(0);for(var sample=0u;sample<256u;sample++){
 rng=(i*1973u+sample*9277u+89173u)|1u;
 let uv=(vec2f(id.xy)+vec2f(random(),random()))/vec2f(size)*2-1;
 let ro=vec3f(0,7,11);let forward=normalize(vec3f(0,-7,-11));let right=vec3f(1,0,0);let up=cross(right,forward);
 let rd=normalize(forward+right*uv.x*1.05-up*uv.y*.59);
 value+=meshTransport(ro,rd,traceMesh(ro,rd,false),false);
 }meshAccumulation[i]=vec4f(value/256,1);
 }`;
 const module=device.createShaderModule({code:common+'\n'+mesh+'\n'+water+'\n'+support+'\n'+transport+'\n'+entry});
 const errors=(await module.getCompilationInfo()).messages.filter(x=>x.type==='error');if(errors.length)throw Error(errors.map(x=>x.lineNum+': '+x.message).join('\n'));
 const visibility=GPUShaderStage.COMPUTE;
 const layouts=[device.createBindGroupLayout({entries:[
  ...Array.from({length:8},(_,binding)=>({binding,visibility,buffer:{type:binding===0?'uniform':binding===1?'storage':'read-only-storage'}})),
  ...[8,9].map(binding=>({binding,visibility,texture:{sampleType:'float',viewDimension:'2d-array'}})),
  {binding:10,visibility,sampler:{type:'filtering'}},
 ]}),device.createBindGroupLayout({entries:[{binding:0,visibility,buffer:{type:'uniform'}}]})];
 const layout=device.createPipelineLayout({bindGroupLayouts:layouts});
 const pipelines=await Promise.all(['checks','picture'].map(entryPoint=>device.createComputePipelineAsync({layout,compute:{module,entryPoint}})));
 const tris=[];function quad(a,b,c,d,mat){tris.push([a,b,c,mat],[a,c,d,mat]);}
 // Upward water sheet; split-level floor and solid retaining walls. A small
 // opaque bridge above x=-6 validates water-only camera classification.
 quad([-10,0,-7],[-10,0,7],[10,0,7],[10,0,-7],1);
 quad([-10,-2,-7],[-10,-2,7],[0,-2,7],[0,-2,-7],0);
 quad([0,-6,-7],[0,-6,7],[10,-6,7],[10,-6,-7],0);
 quad([0,-6,-7],[0,-2,-7],[0,-2,7],[0,-6,7],0);
 quad([-10,-2,7],[-10,-2,-7],[-10,0,-7],[-10,0,7],0);
 quad([10,-6,-7],[10,-6,7],[10,0,7],[10,0,-7],0);
 quad([-10,-6,-7],[10,-6,-7],[10,0,-7],[-10,0,-7],0);
 quad([10,-6,7],[-10,-6,7],[-10,0,7],[10,0,7],0);
 quad([-6.2,2,-.2],[-6.2,2,.2],[-5.8,2,.2],[-5.8,2,-.2],0);
 const vw=tris.length*3*8,iw=tris.length*3,nw=vw+iw,geometry=new ArrayBuffer((nw+8)*4),f=new Float32Array(geometry),u=new Uint32Array(geometry);
 tris.forEach((t,j)=>t.slice(0,3).forEach((p,k)=>{const a=(j*3+k)*8;f.set(p,a);u[a+6]=0x80000000|t[3];u[vw+j*3+k]=j*3+k;}));
 f.set([-10,-6,-7,0,10,2,7,0],nw);u[nw+7]=tris.length;
 const scene=new ArrayBuffer(80),sf=new Float32Array(scene),su=new Uint32Array(scene);
 su.set([1,12,1,0]);sf.set([-10,-6,-7,0,10,2,7,0],4);su[11]=1;su.set([0,0,vw,nw,1,0,0,0],12);
 function buffer(data,usage=GPUBufferUsage.STORAGE){const b=device.createBuffer({size:data.byteLength,usage:usage|GPUBufferUsage.COPY_DST});device.queue.writeBuffer(b,0,data);return b;}
 const geo=buffer(geometry),tlas=buffer(scene),params=buffer(new Float32Array(8),GPUBufferUsage.UNIFORM),uniform=buffer(new Float32Array(36),GPUBufferUsage.UNIFORM);
 const mats=buffer(Float32Array.of(.7,.7,.7,.7,0,1.5,0,0,1,1,0,0, .1,.2,.3,.06,0,1.333,12,0,1,1,0,0));
 const output=device.createBuffer({size:640*360*16,usage:GPUBufferUsage.STORAGE|GPUBufferUsage.COPY_SRC});
 const texture=device.createTexture({size:[1,1,2],format:'rgba8unorm',usage:GPUTextureUsage.TEXTURE_BINDING|GPUTextureUsage.COPY_DST});
 device.queue.writeTexture({texture},new Uint8Array(8).fill(255),{bytesPerRow:4,rowsPerImage:1},[1,1,2]);
 const view=texture.createView({dimension:'2d-array'}),sampler=device.createSampler();
 function groups(pipeline){return [device.createBindGroup({layout:pipeline.getBindGroupLayout(0),entries:[...[uniform,output,mats,tlas,geo,geo,geo,geo].map((b,binding)=>({binding,resource:{buffer:b}})),{binding:8,resource:view},{binding:9,resource:view},{binding:10,resource:sampler}]}),device.createBindGroup({layout:pipeline.getBindGroupLayout(1),entries:[{binding:0,resource:{buffer:params}}]})];}
 const bind=pipelines.map(groups),uf=new Float32Array(36);uf.set([640,360,0,0]);uf.set([0,1,0,1],20);uf.set([2,1,0,0],24);uf.set([1.5,1,1,12],28);uf[11]=.5;device.queue.writeBuffer(uniform,0,uf);
 function optics(ior,distance,rate=0){const sigma=absorptionCoefficients({absorptionColor:'#8ac6d1',attenuationDistance:distance});device.queue.writeBuffer(params,0,Float32Array.from([...sigma,ior,.4,.7,.6,rate]));return sigma;}
 async function run(which,words){device.pushErrorScope('validation');const staging=device.createBuffer({size:words*4,usage:GPUBufferUsage.MAP_READ|GPUBufferUsage.COPY_DST});const enc=device.createCommandEncoder(),pass=enc.beginComputePass();pass.setPipeline(pipelines[which]);bind[which].forEach((g,i)=>pass.setBindGroup(i,g));if(which===0)pass.dispatchWorkgroups(256);else pass.dispatchWorkgroups(80,45);pass.end();enc.copyBufferToBuffer(output,0,staging,0,words*4);device.queue.submit([enc.finish()]);await staging.mapAsync(GPUMapMode.READ);const out=new Float32Array(staging.getMappedRange().slice(0));staging.unmap();staging.destroy();const err=await device.popErrorScope();if(err)throw Error(err.message);return out;}
 const sigma=optics(1.333,12);let a=await run(0,16384*28),checks=[];
 function check(name,ok,details){checks.push({name,passed:!!ok,details});if(!ok)throw Error(name+': '+details);}
 let means=[0,0,0,0],tir=0,finite=true;for(let i=0;i<16384;i++){for(let k=0;k<4;k++)means[k]+=a[i*28+k]/16384;tir+=a[i*28+7];finite&&=Array.from(a.subarray(i*28,i*28+28)).every(Number.isFinite);}
 const F=((1.333-1)/(1.333+1))**2,expected=F+(1-F)/(1.333**2);
 check('Fresnel + радианс при входе',Math.abs(means[3]-.5)<.015&&Math.abs(means[0]-expected)<.015,JSON.stringify({measured:means,expected}));
 check('Полное внутреннее отражение при 80°',tir===0,'transmitted='+tir);
 const sin=.3/Math.hypot(1,.3)/1.333,cos=Math.sqrt(1-sin*sin),x=-7+4*.3+2*sin/cos;
 check('Преломлённый луч действительно попадает в дно BVH',Math.abs(a[8]-x)<.003&&Math.abs(a[9]+2)<1e-4&&Math.abs(a[10]-2/cos)<.003,JSON.stringify(Array.from(a.subarray(8,11))));
 check('Подводная камера под непрозрачным мостом',a[11]===1,'inside='+a[11]);
 check('Beer–Lambert по двум реальным метрам',sigma.every((s,i)=>Math.abs(a[12+i]-Math.exp(-2*s))<1e-5),'T='+Array.from(a.subarray(12,15)));
 check('6 метров: затухание по наклонному пути до настоящего дна',Math.abs(a[19]-6/cos)<.003&&sigma.every((s,i)=>Math.abs(a[16+i]-Math.exp(-s*6/cos))<1e-4),'T,path='+Array.from(a.subarray(16,20)));
 check('Открытый объём не пропускает фальшивое небо вместо дна',a[20]===0&&a[21]===0&&a[22]===0,'radiance='+Array.from(a.subarray(20,23)));
 check('Камера над водой остаётся в воздухе',a[23]===0,'inside='+a[23]);
 let exitWeight=0;for(let i=0;i<16384;i++)exitWeight+=a[i*28+24]/16384;
 check('Выход в воздух: обратный коэффициент радианса',Math.abs(exitWeight-(F+(1-F)*1.333**2))<.03,'weight='+exitWeight);
 check('Конечные числа',finite,'all finite');
 optics(1,12);a=await run(0,16384*28);check('IOR=1: нет отражения и изменения направления',a[0]===1&&a[3]===1&&Math.abs(a[8]-(-7+6*.3))<.003,JSON.stringify(Array.from(a.subarray(0,4))));
 optics(1.333,12,.5);a=await run(0,16384*28);let events=0;for(let i=0;i<16384;i++)events+=a[i*28+15];check('Мутность: свободный пробег в объёме',Math.abs(events/16384-(1-Math.exp(-1)))<.015,'fraction='+events/16384);
 results.textContent=checks.map(c=>'PASS · '+c.name+'\n'+c.details).join('\n\n');results.dataset.checks=JSON.stringify(checks);
 const canvas=document.querySelector('canvas'),ctx=canvas.getContext('2d');
 async function render(){status.textContent='Считаются 256 сэмплов…';$('render').disabled=true;optics(+$('ior').value,+$('distance').value);const pixels=await run(1,640*360*4),image=ctx.createImageData(640,360);for(let i=0;i<pixels.length;i+=4){for(let k=0;k<3;k++){const v=pixels[i+k];image.data[i+k]=Math.round(255*(v<=.0031308?12.92*v:1.055*Math.max(0,v)**(1/2.4)-.055));}image.data[i+3]=255;}ctx.putImageData(image,0,0);status.textContent='Готово · '+checks.length+' GPU-проверок пройдено · 256 сэмплов';$('render').disabled=false;canvas.dataset.settings=JSON.stringify({ior:+$('ior').value,distance:+$('distance').value});}
 for(const id of ['ior','distance'])$(id).oninput=()=>{$(id+'-value').value=$(id).value;};$('render').onclick=()=>render().catch(fail);await render();
}catch(e){fail(e);}
function fail(e){status.textContent='ОШИБКА: '+e.message;status.dataset.error=e.stack;console.error(e);}
