import {groundMaterialRole} from './ground-surfaces.js?v=dry-ground-1';
import {isRoad} from './surface-effects.js?v=moscow-defaults-1';
import {isFacade,facadePixels} from './facade-relief.js?v=moscow-defaults-1';
import {cityBase} from './city-config.js?v=moscow-defaults-1';
export async function loadCityMaterials(owner,scene,assetBase=cityBase){
  const d=owner.device,count=scene.materials.length,size=512,levels=10;
  if(count>d.limits.maxTextureArrayLayers)throw new Error('Недостаточно слоёв текстур для материалов сцены.');
  owner.changing=true;await d.queue.onSubmittedWorkDone();
  owner.materialBuffer?.destroy();owner.textures?.forEach(t=>t.destroy());
  const data=new Float32Array(count*12);
  scene.materials.forEach((m,i)=>data.set([...m.color,m.roughness,m.metallic,m.ior,m.kind,m.alphaCutoff,1,1,isFacade(m)?1:groundMaterialRole(m),isRoad(m)?1:0],i*12));
  owner.materialBuffer=d.createBuffer({size:data.byteLength,usage:GPUBufferUsage.STORAGE,mappedAtCreation:true});
  new Float32Array(owner.materialBuffer.getMappedRange()).set(data);owner.materialBuffer.unmap();
  owner.textures=[d.createTexture({size:[size,size,count],mipLevelCount:levels,format:'rgba8unorm',usage:GPUTextureUsage.STORAGE_BINDING|GPUTextureUsage.TEXTURE_BINDING}),
    d.createTexture({size:[8,512,count],mipLevelCount:10,format:'rgba8unorm',usage:GPUTextureUsage.STORAGE_BINDING|GPUTextureUsage.COPY_DST|GPUTextureUsage.TEXTURE_BINDING}),
    d.createTexture({size:[1,1,count],format:'rgba8unorm',usage:GPUTextureUsage.COPY_DST|GPUTextureUsage.TEXTURE_BINDING})];
  const source=d.createTexture({size:[size,size,count],format:'rgba8unorm-srgb',usage:GPUTextureUsage.COPY_DST|GPUTextureUsage.TEXTURE_BINDING|GPUTextureUsage.RENDER_ATTACHMENT});
  try{
    const white=new Uint8Array(size*size*4).fill(255);
    for(let i=0;i<count;i++){
      const m=scene.materials[i];
      if(isFacade(m)){d.queue.writeTexture({texture:source,origin:[0,0,i]},facadePixels(size,size),{bytesPerRow:size*4},[size,size]);}
      else if(m.texture){
        const r=await fetch(new URL(m.texture,assetBase));if(!r.ok)throw new Error('Не найдена текстура '+m.texture);
        const image=await createImageBitmap(await r.blob(),{resizeWidth:size,resizeHeight:size,premultiplyAlpha:'none',colorSpaceConversion:'none'});
        d.queue.copyExternalImageToTexture({source:image},{texture:source,origin:[0,0,i],premultipliedAlpha:false},[size,size]);image.close();
      }else d.queue.writeTexture({texture:source,origin:[0,0,i]},white,{bytesPerRow:size*4},[size,size]);
      const normal=isFacade(m)?facadePixels(8,512,true):new Uint8Array(8*512*4);if(!isFacade(m))for(let j=0;j<normal.length;j+=4)normal.set([128,128,255,255],j);
      d.queue.writeTexture({texture:owner.textures[1],origin:[0,0,i]},normal,{bytesPerRow:32},[8,512]);
      d.queue.writeTexture({texture:owner.textures[2],origin:[0,0,i]},Uint8Array.of(255,Math.round(m.roughness*255),Math.round(m.metallic*255),255),{},[1,1]);
    }
    const r=await fetch(new URL('./city-textures.wgsl',import.meta.url));const module=d.createShaderModule({code:await r.text()});
    const errors=(await module.getCompilationInfo()).messages.filter(m=>m.type==='error');if(errors.length)throw new Error(errors.map(e=>e.message).join('\n'));
    const pipeline=await d.createComputePipelineAsync({layout:'auto',compute:{module,entryPoint:'main'}}),encoder=d.createCommandEncoder();
    for(let mip=0;mip<levels;mip++){
      const from=mip===0?source:owner.textures[0];
      const bind=d.createBindGroup({layout:pipeline.getBindGroupLayout(0),entries:[
        {binding:0,resource:from.createView({dimension:'2d-array',baseMipLevel:Math.max(0,mip-1),mipLevelCount:1})},
        {binding:1,resource:owner.textures[0].createView({dimension:'2d-array',baseMipLevel:mip,mipLevelCount:1})}]});
      const p=encoder.beginComputePass();p.setPipeline(pipeline);p.setBindGroup(0,bind);p.dispatchWorkgroups(Math.ceil((size>>mip)/8),Math.ceil((size>>mip)/8),count);p.end();
    }
    for(let mip=1;mip<levels;mip++){
      const bind=d.createBindGroup({layout:pipeline.getBindGroupLayout(0),entries:[{binding:0,resource:owner.textures[1].createView({dimension:'2d-array',baseMipLevel:mip-1,mipLevelCount:1})},{binding:1,resource:owner.textures[1].createView({dimension:'2d-array',baseMipLevel:mip,mipLevelCount:1})}]});
      const p=encoder.beginComputePass();p.setPipeline(pipeline);p.setBindGroup(0,bind);p.dispatchWorkgroups(1,Math.ceil((512>>mip)/8),count);p.end();
    }
    d.queue.submit([encoder.finish()]);await d.queue.onSubmittedWorkDone();
  }finally{source.destroy();}
  owner.state.materials=count;owner.stats.textureBytes=(size*size*4*(4/3)+8*512*4*(4/3)+4)*count+data.byteLength;
  owner.bindRaster();owner.tracer.bind();owner.changing=false;
}
