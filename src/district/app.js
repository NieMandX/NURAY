import {DistrictRenderer} from './renderer.js?v=spp-5000-1';
const $=id=>document.getElementById(id);const number=n=>n.toLocaleString('ru-RU');
const mib=n=>`${(n/1048576).toFixed(1)} МиБ`;const milliseconds=n=>n===null||n===undefined?'—':`${n.toFixed(2)} мс`;
let busy=false,benchmarking=false,stopRequested=false;let triangles=1000000,scene='moscow';
function error(message){$('error').hidden=false;$('error').textContent=message;$('loading').hidden=true;console.error(message);}
const renderer=new DistrictRenderer($('district-scene'),s=>{
  $('resident').textContent=number(s.triangles);$('submitted').textContent=number(s.submitted);$('draws').textContent=s.draws;
  $('geometry-memory').textContent=mib(s.geometryBytes);$('texture-memory').textContent=mib(s.textureBytes);
  $('bvh-memory').textContent=mib(s.bvhBytes??0);$('bvh-build-time').textContent=s.engine==='raster'?'—':`${((s.bvhBuildMs??0)/1000).toFixed(2)} с`; $('trace-samples').textContent=`${s.samples} / ${s.sampleLimit} spp`;
  $('device-status').textContent=s.engine==='cascade'?'WebGPU · каскады':s.engine==='trace'?'WebGPU · наш трассировщик':'WebGPU · растеризация';
  $('cache-progress').textContent=renderer.state.indirect?`${s.cacheSamples} / ${s.cacheLimit}`:'выключен';
  $('cache-version').textContent=s.cacheVersion;
  $('cache-updates').textContent=s.cacheUpdates;
  $('cache-area').textContent=s.cacheSpan?`${s.cacheSpan} м`:'—';
  $('cache-time').textContent=s.timer?milliseconds(s.cacheMs):'недоступно';
  $('cache-memory').textContent=mib(s.cacheBytes??0);
  $('path-time').textContent=s.timer?milliseconds(s.pathMs||null):'недоступно';
  $('trace-batch').textContent=s.batch;
  $('reconstruction-status').hidden=!renderer.state.reconstruction;
  $('reconstruction-time').textContent=s.timer?milliseconds(s.reconstructionMs||null):'недоступно';
  $('guide-time').textContent=s.timer?milliseconds(s.guideMs||null):'недоступно';
  $('reconstruction-memory').textContent=mib(s.reconstructionBytes??0);
  $('accumulation-note').textContent=renderer.state.reconstruction?'новых сэмплов в этом ракурсе · история проверяется по поверхности':'камера сбрасывает накопление';
  $('cache-state').textContent=!renderer.state.indirect?'Непрямой свет выключен':s.cacheSamples>=s.cacheLimit?'Кэш готов · вращение камеры сохраняет его':'Прогрев кэша освещения…';
  $('build-time').textContent=`${(s.buildMs/1000).toFixed(2)} с`;$('upload-time').textContent=milliseconds(s.uploadMs);$('shadow-time').textContent=milliseconds(s.shadowMs);
  $('footer-triangles').textContent=number(s.triangles);$('footer-materials').textContent=s.materials;$('gpu-time').textContent=s.timer?milliseconds(s.gpu):'недоступно';
  $('fps').textContent=s.engine!=='raster'&&s.samples>=s.sampleLimit?'готово':s.ready?(1000/s.frameMs).toFixed(0):'—';$('resolution').textContent=`${s.width} × ${s.height}${s.resolutionLimited?' · лимит GPU':''}`;
  $('draws').textContent=s.engine!=='raster'?'compute':s.draws;$('shadow-time').textContent=s.engine!=='raster'?'лучевые':milliseconds(s.shadowMs);
  $('timer-note').textContent=s.timer?'Время GPU измерено timestamp-query; короткие проходы могут округляться браузером. FPS учитывает интервал кадров и ограничивается частотой экрана.':'GPU-таймер недоступен: сравнение покажет только интервалы кадров. Числа GPU не подменяются временем CPU.';
  if(s.loading){$('loading').hidden=false;$('load-label').textContent=`${s.phase??'Собираем'} · ${number(s.targetTriangles)} треугольников · ${Math.round(s.progress*100)}%`;$('load-progress').value=s.progress;$('cancel-load').hidden=false;}
  else if(s.ready){$('loading').hidden=true;$('cancel-load').hidden=true;}
},error);
function lock(value){busy=value;$('settings').disabled=value;$('benchmark').disabled=value||renderer.state.engine!=='raster'||scene==='moscow';}
function syncEngine(){
  const trace=renderer.state.engine!=='raster',cascade=renderer.state.engine==='cascade';$('cascade-status').hidden=!cascade;$('engine').value=renderer.state.engine;
  $('trace-controls').hidden=!trace;$('culling').disabled=trace;$('shadows').disabled=trace;
  document.querySelector('label[for="culling"]').hidden=trace;document.querySelector('label[for="shadows"]').hidden=trace;
  $('submitted-label').textContent=trace?'Доступно лучам':'Отправлено в кадре';
  $('engine-note').textContent=cascade?'Непрямой рассеянный свет из каскадов. Отражения и стекло — лучами. Экспериментальный режим.':trace?`Наш путь света: отражения, преломление и непрямой свет. Изображение уточняется до ${renderer.tracer.limit} spp.`:'Растеризация с PBR и картой теней. Быстрое сравнение геометрической нагрузки.';
  $('benchmark').disabled=busy||trace||scene==='moscow';$('benchmark-note').textContent=scene==='moscow'?'Счётчик памяти показывает уникальные сетки; доступные лучам треугольники учитывают все экземпляры.':trace?'Сравнение 6 вариантов доступно в режиме растеризации. Время одного сэмпла показано отдельно от обновления кэша и вывода.':'1 / 5 / 17 млн × 1 / 200 материалов. Камера фиксируется; отсечение отключается.';
  $('benchmark-results').hidden=trace||!$('results-body').children.length;
}
$('engine').onchange=async e=>{
  if(busy)return;
  const old=renderer.state.engine,next=e.target.value;renderer.state.engine=next;
  if(old!=='raster'&&next!=='raster'){renderer.tracer.reset();syncEngine();renderer.publish(true);return;}
  lock(true);renderer.ready=false;renderer.resize();syncEngine();
  try{await load(triangles);}catch(e){if(!stopRequested)error(e.message);}finally{lock(false);stopRequested=false;}
};
$('bvh-strategy').onchange=async e=>{
  if(busy)return;renderer.state.bvhStrategy=e.target.value;lock(true);
  try{await load(triangles);}catch(e){if(!stopRequested)error(e.message);}finally{lock(false);stopRequested=false;}
};
$('reconstruction').onchange=e=>{renderer.state.reconstruction=e.target.checked;renderer.tracer.reset();renderer.resize();renderer.publish(true);};
$('trace-quality').onchange=e=>{renderer.state.pixels=Number(e.target.value);renderer.resize();};
$('trace-limit').onchange=e=>{
  renderer.tracer.limit=Number(e.target.value);
  if(renderer.tracer.samples>renderer.tracer.limit)renderer.tracer.reset();
  syncEngine();renderer.publish(true);
};
$('trace-bounces').onchange=e=>{renderer.state.bounces=Number(e.target.value);};
$('glass-ior').onchange=e=>{renderer.state.ior=Number(e.target.value);};
$('indirect').onchange=e=>{renderer.state.indirect=e.target.checked;};
$('trace-restart').onclick=()=>renderer.tracer.reset();
$('cache-restart').onclick=()=>{renderer.tracer.cache.invalidate();renderer.tracer.reset();};
$('exposure').onchange=e=>{renderer.state.exposure=Number(e.target.value);};
$('scene-choice').onchange=async e=>{
  if(busy)return;scene=e.target.value;lock(true);syncScene();
  try{await load(triangles);$('exposure').value=String(renderer.state.exposure);}catch(e){if(!stopRequested)error(e.message);}finally{lock(false);stopRequested=false;}
};
function syncScene(){
  const city=scene==='moscow';$('synthetic-controls').hidden=city;$('synthetic-picks').hidden=city;$('city-picks').hidden=!city;$('city-note').hidden=!city;
  document.querySelector('label[for="glass-ior"]').hidden=city;
  document.querySelector('.scene-caption').textContent=city?'Москва-Сити · 5 × 5 км · 2GIS':'48 домов · живая геометрия';
  $('focus-title').textContent=city?'Рассмотреть сцену':'Рассмотреть материал';$('view-label').textContent='Общий план';syncEngine();
}
for(const b of document.querySelectorAll('[data-city-focus]'))b.onclick=()=>{renderer.focus(Number(b.dataset.cityFocus));$('view-label').textContent=b.textContent;};
function sync(){
  for(const b of document.querySelectorAll('[data-triangles]'))b.setAttribute('aria-pressed',Number(b.dataset.triangles)===triangles);
  $('material-count').value=String(renderer.state.materials);$('culling').checked=renderer.state.culling;
}
async function load(count){
  triangles=count;sync();$('error').hidden=true;
  document.querySelector('.loader').hidden=false;$('load-progress').hidden=false;$('loading').hidden=false;$('load-label').textContent='Подготавливаем геометрию…';
  await renderer.load(scene==='moscow'?'moscow':count);
  sync();
  if(scene==='moscow'){
    const city=renderer.city;
    $('city-note').textContent=`Реальная геометрия 2GIS из Blender. ${city.materials.length} PBR-материалов, оригинальные текстуры фасадов и ${number(city.stats.streetInstances)} экземпляров городских объектов.`;
    $('city-summary').textContent=`${city.name} из исходного Blender-проекта 2GIS. ${(city.stats.uniqueTriangles/1e6).toFixed(2)} млн уникальных треугольников, ${(city.stats.expandedTriangles/1e6).toFixed(2)} млн с учётом экземпляров. Геометрия не упрощена. Деревья и городские объекты используют общие сетки.`;
  }
}
for(const b of document.querySelectorAll('[data-triangles]'))b.onclick=async()=>{
  if(busy)return;lock(true);
  try{await load(Number(b.dataset.triangles));}catch(e){if(!stopRequested)error(e.message);}finally{lock(false);stopRequested=false;}
};
$('material-count').onchange=async e=>{
  lock(true);try{await renderer.setMaterials(Number(e.target.value));}catch(e){error(e.message);}finally{lock(false);}
};
for(const key of ['textures','culling','shadows'])$(key).onchange=e=>{renderer.state[key]=e.target.checked;if(key==='shadows')renderer.shadowDirty=true;renderer.revision++;renderer.gpu=null;};
function overview(){renderer.resetCamera();$('view-label').textContent='Общий план';document.querySelectorAll('[data-focus]').forEach(b=>b.setAttribute('aria-pressed','false'));}
$('overview').onclick=overview;
for(const b of document.querySelectorAll('[data-focus]'))b.onclick=()=>{
  renderer.focus(Number(b.dataset.focus),b.dataset.name);$('view-label').textContent=b.dataset.name;
  document.querySelectorAll('[data-focus]').forEach(other=>other.setAttribute('aria-pressed',other===b));
};
function cancel(){
  stopRequested=true;renderer.cancelBuild();renderer.cancelMeasurement('Сравнение остановлено.');$('cancel-load').hidden=true;
  $('loading').hidden=renderer.ready;
  if(!renderer.ready){$('load-label').textContent='Сборка отменена. Выберите число треугольников, чтобы продолжить.';document.querySelector('.loader').hidden=true;$('load-progress').hidden=true;}
}
$('cancel-load').onclick=cancel;$('stop-benchmark').onclick=cancel;
$('benchmark').onclick=async()=>{
  if(busy)return;benchmarking=true;stopRequested=false;lock(true);$('results-body').replaceChildren();$('benchmark-results').hidden=false;$('stop-benchmark').hidden=false;
  const previousCulling=renderer.state.culling;renderer.state.culling=false;renderer.state.textures=true;renderer.state.shadows=true;$('textures').checked=true;$('shadows').checked=true;overview();
  let completed=0;
  try{
    for(const count of [1000000,5000000,17000000]){
      if(stopRequested)break;
      $('benchmark-note').textContent=`Готовим сцену ${count/1e6} млн…`;
      await load(count);
      for(const materials of [1,200]){
        if(stopRequested)break;
        await renderer.setMaterials(materials);sync();
        $('benchmark-note').textContent=`Замер ${++completed} / 6 · ${count/1e6} млн · ${materials} материалов`;
        const result=await renderer.measure();
        const row=document.createElement('tr');
        for(const text of [count/1e6,materials,result.gpu===null?'н/д':result.gpu.toFixed(2),result.frame.toFixed(2)]){const cell=document.createElement('td');cell.textContent=text;row.append(cell);}
        row.title=`${result.resolution}; ${number(result.submitted)} треугольников; ${mib(result.geometryBytes+result.textureBytes)} геометрии и материалов`;
        $('results-body').append(row);
      }
    }
    $('benchmark-note').textContent=stopRequested?'Сравнение остановлено.':`Готово · 6 замеров · ${renderer.canvas.width} × ${renderer.canvas.height} · отсечение выключено`;
  }catch(e){$('benchmark-note').textContent=stopRequested?'Сравнение остановлено.':e.message;}
  finally{benchmarking=false;lock(false);renderer.state.culling=previousCulling;sync();$('stop-benchmark').hidden=true;if(renderer.ready)$('loading').hidden=true;}
};
let drag=null;const canvas=$('district-scene');
canvas.addEventListener('pointerdown',e=>{if(busy)return;canvas.setPointerCapture(e.pointerId);drag={x:e.clientX,y:e.clientY};});
canvas.addEventListener('pointermove',e=>{
  if(!drag||busy)return;const dx=e.clientX-drag.x,dy=e.clientY-drag.y;const c=renderer.camera;
  if(e.shiftKey){const k=c.distance*.0015;c.target[0]-=(Math.cos(c.yaw)*dx+Math.sin(c.yaw)*dy)*k;c.target[2]-=(-Math.sin(c.yaw)*dx+Math.cos(c.yaw)*dy)*k;}
  else{c.yaw-=dx*.004;c.pitch=Math.max(.12,Math.min(1.45,c.pitch+dy*.004));}
  drag={x:e.clientX,y:e.clientY};
});
canvas.addEventListener('pointerup',()=>{drag=null;});canvas.addEventListener('pointercancel',()=>{drag=null;});
canvas.addEventListener('wheel',e=>{e.preventDefault();if(!busy)renderer.camera.distance=Math.max(scene==='moscow'?40:9,Math.min(scene==='moscow'?(renderer.city?.extentMetres??5000)*3:230,renderer.camera.distance*Math.exp(e.deltaY*.001)));},{passive:false});
canvas.addEventListener('keydown',e=>{
  if(busy)return;const c=renderer.camera;
  if(e.key==='ArrowLeft')c.yaw-=.05;else if(e.key==='ArrowRight')c.yaw+=.05;else if(e.key==='ArrowUp')c.pitch=Math.min(1.45,c.pitch+.05);else if(e.key==='ArrowDown')c.pitch=Math.max(.12,c.pitch-.05);else return;e.preventDefault();
});
window.addEventListener('pagehide',()=>renderer.dispose());
syncScene();lock(true);
try{await renderer.init();$('device-status').textContent='WebGPU · активен';await load(triangles);}
catch(e){error(e.message);}finally{lock(false);}
