// A small asynchronous readback ring: profiling never waits on the render loop.
export class GpuTimer {
  constructor(device, onResult, onUnavailable) {
    this.device=device;this.onResult=onResult;this.onUnavailable=onUnavailable;
    this.enabled=device.features.has('timestamp-query');this.disposed=false;
    this.slots=this.enabled?Array.from({length:3},()=>({
      busy:false,
      queries:device.createQuerySet({type:'timestamp',count:14}),
      resolve:device.createBuffer({size:112,usage:GPUBufferUsage.QUERY_RESOLVE|GPUBufferUsage.COPY_SRC}),
      read:device.createBuffer({size:112,usage:GPUBufferUsage.COPY_DST|GPUBufferUsage.MAP_READ}),
    })):[];
  }
  begin(meta) {
    if(!this.enabled)return null;
    const slot=this.slots.find(s=>!s.busy);if(!slot)return null;
    slot.busy=true;slot.labels=[];slot.meta=meta;return slot;
  }
  pass(slot,label) {
    if(!slot)return {};
    const i=slot.labels.length*2;slot.labels.push(label);
    return {timestampWrites:{querySet:slot.queries,beginningOfPassWriteIndex:i,endOfPassWriteIndex:i+1}};
  }
  resolve(encoder,slot) {
    if(!slot)return;
    const count=slot.labels.length*2;
    encoder.resolveQuerySet(slot.queries,0,count,slot.resolve,0);
    encoder.copyBufferToBuffer(slot.resolve,0,slot.read,0,count*8);
  }
  async read(slot) {
    if(!slot)return;
    try {
      await slot.read.mapAsync(GPUMapMode.READ);
      const values=new BigUint64Array(slot.read.getMappedRange());
      const times={cascade:0,irradiance:0,path:0,display:0,total:0};
      slot.labels.forEach((label,i)=>{
        const ms=Number(values[i*2+1]-values[i*2])/1e6;
        times[label]=(times[label]??0)+ms;times.total+=ms;
      });
      slot.read.unmap();
      if(!this.disposed)this.onResult(times,slot.meta);
    } catch(error) {
      if(!this.disposed){this.enabled=false;this.onUnavailable(error.message);}
    } finally { slot.busy=false; }
  }
  dispose() {
    this.disposed=true;
    for(const slot of this.slots){slot.queries.destroy();slot.resolve.destroy();slot.read.destroy();}
  }
}
