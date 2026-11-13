import {instanceBounds,clipPlanes,compactVisibleInstances} from '../../src/district/instance-culling.js';
const EMPTY=new Set();

export class MainInstanceCulling {
  constructor(owner){
    this.owner=owner;this.enabled=true;this.source=owner.mergedTransforms;
    this.bounds=instanceBounds(owner.chunks,this.source);this.output=this.source.slice();
    this.buffer=owner.device.createBuffer({label:'Main view · compact visible instances',size:this.source.byteLength,usage:GPUBufferUsage.STORAGE|GPUBufferUsage.COPY_DST});
    owner.device.queue.writeBuffer(this.buffer,0,this.output);
    owner.stats.geometryBytes+=this.buffer.size;owner.streamStats.residentBytes+=this.buffer.size;
    owner.streamStats.peakResidentBytes=Math.max(owner.streamStats.peakResidentBytes,owner.streamStats.residentBytes);
  }
  prepare(matrix){
    const o=this.owner,gs=o.gaussianVegetation,replaced=gs?.available()?gs.active:EMPTY;
    const cull=this.enabled&&o.state.culling;
    const key=Array.from(matrix).join(',')+','+cull;
    if(key===this.key&&replaced===this.replaced)return;
    this.key=key;this.replaced=replaced;const start=performance.now();
    const result=compactVisibleInstances(o.chunks,this.source,this.bounds,cull?clipPlanes(matrix):null,replaced,this.output);
    this.counts=result.counts;o.device.queue.writeBuffer(this.buffer,0,this.output);
    const stats={enabled:cull,total:result.total,visible:result.visible,culled:result.culled,substituted:result.substituted,prepareMs:performance.now()-start,bytes:this.buffer.size};
    o.canvas.dataset.instanceCulling=JSON.stringify(stats);this.onStatus?.(stats);
  }
  chunks(chunks){return chunks.map(c=>this.counts?.has(c.id)?{...c,instanceCount:this.counts.get(c.id)}:c).filter(c=>c.instanceCount>0);}
  group(original){
    if(this.original!==original){
      this.original=original;const o=this.owner;
      const entries=o.rasterEntries(o.uniform).map(e=>e.binding===8?{binding:8,resource:{buffer:this.buffer}}:e);
      this.bind=o.device.createBindGroup({layout:o.pipeline.getBindGroupLayout(0),entries});
    }
    return this.bind;
  }
  dispose(){this.buffer.destroy();}
}

export function installInstanceCulling(owner){
  // Review URLs retain this opt-in when switching to WebGL or tiled geometry.
  // Those renderers already choose visible tiles and have no merged transform buffer.
  if(!owner.merged||!owner.device)return null;
  const c=new MainInstanceCulling(owner);owner.instanceCulling=c;
  const label=document.createElement('label'),check=document.createElement('input');check.type='checkbox';check.checked=true;
  label.append(check,document.createTextNode(' Отсекать экземпляры вне кадра · проба'));document.getElementById('settings').append(label);
  check.onchange=()=>{c.enabled=check.checked;owner.revision++;};
  return c;
}
