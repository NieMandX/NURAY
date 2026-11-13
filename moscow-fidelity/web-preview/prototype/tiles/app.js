import {installSceneLayers} from './scene-layers.js?v=scene-layers-1';
import {installWaterPanel} from './water-panel.js?v=kursk-water-1';
import {installHeliodon,sceneGeography} from './heliodon.js?v=moscow-defaults-1';
import {MergedGlbRenderer} from './merged-glb-renderer.js?v=gs-11';
import {TileRenderer} from './tile-renderer.js?v=gs-11';
import {WebGLTileRenderer} from './webgl-renderer.js?v=gs-11';
import {areaTileIds,hydrateAreas,installAreaPicker,drawAreaOutline} from './manual-areas.js?v=manual-areas-1';
import {bindCameraInput} from './camera-input.js?v=moscow-defaults-1';
import {createStatsPanel} from './viewer-stats.js?v=gs-11';
import {viewerDefaults,catalogKey,defaultSunPreset} from '../../src/district/viewer-defaults.js?v=kursk-water-1';
import {readAssetJSON} from '../../src/district/asset-fetch.js?v=asset-delivery-1';
const $=id=>document.getElementById(id),showStats=createStatsPanel();
const mergedMode=new URLSearchParams(location.search).get('layout')==='merged';
let manualMode=new URLSearchParams(location.search).get('layout')==='sectors';
let canvas=$('scene'),renderer;
let initialized=false,pending=false,draining=false,layerChanging=false,debounce,currentDrain=Promise.resolve();
function fail(message){$('error').hidden=false;$('error').textContent=message;$('loading').hidden=true;$('retry').hidden=false;console.error(message);}
function report(s){
  const st=renderer.streamStats;canvas.dataset.camera=JSON.stringify(renderer.camera);
  if(mergedMode)$('stats-scope').textContent='Счётчики относятся к включённым объектам всей карты. Рейтрейс учитывает их и вне кадра; отключённые объекты не видны лучам.';
  if(manualMode){canvas.dataset.selectedTiles=JSON.stringify([...(renderer.manualTiles??[])]);drawAreaOutline(renderer);}
  canvas.dataset.sceneLayers=JSON.stringify(renderer.sceneLayers);
  canvas.dataset.residency=JSON.stringify({modes:[...renderer.tileModes],bytes:st.residentBytes,released:st.releasedGpuBytes,revision:renderer.revision,gpuPages:renderer.mergedArenas?.length??renderer.tilePages.size,gpuPageLimit:renderer.pageLimit,wholeSceneTrace:!!renderer.mergedTraceReady});
  showStats(s,st);
  $('residency').textContent=mergedMode?`Единая сцена · ${renderer.tileset?.nodes??'—'} объекта · вся карта`:`250 × 250 м · подробно: ${st.fullTiles??0} · обзор: ${st.coarseTiles??0}${st.budgetLimited?' · лимит нагрузки':''}`;
  if(s.loading){const msg=`${s.phase} · ${Math.round(s.progress*100)}%`;$('loading').textContent=msg;$('activity').textContent=msg;}
  else if(initialized)$('activity').textContent=st.budgetLimited?(manualMode?'Лимит этого режима: показана часть выбранной территории. В WebGPU-растеризации она доступна полностью.':'Ограничение нагрузки: показаны ближайшие участки. Переместите камеру для подгрузки соседних.'):mergedMode?'Карта загружена целиком':manualMode?'Выбранные участки загружены. Остальная карта — по выбору.':'Участки загружены';
  for(const b of document.querySelectorAll('[data-tile]')){
    const mode=renderer.tileModes.get(b.dataset.tile);
    if(b.dataset.detail===(mode||''))continue;
    b.dataset.detail=mode||'';
    b.querySelector('small').textContent=mode==='full'?'Подробно':mode==='coarse'?'Обзор':'Ожидание';
  }
}
const views={
  overview:{yaw:.12,pitch:1.03,distance:710,target:[0,0,0]},
  buildings:{yaw:-.5,pitch:.58,distance:590,target:[-30,65,-205]},
  buildingSlope:{yaw:10.56075,pitch:.206,distance:102.90914,target:[196.1649918,5.674041,-394.79903]},
  courtyard:{yaw:1.484,pitch:.332,distance:176.81355,target:[285.805,4,-325.74056]},
  streetSwings:{yaw:-2.65,pitch:.5,distance:18,target:[275.492,-2.73269,-357.475]},
  vegetation:{yaw:.15,pitch:.7,distance:240,target:[350,0,-290]},
  vegetationClose:{yaw:2.15,pitch:1.12,distance:40,target:[348,4,-287]},
  landscape:{yaw:.12,pitch:1.14,distance:180,target:[392,5,-100]},
  fountainGreen:{yaw:6.56475,pitch:.476,distance:123.632,target:[204.731365,5.674041,-161.593467]},
  greenCurb:{yaw:.4,pitch:.75,distance:45,target:[391.973,-.915,-104.194]},
  railway:{yaw:.9,pitch:.82,distance:34,target:[200,-6.7,190]},
  railwayCurve:{yaw:-.6,pitch:.85,distance:65,target:[250,-3.6,527]},
  railwayEntry:{yaw:.678,pitch:.67,distance:66.30514724315945,target:[66.52168504264506,0,-371.0960860803684]},
  pedestrianPortal:{yaw:.45,pitch:.65,distance:29,target:[251,-3.4,-47]},
  railwayPortal:{yaw:3.25,pitch:.6,distance:37,target:[82,-5,-125]},
  nw:{yaw:.12,pitch:1.15,distance:180,target:[-125,0,-125]},ne:{yaw:.12,pitch:1.15,distance:180,target:[125,0,-125]},
  sw:{yaw:.12,pitch:1.15,distance:180,target:[-125,0,125]},se:{yaw:.12,pitch:1.15,distance:180,target:[125,0,125]},
  center:{yaw:.2,pitch:1.18,distance:150,target:[0,0,0]},
  seam:{yaw:.3,pitch:.62,distance:75,target:[0,1.5,-5]},
  entry:{yaw:-1.05,pitch:.28,distance:31,target:[81.614,-2.407,3.360]},
  descentJoin:{yaw:.663555921538755,pitch:.422,distance:48,target:[239.7,-5.12,90.49]},
  rampContext:{yaw:-5.619629385640831,pitch:.422,distance:243.98028325671973,target:[156.6472928019499,0,-20.094273294466376]},
  tunnelWalls:{yaw:.663555921538755,pitch:.55,distance:75,target:[239.7,-5.12,90.49]},
  pedestrian:{yaw:-5.151629385640837,pitch:.584,distance:89.4755,target:[156.6472928019499,0,-20.094273294466376]},
  stopPaint:{yaw:.42,pitch:.88,distance:108,target:[144,0,-18]},
  crackMain:{yaw:.3,pitch:.55,distance:30,target:[-45.24155,1.6,-13.35367]},
  crackLocal:{yaw:2.570370614359168,pitch:.08,distance:8.41857081436576,target:[42.40180911369523,0,168.13779004027322]},
};
function moved(){renderer.revision++;renderer.gpu=null;renderer.tracer.reset();renderer.publish(true);schedule();}
function schedule({immediate=false}={}){
  if(!initialized)return;clearTimeout(debounce);
  if(immediate){pending=true;void drain();}else debounce=setTimeout(()=>{pending=true;void drain();},140);
}
function drain(){if(draining||layerChanging)return currentDrain;currentDrain=drainTiles();return currentDrain;}
async function drainTiles(){
  draining=true;$('engine').disabled=true;
  try{
    while(pending&&!layerChanging){pending=false;
      const modes=renderer.chooseTiles({full:$('streaming').value==='full'});
      await renderer.updateTiles(modes);
    }
  }catch(e){renderer.loading=false;fail(e.message);$('activity').textContent='Ошибка загрузки';}
  finally{draining=false;$('engine').disabled=false;renderer.publish(true);}
}
async function applySceneLayers(value){
  layerChanging=true;$('settings').disabled=true;
  try{await currentDrain;await renderer.setSceneLayers(value);}
  finally{layerChanging=false;$('settings').disabled=false;if(pending)void drain();}
}
$('engine').onchange=()=>{
  const engine=$('engine').value;
  renderer.ready=false;renderer.state.engine=engine;
  if(!mergedMode&&!manualMode&&engine!=='raster')$('streaming').value='auto';
  renderer.syncWaterPanel?.();
  renderer.tracer.cache.invalidate();renderer.tracer.reset();
  // The trace/cascade switch shares geometry, but still resumes rendering.
  const key=JSON.stringify([renderer.state.engine==='raster'?'raster':'trace',[...renderer.tileModes]]);
  if(key===renderer.streamKey)renderer.ready=true;
  schedule({immediate:true});
};
$('contact-shadows').onchange=e=>{renderer.state.contactAO=e.target.checked;moved();};
$('sun-shadows').onchange=e=>{renderer.state.shadows=e.target.checked;renderer.shadowDirty=true;moved();};
$('quality').onchange=e=>{renderer.state.pixels=Number(e.target.value);renderer.resize();};
$('samples').onchange=e=>{renderer.tracer.limit=Number(e.target.value);renderer.tracer.reset();renderer.publish(true);};
$('streaming').onchange=()=>schedule({immediate:true});
$('area-boundary').onchange=()=>drawAreaOutline(renderer);
$('views').onclick=e=>{
  const b=e.target.closest('[data-view]');if(!b||!initialized)return;
  renderer.camera=b.dataset.view==='overview'&&renderer.backend==='webgl2'&&!manualMode
    ?renderer.overviewCamera(renderer.camera.target):structuredClone(views[b.dataset.view]);
  $('view-name').textContent=b.firstChild.textContent;
  document.querySelectorAll('[data-view]').forEach(v=>v.setAttribute('aria-pressed',v===b));moved();schedule({immediate:true});
};
$('backend').onchange=e=>{const url=new URL(location.href);url.searchParams.set('renderer',e.target.value);location.href=url.href;};
$('retry').onclick=()=>location.reload();
$('measure-scene').onclick=async()=>{
  const button=$('measure-scene'),output=$('benchmark-result');button.disabled=true;output.hidden=false;delete output.dataset.result;output.textContent='Замер: 8 кадров прогрева + 48 кадров. Камеру пока не двигать.';
  try{const result=await renderer.measure(48);const record={layout:mergedMode?'merged-glb':'tiles',camera:structuredClone(renderer.camera),...result};output.textContent=JSON.stringify(record,null,2);output.dataset.result=JSON.stringify(record);}
  catch(error){output.textContent=error.message;delete output.dataset.result;}
  finally{button.disabled=false;}
};
try{
  // Only this small configuration changes when assets move to cloud storage.
  const configURL=new URL('config.json',import.meta.url),response=await fetch(configURL,{cache:'no-store'});
  if(!response.ok)throw Error('Не найдена настройка источника сцены');
  const config=await response.json(),params=new URLSearchParams(location.search);
  const preview=params.get('catalog');
  if(preview){
    if(!/^assets[-a-z0-9]+\/tileset\.json$/.test(preview))throw Error('Неверный адрес локального каталога');
    config.catalog=preview;config.canonicalModel=preview.replace('tileset.json','canonical/full/model.glb');
  }
  if(!params.has('layout')&&config.manualCatalogs?.[config.catalog])manualMode=true;
  if(manualMode){
    const sectors=config.manualCatalogs?.[config.catalog];
    if(!sectors)throw Error('Для этой сцены выбор участков ещё не подготовлен');
    config.assetDelivery??={};
    config.assetDelivery[config.catalog]={...config.assetDelivery[config.catalog],...sectors};
  }
  // Mirrors are opt-in and replace only the compressed GLB, keeping the same
  // catalog identity, materials, visibility, presets and integrity checks.
  const mirrorKey=mergedMode?params.get('mirror'):null;
  const mirror=mirrorKey?config.mergedMirrors?.[config.catalog]?.[mirrorKey]:null;
  if(mirrorKey&&(!mirror||!config.assetDelivery?.[config.catalog]?.merged))throw Error('Для этой сцены зеркало GLB не настроено');
  const assetBase=config.assetBase?new URL(config.assetBase,configURL):configURL;
  const catalogURL=new URL(config.catalog,assetBase),validationURL=new URL(mergedMode?'merged/validation.json':'validation.json',catalogURL);
  $('catalog-link').href=catalogURL.href;$('validation-link').href=new URL((!mergedMode&&config.assetDelivery?.[config.catalog]?.validation?.url)||validationURL.href,catalogURL).href;
  if(mergedMode)config.canonicalModel=config.catalog.replace('tileset.json','merged/model.glb');
  if(config.canonicalModel)$('model-link').href=new URL(config.canonicalModel,assetBase).href;else $('model-link').hidden=true;
  const downloadDelivery=config.assetDelivery?.[config.catalog];
  if(downloadDelivery?.merged){
    const format=/\.gltf(?:\.gz)?(?:\?|$)/.test(downloadDelivery.merged.url)?'glTF':'GLB';
    $('model-link').hidden=false;
    $('model-link').href=new URL(downloadDelivery.merged.url,catalogURL).href;
    $('model-link').textContent=`Общий участок · ${format}`+(downloadDelivery.merged.encoding==='gzip'?' gzip':'');
    if(downloadDelivery.mergedBuffer){
      $('model-buffer-link').href=new URL(downloadDelivery.mergedBuffer.url,catalogURL).href;
      $('model-buffer-link').textContent='Буфер BIN'+(downloadDelivery.mergedBuffer.encoding==='gzip'?' gzip':'');
      $('model-buffer-link').hidden=false;
    }
  }
  if(manualMode){
    const delivery=config.assetDelivery?.[config.catalog];
    $('model-link').href=new URL(delivery?.merged?.url||'merged/model.gltf',catalogURL).href;$('model-link').textContent='Вся Москва · glTF'+(delivery?.merged?.encoding==='gzip'?' gzip':'');
    $('model-buffer-link').href=new URL(delivery?.mergedBuffer?.url||'merged/model.bin',catalogURL).href;$('model-buffer-link').textContent='Буфер BIN'+(delivery?.mergedBuffer?.encoding==='gzip'?' gzip':'');$('model-buffer-link').hidden=false;
  }
  readAssetJSON((!mergedMode&&config.assetDelivery?.[config.catalog]?.validation)||{url:validationURL.href,cache:'no-cache'},catalogURL).then(r=>{
    if(mergedMode){$('validation').textContent=r.passed?`Единая сцена проверена: ${r.objects} объекта, ${r.gpuBatches} групп отрисовки. Атрибуты вершин и матрицы инстансов сохранены; геометрия не упрощена.`:'Проверка сцены выявила расхождения';return;}
    if(r.adapter==='yandex-2gis'){$('validation').textContent=r.passed?`Проверено ${r.chunks} блоков: контрольные суммы, BVH, материалы, сохранение геометрии и ${r.plantInstances.toLocaleString('ru-RU')} инстансов растений.`:'Проверка сцены выявила расхождения';return;}
    $('validation').textContent=r.passed?`Границы и BVH проверены. Максимальное расхождение шва: ${(r.seams.maxGapM*1000).toFixed(4)} мм. Все ${r.meshes} блоков сохраняют происхождение граней.${r.roadInterfaces?.passed?` Проверены ${r.roadInterfaces.interfaces} стыков дорожных и пешеходных поверхностей: поперечных бетонных препятствий нет.`:''}${r.roadSeams?.passed?` Проверены ${r.roadSeams.passages} сшитых дорожных проходов: поперечных бордюров и поднятой земли нет.`:''}`:'Проверка выявила расхождения — см. JSON';
    if(r.roadPaint?.passed)$('validation').textContent+=` Разметка проверена по полотну: ${r.roadPaint.trianglesChecked.toLocaleString('ru-RU')} граней, заступов на недорожные поверхности нет.`;
    if(r.transportClearance?.fullWidth?.passed){
      const t=r.transportClearance;
      $('validation').textContent+=` Проверена полная ширина ${t.source.interfaces} примыканий и ${t.source.corridorCount??t.source.corridors.length} открытых спусков: заступов бордюров, стенок и газонов нет.`;
    }
    if(r.tunnelWalls){
      const groups=r.tunnelWalls.groups??[],confirmed=groups.reduce((n,g)=>n+g.sourceMatchedBoundaryM,0),inferred=groups.reduce((n,g)=>n+g.fallbackBoundaryM,0);
      $('validation').textContent+=` Стенки: ${confirmed.toFixed(1)} м подтверждено исходными контурами; ${inferred.toFixed(1)} м границ без подтверждения, с восстановленной тонкой стенкой.`;
      const headers=groups.reduce((n,g)=>n+(g.portalHeaders?.count??0),0);
      if(headers)$('validation').textContent+=` Над ${headers} входами в подземную часть построены короткие перемычки; проходы под ними открыты.`;
    }
  }).catch(e=>{$('validation').textContent=e.message;});
  const alternate=new URL(location.href);if(mergedMode)alternate.searchParams.set('layout',config.manualCatalogs?.[config.catalog]?'sectors':'tiles');else{alternate.searchParams.set('layout','merged');alternate.searchParams.set('renderer','webgpu');}$('layout-link').href=alternate.href;$('layout-link').textContent=mergedMode&&config.manualCatalogs?.[config.catalog]?'Загрузить только выбранный сектор':mergedMode?'Открыть тайловую версию':'Открыть всю карту · большая загрузка';
  $('layout-link').hidden=!mergedMode;
  if(!mergedMode)fetch(new URL('merged/metadata.json',catalogURL),{method:'HEAD'}).then(r=>{$('layout-link').hidden=!r.ok;}).catch(()=>{});
  const approvedDefaults=viewerDefaults(config.catalog),defaults=approvedDefaults.display;
  const requestedBackend=params.get('renderer')||defaults.renderer;
  $('quality').value=String(defaults.pixels);$('samples').value=String(defaults.samples);
  $('contact-shadows').checked=defaults.contactAO;$('sun-shadows').checked=defaults.shadows;
  $('backend').value=['auto','webgpu','webgl2'].includes(requestedBackend)?requestedBackend:'auto';
  const touchDevice=matchMedia('(pointer: coarse)').matches||/iPad|iPhone|Android/.test(navigator.userAgent);
  const useGL=requestedBackend==='webgl2'||!navigator.gpu||(requestedBackend==='auto'&&touchDevice);
  if(mergedMode&&useGL)throw Error('Пробная цельная сцена требует WebGPU. Тайловая версия доступна по ссылке внизу.');
  renderer=mergedMode?new MergedGlbRenderer(canvas,report,fail):useGL?new WebGLTileRenderer(canvas,report,fail):new TileRenderer(canvas,report,fail);
  const requestedEngine=params.get('engine')??defaults.engine;
  renderer.state.engine=!useGL&&['trace','cascade'].includes(requestedEngine)?requestedEngine:'raster';
  $('engine').value=renderer.state.engine;
  if(!mergedMode&&(params.get('streaming')==='camera'||renderer.state.engine!=='raster'))$('streaming').value='auto';
  renderer.state.pixels=Number($('quality').value);renderer.tracer.limit=defaults.samples;
  renderer.state.contactAO=defaults.contactAO;renderer.state.shadows=defaults.shadows;
  let fallbackReason='';
  try{await renderer.init();}catch(e){
    if(useGL||mergedMode)throw e;
    fallbackReason=e.message;console.warn('WebGPU initialization failed:',fallbackReason);renderer.dispose();
    // A canvas cannot change context type after a WebGPU context was created.
    const replacement=canvas.cloneNode(false);canvas.replaceWith(replacement);canvas=replacement;
    renderer=new WebGLTileRenderer(canvas,report,fail);renderer.state.engine='raster';renderer.state.pixels=Number($('quality').value);
    await renderer.init();
  }
  const isGL=renderer.backend==='webgl2';$('engine').value=renderer.state.engine;$('measure-scene').hidden=isGL;canvas.dataset.backend=isGL?'webgl2':'webgpu';
  $('backend-note').textContent=isGL?`WebGL 2 · PBR · геометрия до ${renderer.geometryBudget/1048576} МиБ. Обзор окрестностей; весь участок можно исследовать перемещением камеры или выбором тайла. Общий план и рейтрейс — в WebGPU.${fallbackReason?` WebGPU недоступен — включён совместимый режим. Причина: ${fallbackReason}`:''}`:'WebGPU · PBR и рейтрейс';
  if(isGL){
    for(const option of $('engine').options)option.disabled=option.value!=='raster';
    $('samples').closest('label').hidden=true;
  }
  bindCameraInput(canvas,()=>renderer,()=>initialized,moved);
  if(!mergedMode&&config.meshPacks?.[config.catalog]){
    const p=await fetch(new URL(config.meshPacks[config.catalog],configURL));
    if(!p.ok)throw Error('Не найден индекс контейнера тайлов');
    renderer.meshPack=await p.json();
  }
  if(mergedMode&&config.visibilityMetadata?.[config.catalog])renderer.visibilityURL=new URL(config.visibilityMetadata[config.catalog],configURL);
  renderer.assetDelivery=config.assetDelivery?.[config.catalog];
  if(mirror)renderer.assetDelivery={...renderer.assetDelivery,merged:{...renderer.assetDelivery.merged,url:new URL(mirror.url,configURL).href}};
  await renderer.open(catalogURL);
  if(manualMode){
    renderer.manualTiles=areaTileIds(renderer.tileset.manualAreas);
    await hydrateAreas(renderer,renderer.manualTiles);
  }
  if(mergedMode&&renderer.modelURL){
    const delivery=renderer.assetDelivery;
    $('model-link').href=new URL(delivery?.merged?.url||renderer.modelURL.href,catalogURL).href;
    $('model-link').textContent='Общий участок · GLB'+(delivery?.merged?.encoding==='gzip'?' gzip':'');
    if(renderer.mergedFormat==='gltf'){
      $('model-link').href=new URL(delivery?.merged?.url||renderer.modelURL.href,catalogURL).href;
      $('model-link').textContent='Общий участок · glTF'+(delivery?.merged?.encoding==='gzip'?' gzip':'');
      $('model-buffer-link').href=new URL(delivery?.mergedBuffer?.url||new URL('model.bin',renderer.modelURL).href,catalogURL).href;
      $('model-buffer-link').textContent='Буфер BIN'+(delivery?.mergedBuffer?.encoding==='gzip'?' gzip':'');
      $('model-buffer-link').hidden=false;
    }
  }
  if(config.surfaceEffects?.[config.catalog])await renderer.loadSurfaceEffects(new URL(config.surfaceEffects[config.catalog],assetBase));
  const sourceGeo=sceneGeography(renderer.tileset,config.geography?.[config.catalog]);
  installWaterPanel(renderer,config.catalog,()=>{renderer.revision++;renderer.gpu=null;renderer.publish(true);});
  installHeliodon(renderer,sourceGeo,()=>{renderer.revision++;renderer.gpu=null;renderer.tracer.cache.invalidate();renderer.tracer.reset();renderer.publish(true);},defaultSunPreset(params,approvedDefaults));
  const data=renderer.tileset,ox=data.origin[0],oy=data.origin[1],bounds=data.boundsMSK;
  const target=[(bounds[0]+bounds[2])/2-ox,0,oy-(bounds[1]+bounds[3])/2];
  views.overview=isGL&&!manualMode?renderer.overviewCamera(target):{yaw:.12,pitch:1.03,distance:data.extentMetres*1.8,target};
  if(manualMode){
    const initial=data.manualAreas.initial,center=[initial.centerMSK[0]-ox,0,oy-initial.centerMSK[1]];
    views.overview={yaw:0,pitch:1.493,distance:initial.sizeM*1.48,target:center};
    views['selected-site']={yaw:-.35,pitch:.8,distance:650,target:center};
  }
  if(isGL)for(const button of document.querySelectorAll('[data-view="overview"]'))button.textContent='Обзор окрестностей';
  views.center.target=mergedMode?target:[bounds[0]+data.tileSizeM*Math.floor((data.grid?.columns??2)/2)-ox,0,oy-bounds[1]-data.tileSizeM*Math.floor((data.grid?.rows??2)/2)];
  const title=manualMode?'NURAY · Москва · сектор 3 × 3 км':data.radiusM?`NURAY · ${data.regionName} · радиус ${data.radiusM/1000} км`:`NURAY · ${data.extentMetres/1000} × ${data.extentMetres/1000} км`;
  document.title=title;$('region-title').textContent=title;
  const regionName=data.regionName||'Кутузовская',isMoscow=approvedDefaults.id.startsWith('moscow-');
  $('region-subtitle').textContent=mergedMode?`${regionName} · единая сцена · ${data.nodes} объекта`:`${regionName} · ${data.tiles.length} тайлов по ${data.tileSizeM} м`;
  if(manualMode){
    $('region-subtitle').textContent='Москва · начальный участок 3 × 3 км · доступно 10 × 10 км';
    $('streaming').disabled=true;$('streaming').value='full';$('streaming').selectedOptions[0].textContent='Только выбранные участки';
    $('streaming-note').textContent='При перемещении камеры остальная карта не загружается. Добавляйте участки на схеме выше. Общий план возвращает к начальному квадрату.';
    $('stats-scope').textContent='Счётчики относятся только к загруженным выбранным участкам.';
    $('backend-note').textContent=isGL?'WebGL 2 · выбранные участки с ограничением памяти устройства. Полная детализация выбранной территории — в WebGPU.':'WebGPU · выбранные участки. Свет, материалы, вода и инстансы сохранены.';
    installAreaPicker(renderer,async ids=>{
      layerChanging=true;$('settings').disabled=true;
      const previous=renderer.manualTiles;
      try{await currentDrain;await hydrateAreas(renderer,ids);renderer.manualTiles=ids;await renderer.updateTiles(renderer.chooseTiles());renderer.publish(true);}
      catch(e){renderer.manualTiles=previous;fail(e.message);throw e;}
      finally{layerChanging=false;$('settings').disabled=false;if(pending)void drain();}
    });
  }
  if(mirror)$('region-subtitle').textContent+=` · зеркало: ${mirror.label}`;
  if(mergedMode){$('streaming').disabled=true;$('streaming').value='full';$('streaming').selectedOptions[0].textContent='Вся карта · единая сцена';$('streaming-note').textContent='Вся карта загружается из объединённой геометрии. Деревья и городские предметы сохраняют общие модели и инстансы.';$('backend-note').textContent='WebGPU · объединённая карта. Растр, рейтрейс и каскады используют включённые объекты всей карты, включая объекты вне кадра.';$('objects-summary').textContent=`Статическая геометрия: 1 объект · общие модели: ${data.nodes-1} · инстансов: ${data.stats.sharedInstances.toLocaleString('ru-RU')}`;}
  if(mergedMode&&renderer.mergedTraceUnavailable){$('backend-note').textContent='WebGPU · вся карта в растеризации. '+renderer.mergedTraceUnavailable;for(const o of $('engine').options)if(o.value!=='raster')o.disabled=true;}
  canvas.setAttribute('aria-label',`Трёхмерная модель · ${regionName}`);
  if(!isMoscow){
    // Source-specific witnesses belong to their own region. Global navigation
    // and tile cameras below are derived from this catalog's metric bounds.
    for(const key of Object.keys(views))if(!['overview','center'].includes(key))delete views[key];
    for(const button of document.querySelectorAll('[data-view]')){
      if(!Object.hasOwn(views,button.dataset.view))button.remove();
      else if(button.dataset.view==='center')button.textContent='Центр участка';
    }
  }
  if(data.objectLayer){
    const o=data.objectLayer.stats;
    $('objects-summary').textContent=`Здания: ${o.buildingObjects} объектов · деревья и кустарники: ${o.vegetationInstances.toLocaleString('ru-RU')} · PBR-материалы: ${data.materials.length}`;
    if(data.objectLayer.foundations)$('objects-summary').textContent+=` · адаптивные цоколи: ${data.objectLayer.foundations.stats.supportedObjects}`;
    if(data.objectLayer.customLibrary){
      $('objects-summary').textContent+=` · моделей растительности: ${o.treeTemplates}`;
      $('vegetation-library-link').href=new URL(config.libraryPreview||'library/preview.png',config.libraryPreview?configURL:catalogURL).href;
      $('vegetation-library-link').textContent=`Библиотека растительности · ${o.treeTemplates} моделей`;
      $('vegetation-library-link').hidden=false;
    }
  }
  if(data.railwayLayer){
    const r=data.railwayLayer;
    $('objects-summary').textContent+=` · железная дорога: ${(r.stats.sourceLengthM/1000).toFixed(1)} км исходных осей`;
  }
  if(data.streetLayer){
    const s=data.streetLayer.stats;
    $('objects-summary').textContent+=` · городские предметы и ограды: ${s.objects} · моделей предметов: ${s.templates}`;
    if(data.streetLayer.fences){
      $('fence-library-link').href=new URL(config.fenceLibraryPreview||'fence-library/preview.png',config.fenceLibraryPreview?configURL:catalogURL).href;
      $('fence-library-link').hidden=false;
    }
    const group=document.createElement('div');group.className='views';group.style.marginBottom='12px';
    for(const view of data.streetLayer.witnessViews??[]){
      views[view.key]=view.camera;
      const button=document.createElement('button');button.dataset.view=view.key;button.textContent=view.label;group.append(button);
    }
    $('tile-grid').after(group);
  }
  if(regionName==='Санкт-Петербург'&&data.witnessViews?.['parking-asphalt-review']){
    data.witnessViews['vegetation-contact-review']={yaw:-.8,pitch:.5,distance:20,target:[678.3396,7.7953,260.3076]};
    data.witnessViews['contact-shadows-review']={yaw:-4.8653125,pitch:.764,distance:158.96537538,target:[626.95619194,7.88677683,276.77457352]};
  }
  const grid=$('tile-grid');grid.replaceChildren();if(mergedMode||manualMode)grid.style.display='none';grid.style.gridTemplateColumns=`repeat(${data.grid?.columns??2},1fr)`;
  if((data.grid?.columns??2)>8)grid.classList.add('compact');
  for(const tile of manualMode?[]:[...data.tiles].sort((a,b)=>b.north-a.north||a.east-b.east)){
    const key=`tile:${tile.id}`,button=document.createElement('button'),small=document.createElement('small');
    button.dataset.tile=tile.id;button.dataset.view=key;button.title=`Тайл ${tile.id}`;
    button.append(document.createTextNode(`${tile.east+1} · ${tile.north+1}`));small.textContent='Ожидание';button.append(small);grid.append(button);
    views[key]={yaw:.12,pitch:1.1,distance:260,target:[(tile.bounds.min[0]+tile.bounds.max[0])/2,0,(tile.bounds.min[2]+tile.bounds.max[2])/2]};
  }
  if(data.witnessViews?.['waterfront-review']){data.witnessViews['water-ripples-review']={...data.witnessViews['waterfront-review'],pitch:.50,distance:80};data.witnessViews['water-sky-review']={...data.witnessViews['waterfront-review'],pitch:.12,distance:180};}
  if(data.witnessViews){
    Object.assign(views,data.witnessViews);
    const labels={'water-sky-review':'Вода · небо и блики','water-ripples-review':'Вода · рябь и берег','vegetation-contact-review':'Растительность · контакт с землёй','contact-shadows-review':'Тени · здания и деревья','facade-bands-review':'Фасады · этажные пояса','parking-asphalt-review':'Парковки · светлый асфальт','waterfront-review':'Набережная · гранит','waterfront-parapet-review':'Набережная · каменный парапет','waterfront-bridge-review':'Вода · дорожный разрыв','flat-roof-review':'Крыша · парапет','pitched-roof-review':'Скатная кровля · матовый металл','paving-asphalt':'Покрытие · асфальт','paving-stone':'Покрытие · брусчатка','paving-gravel':'Покрытие · гравий','paving-sand':'Покрытие · песок','paving-wood':'Покрытие · настил'};
    Object.assign(labels,data.witnessViewLabels??{});
    const group=document.createElement('div');group.className='views';
    for(const [key,label] of Object.entries(labels))if(data.witnessViews[key]){const button=document.createElement('button');button.dataset.view=key;button.textContent=label;group.append(button);}
    $('tile-grid').after(group);
  }
  if(isMoscow&&config.inspectionViews?.length){
    const group=document.createElement('div');group.className='views';
    for(const view of config.inspectionViews){
      if((view.minExtentMetres??0)>data.extentMetres)continue;
      views[view.key]=view.camera;
      const button=document.createElement('button');button.dataset.view=view.key;button.textContent=view.label;group.append(button);
    }
    $('tile-grid').after(group);
  }
  const requestedView=params.get('view');
  if(manualMode){
    for(const b of document.querySelectorAll('[data-view]'))if(b.dataset.view!=='overview')b.hidden=true;
    const b=document.createElement('button');b.dataset.view='selected-site';b.textContent='Отмеченный участок · ближе';$('views').append(b);
  }
  const initialView=Object.hasOwn(views,requestedView)?requestedView:(isGL&&!manualMode?'center':'overview');
  renderer.camera=structuredClone(views[initialView]);
  const approvedCamera=!manualMode&&!requestedView&&!isGL&&approvedDefaults.scene.catalogs.includes(catalogKey(config.catalog));
  if(approvedCamera)renderer.camera=structuredClone(approvedDefaults.scene.camera);
  // A review link can preserve the exact user view while reloading shaders.
  try {
    const c=JSON.parse(params.get('camera')||'null');
    if(c&&Array.isArray(c.target)&&c.target.length===3&&[c.yaw,c.pitch,c.distance,...c.target].every(Number.isFinite)&&c.distance>0&&c.distance<1e6&&c.pitch>0&&c.pitch<Math.PI/2)
      renderer.camera={yaw:c.yaw,pitch:c.pitch,distance:c.distance,target:[...c.target]};
  } catch {}
  document.querySelectorAll('[data-view]').forEach(button=>{
    const selected=button.dataset.view===initialView;
    button.setAttribute('aria-pressed',selected);
    if(selected)$('view-name').textContent=button.firstChild.textContent;
  });
  if(approvedCamera)$('view-name').textContent='Сохранённый вид';
  await renderer.updateTiles(renderer.chooseTiles({full:$('streaming').value==='full'}));await installSceneLayers(renderer,config.catalog,applySceneLayers);
  if(params.get('instanceCulling')==='1')(await import('./main-instance-culling.js?v=gs-13')).installInstanceCulling(renderer);
  if(params.get('splats')==='1')await (await import('./gaussian-panel.js?v=gs-12')).installGaussianPanel(renderer,params.has('splatCatalog')?new URL(params.get('splatCatalog'),assetBase):undefined);
  initialized=true;$('measure-scene').disabled=false;$('settings').disabled=false;$('views').disabled=false;$('area-picker').disabled=false;$('loading').hidden=true;renderer.publish(true);
}catch(e){fail(e.message);}
window.addEventListener('pagehide',()=>renderer?.dispose(),{once:true});
document.addEventListener('visibilitychange',()=>renderer?.publish(true));
