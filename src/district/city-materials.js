import {cityBase} from './city-config.js?v=nuray-cloud-1';
export async function loadCityMaterials(owner,scene){
  const d=owner.device,count=scene.materials.length,size=512,levels=10;
  if(count>d.limits.maxTextureArrayLayers)throw new Error('Недостаточно слоёв текстур для материалов сцены.');
  owner.changing=true;await d.queue.onSubmittedWorkDone();
  owner.materialBuffer?.destroy();owner.textures?.forEach(t=>t.destroy());
  const data=new Float32Array(count*12);
  scene.materials.forEach((m,i)=>data.set([...m.color,m.roughness,m.metallic,m.ior,m.kind,m.alphaCutoff,1,1,0,0],i*12));
  owner.materialBuffer=d.createBuffer({size:data.byteLength,usage:GPUBufferUsage.STORAGE,mappedAtCreation:true});
  new Float32Array(owner.materialBuffer.getMappedRange()).set(data);owner.materialBuffer.unmap();
  owner.textures=[d.createTexture({size:[size,size,count],mipLevelCount:levels,format:'rgba8unorm',usage:GPUTextureUsage.STORAGE_BINDING|GPUTextureUsage.TEXTURE_BINDING}),
    ...Array.from({length:2},()=>d.createTexture({size:[1,1,count],format:'rgba8unorm',usage:GPUTextureUsage.COPY_DST|GPUTextureUsage.TEXTURE_BINDING}))];
  const source=d.createTexture({size:[size,size,count],format:'rgba8unorm-srgb',usage:GPUTextureUsage.COPY_DST|GPUTextureUsage.TEXTURE_BINDING|GPUTextureUsage.RENDER_ATTACHMENT});
  try{
    const white=new Uint8Array(size*size*4).fill(255);
    for(let i=0;i<count;i++){
      const m=scene.materials[i];
      if(m.texture){
        const r=await fetch(new URL(m.texture,cityBase));if(!r.ok)throw new Error('Не найдена текстура '+m.texture);
        const image=await createImageBitmap(await r.blob(),{resizeWidth:size,resizeHeight:size,premultiplyAlpha:'none',colorSpaceConversion:'none'});
        d.queue.copyExternalImageToTexture({source:image},{texture:source,origin:[0,0,i],premultipliedAlpha:false},[size,size]);image.close();
      }else d.queue.writeTexture({texture:source,origin:[0,0,i]},white,{bytesPerRow:size*4},[size,size]);
      d.queue.writeTexture({texture:owner.textures[1],origin:[0,0,i]},Uint8Array.of(128,128,255,255),{},[1,1]);
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
    d.queue.submit([encoder.finish()]);await d.queue.onSubmittedWorkDone();
  }finally{source.destroy();}
  owner.state.materials=count;owner.stats.textureBytes=(size*size*4*(4/3)+8)*count+data.byteLength;
  owner.bindRaster();owner.tracer.bind();owner.changing=false;
}
