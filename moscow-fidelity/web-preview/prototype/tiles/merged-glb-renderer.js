import {MergedFenceVisibility,validateVisibility} from './merged-visibility.js?v=scene-layers-1';
import {TileRenderer} from './tile-renderer.js?v=large-region-2';
import {loadCityMaterials} from '../../src/district/city-materials.js?v=large-region-1';
import {orthographic,lookAt,multiply} from '../../src/district/math.js?v=moscow-defaults-1';
import {planMergedTrace,mergedInstances,sha256} from './merged-trace.js?v=large-region-1';
import {traceScene} from './tile-scene.js?v=moscow-defaults-1';

import {openMergedAsset,GlbStream} from './merged-asset.js?v=large-region-1';
export {GlbStream};
export class MergedGlbRenderer extends TileRenderer {
  constructor(...args){super(...args);this.merged=true;this.objectURLs=[];}
  async open(catalogURL){
    const start=performance.now();this.ready=false;this.loading=true;this.phase='Читаем объединённую сцену';this.progress=0;this.publish(true);
    this.base=new URL('.',catalogURL);this.modelURL=new URL('merged/model.glb',catalogURL);
    const metadataResponse=await fetch(new URL('merged/metadata.json',catalogURL));
    if(!metadataResponse.ok)throw Error('Не найдены сведения об объединённой сцене');
    const metadata=await metadataResponse.json();
    if(metadata.asset){
      if(!['model.glb','model.gltf'].includes(metadata.asset.file))throw Error('Неверный формат объединённой сцены');
      this.modelURL=new URL('merged/'+metadata.asset.file,catalogURL);
    }
    let last=0,previous=0;
    const asset=await openMergedAsset(this.modelURL,{
      base:catalogURL,
      spec:this.assetDelivery?.merged,bufferSpec:this.assetDelivery?.mergedBuffer,
      onBytes:bytes=>{this.streamStats.downloadBytes+=bytes-previous;previous=bytes;},
      onProgress:(bytes,length)=>{this.progress=length>0?Math.min(1,bytes/length):0;if(performance.now()-last>200){last=performance.now();this.publish(true);}},
    });
    const {reader,doc,header,length,binaryLength,expectedStreamBytes}=asset;this.mergedFormat=asset.format;
    this.streamStats.requests=asset.format==='gltf'?3:2;
    try{
      const data=doc.extras?.nuray;if(data?.format!=='nuray-merged-glb-v1')throw Error('Этот GLB не содержит данных объединённой сцены NURAY');
      {
        const response=await fetch(this.visibilityURL??new URL('merged/visibility.json',catalogURL));
        if(!response.ok&&(this.visibilityURL||response.status!==404))throw Error('Не найдена карта категорий GLB');
        if(response.ok){this.visibilityMetadata=validateVisibility(await response.json(),await sha256(header),data.draws);
        for(const draw of data.draws){const entry=this.visibilityMetadata.get(draw.id);draw.layer=entry.layer??null;draw.fenceTriangles=entry.fenceTriangles??0;}}
      }
      const manifestResponse=await fetch(new URL('trace/manifest.json',this.modelURL),{cache:'no-cache'});
      if(manifestResponse.ok){
        const manifest=await manifestResponse.json();
        if(manifest.glbBytes!==length||manifest.headerSha256!==await sha256(header))throw Error('Ускоритель устарел: GLB изменился. Подготовьте merged/trace заново.');
        this.mergedRecords=new Map(manifest.draws.map(d=>[d.id,d]));
        try{this.mergedPlan=planMergedTrace(data.draws,manifest,this.pageLimit);}
        catch(error){if(error.code!=='TRACE_CAPACITY'||this.state.engine!=='raster')throw error;this.mergedTraceUnavailable=error.message;}
        if(this.mergedPlan)this.mergedArenas=this.mergedPlan.sizes.map(size=>this.device.createBuffer({label:'Whole scene · shared raster / trace geometry',size,usage:GPUBufferUsage.STORAGE|GPUBufferUsage.VERTEX|GPUBufferUsage.INDEX|GPUBufferUsage.COPY_DST}));
      }else if(manifestResponse.status!==404||this.state.engine!=='raster')throw Error('Для полной трассировки подготовьте merged/trace/manifest.json из model.glb');
      const bounds={min:[data.boundsMSK[0]-data.origin[0],-100,data.origin[1]-data.boundsMSK[3]],max:[data.boundsMSK[2]-data.origin[0],500,data.origin[1]-data.boundsMSK[1]]};
      this.tileset={...data,tileSizeM:data.extentMetres,grid:{columns:1,rows:1},tiles:[{id:'whole',east:0,north:0,boundsMSK:data.boundsMSK,bounds,chunks:[],instances:[]}],chunks:[],textures:{}};
      this.city=this.tileset;this.sceneName='moscow';this.state.exposure=.85;
      const center=[(bounds.min[0]+bounds.max[0])/2,0,(bounds.min[2]+bounds.max[2])/2],span=data.extentMetres;
      this.shadowMatrix=multiply(orthographic(span*.8,.1,span*4),lookAt(this.sun.map((x,i)=>center[i]+x*span*2),center));
      const wanted=new Map();doc.images.forEach((im,i)=>wanted.set(im.bufferView,{type:'image',image:im,index:i}));wanted.set(data.transformsView,{type:'transforms'});
      for(const draw of data.draws){wanted.set(draw.vertexView,{type:'vertex',draw});wanted.set(draw.indexView,{type:'index',draw});}
      const urls=new Map();let position=0,uploadMs=0,materialsReady=false;
      for(const [id,action] of [...wanted].sort((a,b)=>doc.bufferViews[a[0]].byteOffset-doc.bufferViews[b[0]].byteOffset)){
        const view=doc.bufferViews[id];if(view.byteOffset<position)throw Error('Перекрывающиеся GPU-диапазоны в GLB');
        await reader.take(view.byteOffset-position,false);const bytes=await reader.take(view.byteLength);position=view.byteOffset+view.byteLength;
        if(action.type==='image'){
          const url=URL.createObjectURL(new Blob([bytes],{type:action.image.mimeType}));this.objectURLs.push(url);urls.set(action.image.name,url);
        }else if(action.type==='transforms'){
          this.setInstances(bytes.buffer);this.rasterInstanceBytes=bytes.byteLength;
          this.mergedTransforms=new Float32Array(bytes.buffer);
        }else{
          if(!materialsReady){
            const materials=data.materials.map(m=>({...m,texture:m.texture?urls.get(m.texture.split('/').at(-1)):null}));
            if(materials.some((m,i)=>data.materials[i].texture&&!m.texture))throw Error('В GLB не хватает встроенной текстуры');
            await loadCityMaterials(this,{materials},this.base);materialsReady=true;this.phase='Загружаем объединённую геометрию';
          }
          if(bytes.byteLength>this.device.limits.maxBufferSize)throw Error('GPU не поддерживает размер буфера объединённой сцены');
          const begun=performance.now(),kind=action.type,usage=kind==='vertex'?GPUBufferUsage.VERTEX:GPUBufferUsage.INDEX;
          if(kind==='vertex'){this.waterHeights.add(action.draw.id,bytes,data.materials,action.draw.instanced);this.groundHeights.add(action.draw.id,bytes,data.materials,action.draw.instanced);}
          const descriptor=this.mergedPlan?.descriptors.get(action.draw.id),offset=descriptor?descriptor[kind]*4:0;
          if(this.mergedRecords&&await sha256(bytes)!==this.mergedRecords.get(action.draw.id)[kind+'Sha256'])throw Error('Геометрия не совпадает с ускорителем: '+action.draw.name);
          const buffer=descriptor?this.mergedArenas[descriptor.page]:this.device.createBuffer({label:`Merged ${kind} ${action.draw.id}`,size:bytes.byteLength,usage:usage|GPUBufferUsage.STORAGE|GPUBufferUsage.COPY_DST});
          this.device.queue.writeBuffer(buffer,offset,bytes);uploadMs+=performance.now()-begun;
          let mesh=this.rasterMeshes.get(action.draw.id);if(!mesh){mesh={...action.draw};this.rasterMeshes.set(mesh.id,mesh);}mesh[kind]=buffer;mesh[kind+'Offset']=offset;
          this.streamStats.residentBytes+=bytes.byteLength;
          // Keep the upload queue bounded as well as decoded CPU memory.
          if(kind==='index')await this.device.queue.onSubmittedWorkDone();
        }
      }
      await reader.take(binaryLength-position,false);
      if(reader.bytes!==expectedStreamBytes)throw Error('Размер сцены не совпадает с заголовком');
      await reader.finish();
      await this.device.queue.onSubmittedWorkDone();
      this.chunks=[...this.rasterMeshes.values()];
      if(this.visibilityMetadata){this.fenceVisibility=new MergedFenceVisibility(this);await this.fenceVisibility.init(this.visibilityMetadata);}
      this.stats.geometryBytes=this.streamStats.residentBytes+this.rasterInstanceBytes+(this.fenceVisibility?.buffers.reduce((n,b)=>n+b.size,0)??0);this.stats.bvhBytes=this.mergedPlan?[...this.mergedPlan.records.values()].reduce((n,d)=>n+d.nodeBytes,0):0;
      this.streamStats.residentBytes=this.stats.geometryBytes+this.stats.bvhBytes;this.streamStats.peakResidentBytes=this.streamStats.residentBytes;this.streamStats.cpuCacheBytes=this.mergedTransforms.byteLength;
      this.stats.uploadMs=uploadMs;this.stats.buildMs=performance.now()-start;this.stats.bvhBuildMs=0;this.updateCounts();
      if(this.stats.triangles!==data.stats.expandedTriangles||this.stats.uniqueTriangles!==data.stats.uniqueTriangles)throw Error('Число треугольников GLB не совпало с проверенной сборкой');
      this.tileModes=new Map([['whole','full']]);this.streamStats.fullTiles=1;this.streamStats.coarseTiles=0;this.loading=false;this.progress=1;
    }catch(error){await reader.reader.cancel().catch(()=>{});throw error;}
    finally{this.objectURLs.forEach(url=>URL.revokeObjectURL(url));this.objectURLs=[];}
  }
  chooseTiles(){return new Map([['whole','full']]);}
  async prepareTrace(){
    if(this.mergedTraceReady)return;
    if(this.mergedTraceUnavailable)throw Error(this.mergedTraceUnavailable);
    if(!this.mergedPlan)throw Error('Для этого GLB ещё не подготовлен ускоритель merged/trace');
    this.ready=false;this.loading=true;this.phase='Ускоритель лучей · вся карта';this.progress=0;this.publish(true);
    const start=performance.now();await this.device.queue.onSubmittedWorkDone();
    for(const [i,c] of [...this.mergedPlan.records.values()].entries()){
      const response=await fetch(new URL('trace/'+c.file,this.modelURL));if(!response.ok)throw Error('Не найден ускоритель '+c.file);
      const compressed=await response.arrayBuffer();this.streamStats.requests++;this.streamStats.downloadBytes+=compressed.byteLength;
      const bytes=await new Response(new Blob([compressed]).stream().pipeThrough(new DecompressionStream('gzip'))).arrayBuffer();
      if(bytes.byteLength!==c.indexBytes+c.nodeBytes||await sha256(bytes)!==c.sha256)throw Error('Повреждён ускоритель '+c.file);
      const d=this.mergedPlan.descriptors.get(c.id);
      // Reordered indices are valid for raster too; both engines share vertices.
      this.device.queue.writeBuffer(this.mergedArenas[d.page],d.index*4,bytes);
      await this.device.queue.onSubmittedWorkDone();this.progress=(i+1)/this.chunks.length;this.publish(true);
    }
    this.phase='Иерархия всех объектов и инстансов';this.publish(true);
    this.tracer.pages=this.mergedArenas;this.rebuildMergedScene();
    this.stats.bvhBuildMs=performance.now()-start;this.mergedTraceReady=true;
  }
  rebuildMergedScene(){
    const assets=new Map([...this.mergedPlan.records.values()].map(c=>[c.id,c]));
    const scene=traceScene(mergedInstances(this.chunks.filter(c=>this.isChunkVisible(c)),this.mergedTransforms),assets,this.mergedPlan.descriptors);
    const previous=this.traceSceneBytes??0;this.tracer.scene?.destroy();
    this.tracer.scene=this.device.createBuffer({label:'Whole GLB · visible instances TLAS',size:scene.byteLength,usage:GPUBufferUsage.STORAGE|GPUBufferUsage.COPY_DST});
    this.device.queue.writeBuffer(this.tracer.scene,0,scene);this.traceSceneBytes=scene.byteLength;
    this.stats.bvhBytes+=scene.byteLength-previous;this.streamStats.residentBytes+=scene.byteLength-previous;
    this.streamStats.peakResidentBytes=Math.max(this.streamStats.peakResidentBytes,this.streamStats.residentBytes);this.tracer.bind();
  }
  async updateTiles(){
    if(this.state.engine!=='raster')await this.prepareTrace();
    this.streamKey=JSON.stringify([this.state.engine==='raster'?'raster':'trace',[...this.tileModes]]);
    this.ready=true;this.loading=false;this.progress=1;this.publish(true);
  }
  releaseRaster(){
    this.fenceVisibility?.destroy();
    if(!this.mergedArenas)return super.releaseRaster();
    this.mergedArenas.forEach(b=>b.destroy());this.mergedArenas=[];this.rasterMeshes.clear();this.chunks=[];
    if(this.rasterInstanceBytes){this.instanceBuffer.destroy();this.rasterInstanceBytes=0;}
  }
  releaseTrace(){this.tracer.pages=[];this.tracer.scene?.destroy();this.tracer.scene=null;this.tracer.group=null;this.mergedTraceReady=false;this.traceSceneBytes=0;}
}
