import {DistrictRenderer} from '../src/district/renderer.js?v=dry-ground-1';
import {ENVIRONMENT_BRDF_WGSL} from '../src/district/environment-brdf.js?v=dry-ground-1';
import {loadCityMaterials} from '../src/district/city-materials.js?v=dry-ground-1';
import {orthographic,lookAt,multiply} from '../src/district/math.js';
import {DEFAULT_SETTINGS,normalizeSettings,buildGeometry,buildSurfaceGeometry,exportGLB} from './foliage-editor.js';
import {decodePackedGeometry,normalizeAngle,smoothFoliage} from './foliage-smoothing.js?v=exact-base-1';
import {normalizeColor,linearToColor,foliagePalette} from './foliage-color.js';
import {normalizeStrength,colorCurvature,workshopShader} from './foliage-curvature.js?v=shared-tint-1';
const $=id=>document.getElementById(id),canvas=$('scene');
const error=e=>{$('error').hidden=false;$('error').textContent=e?.message??String(e);$('status').textContent='Не удалось показать модель';};
class StudyRenderer extends DistrictRenderer{
  async init(){
    const result=await super.init(),response=await fetch(new URL('../src/district/district.wgsl',import.meta.url));
    if(!response.ok)throw Error('Не найден шейдер мастерской');
    const module=this.device.createShaderModule({label:'Foliage vertex shading',code:workshopShader(ENVIRONMENT_BRDF_WGSL+await response.text())});
    const errors=(await module.getCompilationInfo()).messages.filter(m=>m.type==='error');if(errors.length)throw Error(errors.map(e=>e.message).join('\n'));
    const attributes=[{shaderLocation:0,offset:0,format:'float32x3'},{shaderLocation:1,offset:12,format:'snorm16x2'},{shaderLocation:2,offset:16,format:'float32x2'},{shaderLocation:3,offset:24,format:'uint32'},{shaderLocation:4,offset:28,format:'float32'}];
    this.pipeline=await this.device.createRenderPipelineAsync({label:'Workshop PBR with curvature',layout:'auto',vertex:{module,entryPoint:'vertex',buffers:[{arrayStride:32,attributes}]},fragment:{module,entryPoint:'fragment',targets:[{format:this.format}]},primitive:{topology:'triangle-list',cullMode:'back'},depthStencil:{format:'depth32float',depthWriteEnabled:true,depthCompare:'greater'}});
    this.bindRaster();return result;
  }
  updatePalette(palette){
    palette.forEach((m,i)=>this.device.queue.writeBuffer(this.materialBuffer,i*48,new Float32Array(m.color)));
    this.revision++;
  }
  updateTree(geometry){
    const chunk=this.chunks[0];
    if(!chunk.editable||chunk.capacity<geometry.triangles){
      chunk.vertex.destroy();chunk.index.destroy();
      // Capacity is the full mesh; simplification only changes the draw count.
      const capacity=geometry.woodTriangles+geometry.baseFoliageTriangles;
      chunk.capacity=capacity;
      chunk.vertex=this.device.createBuffer({size:capacity*3*32,usage:GPUBufferUsage.VERTEX|GPUBufferUsage.COPY_DST});
      const ix=Uint32Array.from({length:capacity*3},(_,i)=>i);
      chunk.index=this.device.createBuffer({size:ix.byteLength,usage:GPUBufferUsage.INDEX,mappedAtCreation:true});
      new Uint32Array(chunk.index.getMappedRange()).set(ix);chunk.index.unmap();chunk.editable=true;
    }
    this.device.queue.writeBuffer(chunk.vertex,0,geometry.words);
    Object.assign(chunk,{triangles:geometry.triangles,vertexCount:geometry.vertexCount,bounds:geometry.bounds});
    const h=geometry.bounds.max[1];this.shadowMatrix=multiply(orthographic(h*1.1,.1,h*6),lookAt(this.sun.map((v,i)=>v*h*2+(i===1?h*.4:0)),[0,h*.4,0]));
    this.stats.triangles=geometry.triangles;this.stats.vertices=geometry.vertexCount;this.shadowDirty=true;this.revision++;this.publish(true);
  }
  async open(url){
    this.ready=false;this.loading=true;this.revision++;
    const response=await fetch(url,{cache:'no-store'});if(!response.ok)throw Error('Не найдена модель');const scene=await response.json();
    await this.device.queue.onSubmittedWorkDone();
    this.chunks.forEach(c=>{c.vertex.destroy();c.index.destroy();});this.chunks=[];
    const ground={name:'Фон',color:[.53,.52,.47],roughness:1,metallic:0,ior:1.5,kind:1,alphaCutoff:0,texture:null};
    await loadCityMaterials(this,{...scene,materials:[...scene.materials,ground]},new URL('.',url));
    // The workshop can edit foliage colors without rebuilding textures or geometry.
    const materialData=new Float32Array((scene.materials.length+1)*12);
    [...scene.materials,ground].forEach((m,i)=>materialData.set([...m.color,m.roughness,m.metallic,m.ior,m.kind,m.alphaCutoff,1,1,0,0],i*12));
    this.materialBuffer.destroy();
    this.materialBuffer=this.device.createBuffer({size:materialData.byteLength,usage:GPUBufferUsage.STORAGE|GPUBufferUsage.COPY_DST,mappedAtCreation:true});
    new Float32Array(this.materialBuffer.getMappedRange()).set(materialData);this.materialBuffer.unmap();this.bindRaster();this.tracer.bind();
    const chunk=scene.chunks[0],rawResponse=await fetch(new URL(chunk.file,url),{cache:'no-store'});
    if(!rawResponse.ok)throw Error('Не найдена геометрия');
    const raw=await new Response(rawResponse.body.pipeThrough(new DecompressionStream('gzip'))).arrayBuffer();
    const upload=(data,usage)=>{const b=this.device.createBuffer({size:data.byteLength,usage,mappedAtCreation:true});new Uint8Array(b.getMappedRange()).set(new Uint8Array(data));b.unmap();return b;};
    this.chunks.push({...chunk,vertex:upload(raw.slice(0,chunk.vertexBytes),GPUBufferUsage.VERTEX),index:upload(raw.slice(chunk.vertexBytes),GPUBufferUsage.INDEX),instanceFirst:0,instanceCount:1});
    const size=400,points=[[-size,-.035,-size],[size,-.035,size],[size,-.035,-size],[-size,-.035,size]],words=new Uint32Array(4*8),floats=new Float32Array(words.buffer);
    points.forEach((p,i)=>{floats.set(p,i*8);words[i*8+3]=32767<<16;words[i*8+6]=(0x80000000|scene.materials.length)>>>0;});
    const indices=new Uint32Array([0,1,2,0,3,1]);
    this.chunks.push({id:1,triangles:2,bounds:{min:[-size,-.04,-size],max:[size,0,size]},vertex:upload(words.buffer,GPUBufferUsage.VERTEX),index:upload(indices.buffer,GPUBufferUsage.INDEX),instanceFirst:0,instanceCount:1});
    const h=chunk.bounds.max[1];this.shadowMatrix=multiply(orthographic(h*1.1,.1,h*6),lookAt(this.sun.map((v,i)=>v*h*2+(i===1?h*.4:0)),[0,h*.4,0]));
    this.stats.triangles=chunk.triangles;this.stats.vertices=chunk.vertexCount;this.loading=false;this.ready=true;this.shadowDirty=true;this.publish(true);
    return {geometry:decodePackedGeometry(raw,chunk),materials:scene.materials};
  }
}
const renderer=new StudyRenderer(canvas,()=>{canvas.dataset.camera=JSON.stringify(renderer.camera);},error);
renderer.state.engine='raster';renderer.state.pixels=0;renderer.state.exposure=.85;renderer.state.textures=false;
let catalog,optimization,choices={},current,loading=false,drag;
let editorData,editorActive=false,editorSettings={...DEFAULT_SETTINGS},editedGeometry,editFrame=0;
let baseGeometry,shownGeometry,shownMaterials,smoothingAngle=0,smoothingKey,shadingFrame=0,currentVariant;
let appearance={models:{}},sourceMaterials,foliageColor,colorKey,defaultColor;
let curvatureStrength=45,curvatureKey;
let booleanWorker,booleanSource,booleanSurface,booleanBusy=false,booleanMode=false,workerEpoch=0,workerId=0,workerRequest;
const settingKeys=Object.keys(DEFAULT_SETTINGS),number=n=>n.toLocaleString('ru-RU');
const editableModels=new Set(['birch','open','spruce','thuja','growth','low','bush']),editorCache=new Map();
function applyShading(){
  if(!baseGeometry)return;
  shownGeometry=colorCurvature(smoothFoliage(baseGeometry,smoothingAngle),shownMaterials,curvatureStrength);renderer.updateTree(shownGeometry);
  $('smooth-angle').value=smoothingAngle;$('value-smooth-angle').textContent=`${smoothingAngle}°`;
  $('curvature-strength').value=curvatureStrength;$('value-curvature-strength').textContent=`${curvatureStrength}%`;
  shownGeometry={...shownGeometry,extras:{...shownGeometry.extras,foliageColor,colorSpace:'srgb'}};
  $('download').textContent='Модель с текущими настройками · GLB';
  canvas.dataset.shading=JSON.stringify({model:current.id,variant:currentVariant,angle:smoothingAngle,triangles:shownGeometry.triangles});
}
function applyColor(){
  shownMaterials=foliagePalette(sourceMaterials,foliageColor);renderer.updatePalette(shownMaterials);
  $('foliage-color').value=$('foliage-hex').value=foliageColor;
  $('foliage-hex').setCustomValidity('');$('foliage-hex').removeAttribute('aria-invalid');
  canvas.dataset.appearance=JSON.stringify({model:current.id,foliageColor,curvatureStrength});
}
function changeColor(value){
  if(loading||!sourceMaterials)return;
  const color=normalizeColor(value);
  if(!color){$('foliage-hex').setCustomValidity('Введите цвет в формате #RRGGBB');$('foliage-hex').setAttribute('aria-invalid','true');return;}
  foliageColor=color;applyColor();applyShading();
  try{localStorage.setItem(colorKey,color);}catch{}
}
$('foliage-color').oninput=e=>changeColor(e.target.value);
$('foliage-hex').oninput=e=>changeColor(e.target.value);
$('color-reset').onclick=()=>changeColor(defaultColor);
$('curvature-strength').oninput=e=>{
  if(loading||!baseGeometry)return;
  curvatureStrength=normalizeStrength(e.target.value);applyColor();applyShading();
  try{localStorage.setItem(curvatureKey,String(curvatureStrength));}catch{}
};
$('smooth-angle').oninput=e=>{
  if(loading||!baseGeometry)return;
  smoothingAngle=normalizeAngle(e.target.value);$('value-smooth-angle').textContent=`${smoothingAngle}°`;
  try{localStorage.setItem(smoothingKey,String(smoothingAngle));}catch{}
  if(!shadingFrame)shadingFrame=requestAnimationFrame(()=>{shadingFrame=0;try{applyShading();}catch(e){error(e);}});
};
function storageKey(){return `nuray-${editorData.model}-editor:`+editorData.baseGeometrySha256;}
async function loadEditor(id){
  if(!editorCache.has(id)){
    const response=await fetch(new URL(`./assets/${id}/editor.json.gz`,import.meta.url),{cache:'no-store'});
    if(!response.ok)throw Error('Не найдены фрагменты выбранного дерева');
    const data=await new Response(response.body.pipeThrough(new DecompressionStream('gzip'))).json();
    if(data.model!==id)throw Error('Фрагменты не соответствуют выбранному дереву');
    editorCache.set(id,{...data,label:current.label});
  }
  editorData=editorCache.get(id);
  const selected=choices[id],initial=selected?.sourceGeometrySha256===editorData.baseGeometrySha256?selected.settings:DEFAULT_SETTINGS;
  try{editorSettings=normalizeSettings(JSON.parse(localStorage.getItem(storageKey())??JSON.stringify(initial)));}catch{editorSettings=normalizeSettings(initial);}
  editorSettings.optimize=100;
}
function clearBoolean(){
  workerEpoch++;booleanWorker?.terminate();booleanWorker=null;
  workerRequest?.reject(Error('Расчёт отменён'));workerRequest=null;
  booleanSource=booleanSurface=null;booleanBusy=booleanMode=false;editorSettings.optimize=100;
}
function booleanCall(type,args){
  if(!booleanWorker){
    booleanWorker=new Worker(new URL('./boolean-worker.js',import.meta.url),{type:'module'});
    booleanWorker.onmessage=({data})=>{
      if(data.id!==workerRequest?.id)return;
      const request=workerRequest;workerRequest=null;data.error?request.reject(Error(data.error)):request.resolve(data.surface);
    };
    booleanWorker.onerror=e=>{workerRequest?.reject(Error(e.message||'Не удалось выполнить Boolean'));workerRequest=null;};
  }
  return new Promise((resolve,reject)=>{const id=++workerId;workerRequest={id,resolve,reject};booleanWorker.postMessage({id,type,...args});});
}
function syncControls(){
  for(const key of settingKeys){
    const value=editorSettings[key];$('edit-'+key).value=value;
    $('value-'+key).textContent=`${value}%`+(key==='optimize'?` · ×${(value/100).toLocaleString('ru-RU')}`:key.startsWith('r')?` · до ${Math.round(value*3.6)}°`:'');
  }
  const {rx,ry,rz}=editorSettings,same=rx===ry&&ry===rz;
  $('edit-all').value=same?rx:Math.round((rx+ry+rz)/3);
  $('value-all').textContent=same?`${rx}% · до ${Math.round(rx*3.6)}°`:'Раздельно';
  $('edit-all').setAttribute('aria-valuetext',same?`${rx}%`:'Оси настроены отдельно');
  $('boolean-build').disabled=booleanBusy;
  $('boolean-build').textContent=booleanSource?'Показать оболочку · 100%':'Построить Boolean-оболочку';
  $('boolean-fragments').hidden=!booleanMode;
  $('boolean-fragments').disabled=booleanBusy;
  $('edit-optimize').disabled=!booleanMode;
  $('download').setAttribute('aria-disabled',String(booleanBusy));
}
function applyEdit(){
  if(!editorActive)return;
  editedGeometry=booleanMode&&booleanSurface?buildSurfaceGeometry(editorData,booleanSurface,booleanSurface.settings):buildGeometry(editorData,{...editorSettings,optimize:100});
  baseGeometry=editedGeometry;applyShading();
  const g=editedGeometry;
  $('facts').textContent=`${number(g.triangles)} треугольников · листва ${number(g.foliageTriangles)} · ствол и ветви ${number(g.woodTriangles)} · высота ${(g.bounds.max[1]-g.bounds.min[1]).toFixed(1)} м`;
  $('edit-count').textContent=booleanMode?
    `Листва: фрагменты ${number(booleanSource.originalFoliageTriangles)} → Boolean ${number(g.baseFoliageTriangles)} → сейчас ${number(g.foliageTriangles)}. Всего: ${number(g.triangles)}.`:
    `Исходная листва: ${number(g.foliageTriangles)} треугольников. Постройте оболочку, чтобы включить её упрощение.`;
  $('variant').textContent=booleanMode?(g.settings.optimize===100?'Boolean-оболочка · без упрощения':`Boolean-оболочка · упрощение ×${g.settings.optimize/100}`):'Фрагменты · настройка листвы';
  canvas.dataset.editor=JSON.stringify({model:g.model,settings:g.settings,mode:g.mode,triangles:g.triangles,foliageTriangles:g.foliageTriangles,baseFoliageTriangles:g.baseFoliageTriangles,woodTriangles:g.woodTriangles});
  try{localStorage.setItem(storageKey(),JSON.stringify(editorSettings));$('edit-save').textContent='Настройки сохраняются в этом браузере.';}
  catch{$('edit-save').textContent='Автосохранение недоступно. Скачайте выбранную модель GLB.';}
}
async function simplifyBoolean(){
  if(booleanBusy||!booleanMode||!booleanSource)return;
  const epoch=workerEpoch,optimize=editorSettings.optimize;
  booleanBusy=true;syncControls();$('boolean-status').textContent='Упрощаем Boolean-оболочку…';
  try{
    const result=optimize===100?booleanSource:await booleanCall('simplify',{optimize});
    if(epoch!==workerEpoch)return;
    if(optimize===editorSettings.optimize){booleanSurface=result;applyEdit();$('boolean-status').textContent='Boolean-оболочка готова · замкнутая сетка';}
  }catch(e){
    if(epoch!==workerEpoch)return;
    editorSettings.optimize=booleanSurface.settings.optimize;$('boolean-status').textContent=`Упрощение не применено: ${e.message}`;
  }finally{
    if(epoch===workerEpoch){booleanBusy=false;syncControls();if(editorSettings.optimize!==booleanSurface.settings.optimize)void simplifyBoolean();}
  }
}
function queueEdit(){if(!editFrame)editFrame=requestAnimationFrame(()=>{editFrame=0;try{if(booleanMode)void simplifyBoolean();else applyEdit();}catch(e){error(e);}});}
for(const key of [...settingKeys,'all'])$('edit-'+key).oninput=e=>{
  if(!editorActive)return;
  const value=Number(e.target.value);
  if(key!=='optimize'){clearBoolean();$('boolean-status').textContent='Форма изменена. Постройте оболочку заново.';}
  if(key==='all')editorSettings.rx=editorSettings.ry=editorSettings.rz=value;else editorSettings[key]=value;
  syncControls();queueEdit();
};
$('boolean-build').onclick=async()=>{
  if(!editorActive||booleanBusy)return;
  if(booleanSource){booleanMode=true;booleanSurface=booleanSource;editorSettings.optimize=100;syncControls();applyEdit();$('boolean-status').textContent='Boolean-оболочка готова · без упрощения';return;}
  const epoch=workerEpoch;
  booleanBusy=true;syncControls();$('boolean-status').textContent='Объединяем листву, удаляем внутренние грани…';
  try{
    const surface=await booleanCall('build',{editor:editorData,settings:editorSettings});
    if(epoch!==workerEpoch)return;
    booleanSource=booleanSurface=surface;booleanMode=true;editorSettings.optimize=100;applyEdit();
    $('boolean-status').textContent='Boolean-оболочка готова · замкнутая сетка';
  }catch(e){if(epoch===workerEpoch)$('boolean-status').textContent=`Не удалось построить оболочку: ${e.message}`;}
  finally{if(epoch===workerEpoch){booleanBusy=false;syncControls();}}
};
$('boolean-fragments').onclick=()=>{
  if(booleanBusy)return;
  booleanMode=false;editorSettings.optimize=100;syncControls();applyEdit();$('boolean-status').textContent='Показаны исходные фрагменты. Оболочка сохранена для сравнения.';
};
$('edit-reset').onclick=()=>{clearBoolean();editorSettings={...DEFAULT_SETTINGS};syncControls();$('boolean-status').textContent='Сначала настройте листву, затем постройте оболочку.';queueEdit();};
$('download').onclick=e=>{
  if(loading||booleanBusy||editFrame||shadingFrame){e.preventDefault();return;}
  e.preventDefault();if(editorActive)applyEdit();else applyShading();
  const url=URL.createObjectURL(new Blob([exportGLB(shownGeometry,shownMaterials)],{type:'model/gltf-binary'}));
  const suffix=editorActive?(booleanMode?'boolean':'edited'):currentVariant;
  const link=document.createElement('a');link.href=url;link.download=`NURAY-${current.id}-${suffix}${smoothingAngle?'-smooth-'+smoothingAngle:''}.glb`;link.click();setTimeout(()=>URL.revokeObjectURL(url),30000);
};
function frameModel(){const b=current.sourceBounds;renderer.camera={yaw:.62,pitch:.16,distance:(b.max[1]-b.min[1])*1.65,target:[0,(b.max[1]+b.min[1])*.5,0]};}
async function select(id,reset=true,preferred){
  if(loading)return;loading=true;$('version').disabled=true;
  editorActive=false;$('editor').hidden=true;delete canvas.dataset.editor;
  $('shading').hidden=true;baseGeometry=shownGeometry=null;delete canvas.dataset.shading;
  $('color-controls').hidden=true;delete canvas.dataset.appearance;
  if(shadingFrame){cancelAnimationFrame(shadingFrame);shadingFrame=0;}
  clearBoolean();$('boolean-status').textContent='Сначала настройте листву, затем постройте оболочку.';
  if(editFrame){cancelAnimationFrame(editFrame);editFrame=0;}
  document.querySelectorAll('#models button').forEach(b=>{b.disabled=true;b.setAttribute('aria-pressed',b.dataset.model===id);});
  current=catalog.models.find(m=>m.id===id);
  const versions=[{value:'new',folder:id,label:current.studyLabel??'Исходная · листва +20%',triangles:current.triangles,bounds:current.bounds,
    description:current.description+' '+(current.scaleDescription??'Фрагменты листвы и хвои увеличены на 20%; стволы и ветви прежние.')},...(current.comparisons??[])];
  if(id===optimization?.source){
    for(const value of ['compact-union',optimization.selectedVariant,...(optimization.reductionSteps?.variants??[])]){
      const v=optimization.variants.find(v=>v.id===value);
      if(v)versions.push({...v,value:v.id,folder:v.id,label:v.stage?`${v.label} · ${v.triangles}`:v.id==='compact-union'?'Внешняя оболочка':'Оболочка + упрощение'});
    }
  }
  const accepted=choices[id];
  if(accepted?.folder&&!versions.some(v=>v.value===accepted.variant)){
    versions.push({...accepted,value:accepted.variant});
  }
  versions.push({value:'previous',folder:id+'-previous',label:'Старая форма · до эскиза',triangles:current.previousTriangles,bounds:current.previousBounds,
    description:'Прежняя геометрия до работы по эскизу, при том же освещении, в той же палитре и с той же камерой.'});
  for(const v of versions)if(v.value===choices[id]?.variant)v.label+=' · выбрано';
  const selected=versions.find(v=>v.value===(preferred??choices[id]?.variant))??versions[0];
  $('version').replaceChildren(...versions.map(v=>new Option(v.label,v.value,false,v===selected)));
  $('name').textContent=current.label;$('variant').textContent=selected.label;$('description').textContent=selected.description;
  $('optimization-link').hidden=id!==optimization?.source;
  $('status').textContent='Загружаем модель…';
  try{
    if(reset)frameModel();
    const url=new URL(`./assets/${selected.folder}/scene.json`,import.meta.url);
    const loaded=await renderer.open(url);sourceMaterials=loaded.materials;currentVariant=selected.value;
    defaultColor=appearance.models[id]?.foliageColor??current.defaultFoliageColor??linearToColor(sourceMaterials[0].color);
    colorKey=`nuray-foliage-color:v${appearance.version??1}:${id}`;
    curvatureKey=`nuray-foliage-curvature:v1:${id}`;
    try{foliageColor=normalizeColor(localStorage.getItem(colorKey))??defaultColor;}catch{foliageColor=defaultColor;}
    try{curvatureStrength=normalizeStrength(localStorage.getItem(curvatureKey)??appearance.models[id]?.curvatureStrength??current.defaultCurvatureStrength??45);}catch{curvatureStrength=current.defaultCurvatureStrength??45;}
    applyColor();$('color-controls').hidden=false;
    baseGeometry={...loaded.geometry,model:id,label:current.label,settings:selected.settings,mode:selected.mode??'saved',
      extras:{sourceVariant:selected.value,trunkCorrection:selected.trunkCorrection}};
    smoothingKey=`nuray-foliage-smoothing:${id}:${selected.folder}:${selected.geometrySha256??''}`;
    const acceptedAngle=selected.value===accepted?.variant?accepted.smoothingAngle??0:selected.value==='new'?current.defaultSmoothingAngle??0:0;
    try{smoothingAngle=normalizeAngle(localStorage.getItem(smoothingKey)??acceptedAngle);}catch{smoothingAngle=acceptedAngle;}
    $('shading').hidden=false;
    const count=selected.triangles,b=selected.bounds,referenceCount=selected.stage?optimization.reductionSteps.baseTriangles:current.triangles,change=(count/referenceCount-1)*100;
    $('facts').textContent=`${count.toLocaleString('ru-RU')} треугольников · высота ${(b.max[1]-b.min[1]).toFixed(1)} м`+
      (selected.value.startsWith('compact-')?` · ${change>0?'+':''}${change.toFixed(1)}% ${selected.stage?'от версии '+referenceCount.toLocaleString('ru-RU'):'к исходной'}`:'');
    $('download').href=new URL('model.glb',url);
    document.querySelector('.note').textContent=(accepted?.integrated&&selected.value===accepted.variant
      ?'Утверждённая версия этого растения подключена к городскому макету. Изменения в мастерской сохраняются отдельно. '
      :'Это проба для настройки и согласования формы. ')+
      'Масштаб опирается на шаблоны 2ГИС; здесь показана модель до масштаба конкретного растения.';
    $('download').textContent='Выбранная модель · GLB';
    if(editableModels.has(id)&&selected.value==='new'){
      await loadEditor(id);editorActive=true;$('editor').hidden=false;
      $('editor').setAttribute('aria-label','Настройка листвы: '+current.label);
      syncControls();applyEdit();
      $('download').textContent='Модель с текущими настройками · GLB';
    }else applyShading();
    const pageURL=new URL(location.href);pageURL.searchParams.set('model',id);pageURL.searchParams.set('variant',selected.value);history.replaceState(null,'',pageURL);
    $('status').textContent='Модель готова';
  }catch(e){error(e);}finally{loading=false;$('version').disabled=false;document.querySelectorAll('#models button').forEach(b=>b.disabled=false);}
}
$('models').onclick=e=>{const b=e.target.closest('[data-model]');if(b)void select(b.dataset.model);};
$('version').onchange=()=>void select(current.id,false,$('version').value);
$('views').onclick=e=>{const b=e.target.closest('[data-yaw]');if(!b||!current)return;renderer.camera.yaw=Number(b.dataset.yaw);renderer.camera.pitch=.10;renderer.revision++;};
canvas.onpointerdown=e=>{if(loading)return;canvas.setPointerCapture(e.pointerId);drag=[e.clientX,e.clientY];};
canvas.onpointerup=canvas.onpointercancel=canvas.onlostpointercapture=()=>drag=null;
canvas.onpointermove=e=>{if(!drag)return;if(!e.buttons){drag=null;return;}renderer.camera.yaw-=(e.clientX-drag[0])*.006;renderer.camera.pitch=Math.max(-.02,Math.min(1.3,renderer.camera.pitch+(e.clientY-drag[1])*.006));drag=[e.clientX,e.clientY];renderer.revision++;};
canvas.addEventListener('wheel',e=>{e.preventDefault();renderer.camera.distance=Math.max(4,Math.min(130,renderer.camera.distance*Math.exp(e.deltaY*.001)));renderer.revision++;},{passive:false});
try{
  const response=await fetch(new URL('./assets/catalog.json',import.meta.url),{cache:'no-store'});if(!response.ok)throw Error('Каталог не найден');catalog=await response.json();
  const optimizationResponse=await fetch(new URL('./assets/optimization.json',import.meta.url));
  if(optimizationResponse.ok)optimization=await optimizationResponse.json();
  const choicesResponse=await fetch(new URL('./assets/choices.json',import.meta.url),{cache:'no-store'});
  if(choicesResponse.ok)choices=await choicesResponse.json();
  const appearanceResponse=await fetch(new URL('./assets/appearance.json',import.meta.url),{cache:'no-store'});
  if(appearanceResponse.ok)appearance=await appearanceResponse.json();
  for(const [i,m] of catalog.models.entries()){const b=document.createElement('button');b.dataset.model=m.id;b.textContent=`0${i+1} / ${m.label}`;b.disabled=true;$('models').appendChild(b);}
  const params=new URLSearchParams(location.search),initial=catalog.models.find(m=>m.id===params.get('model'))??catalog.models[0];
  await renderer.init();await select(initial.id,true,params.get('variant')||undefined);
}catch(e){error(e);}
