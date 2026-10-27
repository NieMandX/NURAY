// Mixed static batches retain the original geometry and BLAS. A negative tint
// is a runtime-only visibility sentinel, never a change to the published GLB.
export function validateVisibility(data,headerSha,draws){
  if(data.format!=='nuray-merged-visibility-v1'||data.headerSha256!==headerSha||data.draws.length!==draws.length)throw Error('Карта категорий не соответствует GLB');
  return new Map(data.draws.map((record,i)=>{
    const draw=draws[i];if(record.id!==draw.id||record.name!==draw.name)throw Error('Неверная группа категорий GLB');
    let end=0;for(const [start,count] of record.fenceVertexRanges??[]){if(!Number.isInteger(start)||!Number.isInteger(count)||count<1||start<end||start+count>draw.vertexCount)throw Error('Неверный диапазон ограждений');end=start+count;}
    return [record.id,record];
  }));
}
export class MergedFenceVisibility{
  constructor(renderer){this.renderer=renderer;this.buffers=[];this.groups=[];this.visible=true;}
  async init(records){
    const r=this.renderer,device=r.device;
    const code=`@group(0) @binding(0) var<storage,read_write> geometry:array<u32>;
@group(0) @binding(1) var<storage,read> offsets:array<u32>;
@group(0) @binding(2) var<uniform> control:vec4u;
@compute @workgroup_size(64) fn main(@builtin(global_invocation_id) id:vec3u){if id.x<control.x{geometry[offsets[id.x]]=control.y;}}`;
    this.pipeline=await device.createComputePipelineAsync({layout:'auto',compute:{module:device.createShaderModule({code}),entryPoint:'main'}});
    for(const record of records.values()){
      const ranges=record.fenceVertexRanges;if(!ranges?.length)continue;
      const mesh=r.rasterMeshes.get(record.id),count=ranges.reduce((n,x)=>n+x[1],0),offsets=new Uint32Array(count);let i=0;
      for(const [start,length] of ranges)for(let v=start;v<start+length;v++)offsets[i++]=(mesh.vertexOffset??0)/4+v*8+7;
      const ids=device.createBuffer({size:offsets.byteLength,usage:GPUBufferUsage.STORAGE,mappedAtCreation:true});new Uint32Array(ids.getMappedRange()).set(offsets);ids.unmap();
      const control=device.createBuffer({size:16,usage:GPUBufferUsage.UNIFORM|GPUBufferUsage.COPY_DST});
      const group=device.createBindGroup({layout:this.pipeline.getBindGroupLayout(0),entries:[{binding:0,resource:{buffer:mesh.vertex}},{binding:1,resource:{buffer:ids}},{binding:2,resource:{buffer:control}}]});
      this.groups.push({group,control,count});this.buffers.push(ids,control);
    }
  }
  set(visible){
    if(visible===this.visible)return;this.visible=visible;
    const device=this.renderer.device,encoder=device.createCommandEncoder();
    for(const {group,control,count} of this.groups){device.queue.writeBuffer(control,0,new Uint32Array([count,visible?0:0xbf800000,0,0]));const pass=encoder.beginComputePass();pass.setPipeline(this.pipeline);pass.setBindGroup(0,group);pass.dispatchWorkgroups(Math.ceil(count/64));pass.end();}
    device.queue.submit([encoder.finish()]);
  }
  destroy(){this.buffers.forEach(b=>b.destroy());this.buffers=[];this.groups=[];}
}
