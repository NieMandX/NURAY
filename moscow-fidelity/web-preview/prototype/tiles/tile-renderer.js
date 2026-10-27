import {layerDefaults,normalizeLayers,layerVisible} from './scene-layers.js?v=scene-layers-1';
import {meshBytes} from './packed-mesh.js?v=moscow-defaults-1';
import {DistrictRenderer} from '../../src/district/renderer.js?v=moscow-preset-2';
import {REGION_GPU_PAGE_BYTES} from '../../src/district/gpu-limits.js?v=moscow-defaults-1';
import {orthographic,lookAt,perspective,multiply,visible} from '../../src/district/math.js?v=moscow-defaults-1';
import {loadCityMaterials} from '../../src/district/city-materials.js?v=ground-reflections-1';
import {planGpuPages} from './gpu-pages.js?v=moscow-defaults-1';
import {activeChunkIds,pageChunkIds,sceneInstances,rasterLayout,traceScene} from './tile-scene.js?v=moscow-defaults-1';

export class TileRenderer extends DistrictRenderer {
  constructor(canvas,onStatus,onError){
    super(canvas,onStatus,onError);this.waterEnabled=true;this.sceneLayers=layerDefaults();
    this.preferredPageLimit=REGION_GPU_PAGE_BYTES;
    this.meshCache=new Map();this.rasterMeshes=new Map();this.tilePages=new Map();
    this.tileModes=new Map();this.streamStats={downloadBytes:0,requests:0,cacheHits:0,evictions:0,releasedGpuBytes:0,residentBytes:0,peakResidentBytes:0};
    this.cacheBudget=24*1048576;
  }
  isChunkVisible(mesh){return layerVisible(mesh,this.sceneLayers);}
  async setSceneLayers(value){
    const wasReady=this.ready;this.ready=false;
    try{
      if(this.device)await this.device.queue.onSubmittedWorkDone();
      this.sceneLayers=normalizeLayers(value);
      if(this.merged){
        this.fenceVisibility?.set(this.sceneLayers.fences);
        if(this.mergedTraceReady)this.rebuildMergedScene();
      }else if(this.state.engine!=='raster'&&wasReady)await this.updateTiles(this.tileModes,{force:true});
      this.updateCounts();this.revision++;this.gpu=null;this.shadowDirty=true;this.tracer.cache.invalidate();this.tracer.reset();
    }finally{this.ready=wasReady;this.publish(true);}
  }
  async open(url){
    // A mutable catalog may publish new content hashes at the same URL. Always
    // revalidate metadata; immutable hash-named mesh files keep normal caching.
    const r=await fetch(url,{cache:'no-cache'});if(!r.ok)throw Error('Не найден каталог тайлов');
    this.tileset=await r.json();this.base=new URL('.',url);this.city=this.tileset;this.sceneName='moscow';
    this.tracePagePlan=this.tileset.extentMetres>1500?[]:planGpuPages(this.tileset,this.pageLimit);
    await loadCityMaterials(this,this.tileset,this.base);
    const span=this.tileset.extentMetres;
    const center=[(this.tileset.boundsMSK[0]+this.tileset.boundsMSK[2])/2-this.tileset.origin[0],0,
      this.tileset.origin[1]-(this.tileset.boundsMSK[1]+this.tileset.boundsMSK[3])/2];
    this.shadowMatrix=multiply(orthographic(span*.8,.1,span*4),lookAt(this.sun.map((x,i)=>center[i]+x*span*2),center));
    this.state.exposure=.85;this.assets=new Map(this.tileset.chunks.map(c=>[c.id,c]));
  }
  chooseTiles({full=false}={}){
    const c=this.camera;let all=this.tileset.tiles;
    if(full&&this.state.engine==='raster')return new Map(all.map(t=>[t.id,'full']));
    if(this.tileset.extentMetres>1500){
      const aspect=this.canvas.width/this.canvas.height;
      const fov=2*Math.atan(Math.tan(44*Math.PI/360)*Math.max(1,1.1/aspect));
      const eye=[Math.sin(c.yaw)*Math.cos(c.pitch)*c.distance+c.target[0],Math.sin(c.pitch)*c.distance+c.target[1],Math.cos(c.yaw)*Math.cos(c.pitch)*c.distance+c.target[2]];
      const matrix=multiply(perspective(fov,aspect,1,this.tileset.extentMetres*6,true),lookAt(eye,c.target));
      all=all.filter(t=>{
        const b=t.contentBounds??t.bounds,margin=150;
        return visible({min:b.min.map(v=>v-margin),max:b.max.map(v=>v+margin)},matrix);
      });
    }
    if(c.distance>360)return this.fitTraceTiles(new Map(all.map(t=>[t.id,'coarse'])));
    const radius=Math.max(35,Math.min(140,c.distance*.40));
    return this.fitTraceTiles(new Map(all.map(t=>{
      const b=t.bounds,p=c.target,dx=Math.max(b.min[0]-p[0],0,p[0]-b.max[0]),dz=Math.max(b.min[2]-p[2],0,p[2]-b.max[2]);
      const threshold=radius+(this.tileModes.get(t.id)==='full'?20:0);
      return [t.id,Math.hypot(dx,dz)<=threshold?'full':'coarse'];
    })));
  }
  fitTraceTiles(modes){
    this.streamStats.budgetLimited=false;
    if(this.state.engine==='raster')return modes;
    // A finite resident set is needed by the four BLAS bindings. Keep the
    // nearest geometry first; scene-wide raster loading remains unchanged.
    const p=this.camera.target,tiles=this.tileset.tiles.filter(t=>modes.has(t.id));
    const distance=t=>{const b=t.bounds;return Math.hypot(Math.max(b.min[0]-p[0],0,p[0]-b.max[0]),Math.max(b.min[2]-p[2],0,p[2]-b.max[2]));};
    tiles.sort((a,b)=>distance(a)-distance(b)||a.id.localeCompare(b.id));
    const budget=Math.min(512*1048576,4*this.pageLimit);
    const select=n=>new Map(tiles.slice(0,n).map(t=>[t.id,modes.get(t.id)]));
    let lo=0,hi=tiles.length;
    while(lo<hi){const mid=Math.ceil((lo+hi)/2);try{
      const pages=planGpuPages(this.tileset,this.pageLimit,4,select(mid));
      if(pages.reduce((sum,p)=>sum+p.bytes,0)<=budget)lo=mid;else hi=mid-1;
    }catch{hi=mid-1;}}
    if(!lo&&tiles.length)throw Error('Ближайший тайл превышает бюджет рейтрейса');
    this.streamStats.budgetLimited=lo<tiles.length;return select(lo);
  }
  async mesh(id){
    let entry=this.meshCache.get(id);
    if(entry){entry.used=performance.now();this.streamStats.cacheHits++;return entry.mesh;}
    const c=this.assets.get(id);
    const compressed=await meshBytes(c.file,this.base,this.meshPack);this.streamStats.downloadBytes+=compressed.byteLength;this.streamStats.requests++;
    const raw=await new Response(new Blob([compressed]).stream().pipeThrough(new DecompressionStream('gzip'))).arrayBuffer();
    const total=c.vertexBytes+c.indexBytes+c.nodeBytes+c.lineageBytes;
    if(raw.byteLength!==total||c.format!=='nuray-tile-mesh-v1')throw Error('Повреждён блок '+id);
    // The manifest's content hash pins the exact published asset version.
    const hash=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',raw)),x=>x.toString(16).padStart(2,'0')).join('');
    if(hash!==c.sha256)throw Error('Контрольная сумма блока не совпала: '+id);
    const mesh={...c,vertices:raw.slice(0,c.vertexBytes),indices:raw.slice(c.vertexBytes,c.vertexBytes+c.indexBytes),
      nodes:raw.slice(c.vertexBytes+c.indexBytes,c.vertexBytes+c.indexBytes+c.nodeBytes)};
    this.waterHeights.add(id,mesh.vertices,this.tileset.materials,c.instanced);
    this.groundHeights.add(id,mesh.vertices,this.tileset.materials,c.instanced);
    this.meshCache.set(id,{mesh,bytes:c.vertexBytes+c.indexBytes+c.nodeBytes,used:performance.now()});return mesh;
  }
  trimCache(active){
    let bytes=[...this.meshCache.values()].reduce((n,c)=>n+c.bytes,0);
    // Prefer inactive entries, then discard decoded active entries if needed:
    // their GPU copies remain resident and do not depend on the CPU cache.
    for(const [id,c] of [...this.meshCache].sort((a,b)=>Number(active.has(a[0]))-Number(active.has(b[0]))||a[1].used-b[1].used)){
      if(bytes<=this.cacheBudget)break;
      this.meshCache.delete(id);bytes-=c.bytes;this.streamStats.evictions++;
    }
    this.streamStats.cpuCacheBytes=bytes;
  }
  async updateTiles(modes,{force=false}={}){
    const key=JSON.stringify([this.state.engine==='raster'?'raster':'trace',[...modes]]);
    if(!force&&key===this.streamKey)return;
    const started=performance.now();
    this.stats.buildMs=null;this.stats.uploadMs=null;this.stats.bvhBuildMs=null;
    this.loading=true;this.phase='Подгружаем участки';this.progress=0;this.publish(true);
    const active=activeChunkIds(this.tileset,modes);
    const instances=sceneInstances(this.tileset,modes).filter(i=>this.state.engine==='raster'||this.isChunkVisible(this.assets.get(i.mesh)));
    if(this.tileset.extentMetres>1500&&this.state.engine!=='raster'){
      // Large regions reserve only the requested detail, not every off-screen
      // full-detail tile. Re-plan before allocating or destroying any GPU data.
      this.tracePagePlan=planGpuPages(this.tileset,this.pageLimit,4,modes);
    }
    const meshData=new Map();let completed=0;
    // At most four network/decompression operations in flight, independently
    // of how many render chunks a tile contains.
    // Geometry already in an unchanged GPU allocation needs no CPU copy.
    // A region larger than the decoded cache must not re-fetch all far tiles
    // just because one nearby tile gains or loses its paint meshes.
    const required=new Set();
    if(this.state.engine==='raster'){
      for(const id of active)if(!this.rasterMeshes.has(id))required.add(id);
    }else this.tracePagePlan.forEach((allocation,page)=>{
      const ids=pageChunkIds(allocation,this.tileset,modes);
      if(this.tilePages.get(page)?.key!==ids.join('|'))for(const id of ids)required.add(id);
    });
    const ids=[...required];let next=0;
    await Promise.all(Array.from({length:Math.min(4,ids.length)},async()=>{
      while(next<ids.length){const id=ids[next++];meshData.set(id,await this.mesh(id));this.progress=++completed/ids.length;this.publish();}
    }));
    this.ready=false;await this.device.queue.onSubmittedWorkDone();
    const commitStarted=performance.now();this.stats.bvhBuildMs=0;
    if(this.state.engine==='raster')this.commitRaster(active,meshData,instances);
    else this.commitTrace(modes,meshData,instances);
    // CPU submission time, excluding the separately measured top-level BVH build.
    this.stats.uploadMs=Math.max(0,performance.now()-commitStarted-this.stats.bvhBuildMs);
    this.tileModes=new Map(modes);this.streamKey=key;this.trimCache(active);
    this.revision++;this.gpu=null;this.tracer.cache.invalidate();this.tracer.reset();this.shadowDirty=true;
    this.lastTime=0;this.shadowMs=null;this.stats.buildMs=performance.now()-started;
    this.ready=true;this.loading=false;
    this.streamStats.fullTiles=[...modes.values()].filter(x=>x==='full').length;
    this.streamStats.coarseTiles=modes.size-this.streamStats.fullTiles;
    this.streamStats.peakResidentBytes=Math.max(this.streamStats.peakResidentBytes,this.streamStats.residentBytes);
    this.publish(true);
  }
  releaseRaster(){
    for(const c of this.rasterMeshes.values()){c.vertex.destroy();c.index.destroy();this.streamStats.releasedGpuBytes+=c.vertexBytes+c.indexBytes;}
    this.rasterMeshes.clear();
    if(this.rasterInstanceBytes){this.instanceBuffer.destroy();this.streamStats.releasedGpuBytes+=this.rasterInstanceBytes;this.rasterInstanceBytes=0;}
  }
  releaseTrace(){
    for(const c of this.tilePages.values()){c.buffer.destroy();this.streamStats.releasedGpuBytes+=c.bytes;}
    this.tilePages.clear();this.tracer.pages=[];
    if(this.tracer.scene){this.streamStats.releasedGpuBytes+=this.traceSceneBytes??0;this.tracer.scene.destroy();}
    this.traceSceneBytes=0;this.tracer.scene=null;this.tracer.group=null;
  }
  commitRaster(active,meshes,instances){
    this.releaseTrace();
    for(const [id,c] of this.rasterMeshes)if(!active.has(id)){
      c.vertex.destroy();c.index.destroy();this.streamStats.releasedGpuBytes+=c.vertexBytes+c.indexBytes;this.rasterMeshes.delete(id);
    }
    for(const id of active)if(!this.rasterMeshes.has(id)){
      const c=meshes.get(id),vertex=this.device.createBuffer({size:c.vertexBytes,usage:GPUBufferUsage.VERTEX|GPUBufferUsage.COPY_DST}),index=this.device.createBuffer({size:c.indexBytes,usage:GPUBufferUsage.INDEX|GPUBufferUsage.COPY_DST});
      this.device.queue.writeBuffer(vertex,0,c.vertices);this.device.queue.writeBuffer(index,0,c.indices);
      this.rasterMeshes.set(id,{...this.assets.get(id),vertex,index,instanceFirst:0,instanceCount:1});
    }
    const layout=rasterLayout(instances,this.assets);
    this.streamStats.releasedGpuBytes+=this.rasterInstanceBytes??0;this.setInstances(layout.transforms.buffer);this.rasterInstanceBytes=layout.transforms.byteLength;
    this.chunks=layout.draws.map(draw=>({...this.rasterMeshes.get(draw.id),...draw}));
    this.stats.geometryBytes=this.chunks.reduce((n,c)=>n+c.vertexBytes+c.indexBytes,0)+this.rasterInstanceBytes;this.stats.bvhBytes=0;
    this.streamStats.residentBytes=this.stats.geometryBytes;this.updateCounts();
  }
  commitTrace(modes,meshes,instances){
    this.releaseRaster();const descriptors=new Map();let geometry=0,nodes=0;
    for(const [page,arena] of this.tilePages)if(page>=this.tracePagePlan.length){
      arena.buffer.destroy();this.streamStats.releasedGpuBytes+=arena.bytes;this.tilePages.delete(page);
    }
    this.tracer.pages.length=this.tracePagePlan.length;
    this.tracePagePlan.forEach((allocation,page)=>{
      const ids=pageChunkIds(allocation,this.tileset,modes);
      const bytes=ids.reduce((n,id)=>{const c=this.assets.get(id);return n+c.vertexBytes+c.indexBytes+c.nodeBytes;},0);
      if(bytes>this.pageLimit)throw Error('Превышен лимит GPU-страницы: '+page);
      const key=ids.join('|');let arena=this.tilePages.get(page);
      if(arena?.key!==key){
        if(arena){arena.buffer.destroy();this.streamStats.releasedGpuBytes+=arena.bytes;}
        const buffer=this.device.createBuffer({label:'Spatial GPU page '+page,size:Math.max(4,bytes),usage:GPUBufferUsage.STORAGE|GPUBufferUsage.COPY_DST});let offset=0;
        for(const id of ids){const c=meshes.get(id);for(const data of [c.vertices,c.indices,c.nodes]){this.device.queue.writeBuffer(buffer,offset,data);offset+=data.byteLength;}}
        arena={key,buffer,bytes};this.tilePages.set(page,arena);
      }
      this.tracer.pages[page]=arena.buffer;let offset=0;
      for(const id of ids){const c=this.assets.get(id),vertex=offset/4,index=vertex+c.vertexBytes/4,node=index+c.indexBytes/4;
        descriptors.set(id,{page,vertex,index,nodes:node,nodeCount:c.nodeCount});offset+=c.vertexBytes+c.indexBytes+c.nodeBytes;geometry+=c.vertexBytes+c.indexBytes;nodes+=c.nodeBytes;}
    });
    const bvhStarted=performance.now(),scene=traceScene(instances,this.assets,descriptors);
    this.stats.bvhBuildMs=performance.now()-bvhStarted;
    if(this.tracer.scene){this.streamStats.releasedGpuBytes+=this.traceSceneBytes??0;this.tracer.scene.destroy();}
    this.traceSceneBytes=scene.byteLength;this.tracer.scene=this.device.createBuffer({size:scene.byteLength,usage:GPUBufferUsage.STORAGE|GPUBufferUsage.COPY_DST});this.device.queue.writeBuffer(this.tracer.scene,0,scene);
    this.chunks=rasterLayout(instances,this.assets).draws.map(draw=>({...this.assets.get(draw.id),...draw}));this.stats.geometryBytes=geometry;this.stats.bvhBytes=nodes+scene.byteLength;
    this.streamStats.residentBytes=geometry+nodes+scene.byteLength;this.updateCounts();this.tracer.bind();
  }
  updateCounts(){
    const chunks=this.chunks.filter(c=>this.isChunkVisible(c));
    const triangles=c=>c.triangles-(this.sceneLayers.fences?0:c.fenceTriangles??0);
    this.stats.triangles=chunks.reduce((n,c)=>n+triangles(c)*c.instanceCount,0);
    this.stats.uniqueTriangles=chunks.reduce((n,c)=>n+triangles(c),0);
    this.stats.vertices=chunks.reduce((n,c)=>n+c.vertexCount,0);
    this.stats.meshCount=chunks.length;
    this.stats.sharedInstances=chunks.reduce((n,c)=>n+(c.instanced?c.instanceCount:0),0);
    this.stats.submitted=0;this.stats.draws=0;
  }
  timing(times,meta){
    if(meta.revision!==this.revision)return;
    super.timing(times,meta);
    // Include every timed pass in the frame, including a refreshed shadow map.
    this.gpu=times.total;this.publish(true);
  }
  publish(force=false){
    this.stats.frameMeasured=this.lastTime>0;
    this.stats.tabHidden=document.hidden;this.stats.waterFrozen=this.waterEnabled&&!this.waterSettings.animated;
    super.publish(force);
  }
  dispose(){this.releaseRaster();this.releaseTrace();this.meshCache.clear();super.dispose();}
}
