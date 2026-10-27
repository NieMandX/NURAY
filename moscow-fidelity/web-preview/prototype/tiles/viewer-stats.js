const number=n=>Number.isFinite(n)?n.toLocaleString('ru-RU'):'—';
const ms=n=>Number.isFinite(n)?`${n.toFixed(2)} мс`:'—';
const seconds=n=>Number.isFinite(n)?`${(n/1000).toFixed(2)} с`:'—';
const mib=n=>Number.isFinite(n)?`${(n/1048576).toFixed(2)} МиБ`:'—';

export function statsText(s,stream){
  const trace=s.engine!=='raster',loaded=s.ready&&!s.loading;
  const measured=loaded&&s.frameMeasured;
  const complete=trace&&measured&&s.samples>=s.sampleLimit;
  const fps=!loaded?'—':s.tabHidden?'Пауза':s.waterFrozen&&!trace?'Стоп-кадр':complete?'Готово':measured&&s.frameMs>0?(1000/s.frameMs).toFixed(0):'—';
  const gpu=!s.timer?'н/д':measured?ms(s.gpu):'—';
  const submitted=measured?number(trace?s.triangles:s.submitted):'—';
  return {
    'fps':fps,'frame-time':measured&&!s.tabHidden&&!complete&&!s.waterFrozen?ms(s.frameMs):'—','gpu-time':gpu,
    'submitted-label':trace?'Доступно лучам':'Треугольников в кадре',
    'submitted':submitted,'draws':trace?'Compute':measured?number(s.draws):'—',
    'unique-triangles':number(s.uniqueTriangles),'triangles':number(s.triangles),
    'mesh-count':number(s.meshCount),'instance-count':number(s.sharedInstances),'materials-count':number(s.materials),
    'resolution':`${s.width} × ${s.height}${s.resolutionLimited?' · лимит GPU':''}`,
    'spp':trace?`${s.samples} / ${s.sampleLimit}`:'—',
    'path-time':trace&&s.timer&&measured&&Number.isFinite(s.gpu)?ms(s.pathMs):'—',
    'trace-batch':trace?number(s.batch):'—',
    'geometry-memory':mib(s.geometryBytes),'bvh-memory':mib(s.bvhBytes??0),'texture-memory':mib(s.textureBytes),'surface-memory':mib(s.surfaceEffectBytes??0),
    'ocean-memory':mib(s.oceanBytes??0),
    'memory':mib(stream.residentBytes),'peak':mib(stream.peakResidentBytes),'released':mib(stream.releasedGpuBytes),
    'cpu':mib(stream.cpuCacheBytes),'network':mib(stream.downloadBytes),'requests':`${stream.requests} / ${stream.cacheHits}`,
    'tile-count':`${stream.fullTiles??0} / ${stream.coarseTiles??0}`,
    'build-time':loaded?seconds(s.buildMs):'—','upload-time':loaded?ms(s.uploadMs):'—',
    'bvh-build-time':trace&&loaded?ms(s.bvhBuildMs):'—',
    'shadow-time':trace?'Лучевые':s.timer&&measured?ms(s.shadowMs):'—',
    'brief-fps':fps,'brief-gpu':gpu,'brief-submitted':submitted,
    'brief-submitted-label':trace?'Треугольники · лучам':'Треугольники · в кадре',
    'brief-draws':trace?'Compute':measured?number(s.draws):'—','brief-memory':mib(stream.residentBytes),
    'brief-resolution':`${s.width} × ${s.height}`,
    'timing-note':s.waterFrozen&&!trace?'Стоп-кадр: GPU показывает время последней отрисовки. Пока камера и настройки неподвижны, новые кадры не отправляются.':s.timer?'GPU — сумма измеренных проходов кадра. Интервал кадра включает ожидание браузера; это не время CPU.':'Измерение времени GPU недоступно в этом браузере. FPS и интервал кадра измеряются отдельно.',
  };
}

export function createStatsPanel(){
  const elements=new Map(),traceRows=document.getElementById('trace-stats');
  let lastUpdate=-Infinity,lastState='';
  return (s,stream)=>{
    // Camera changes can publish on every pointer event; keep the HUD lightweight.
    const state=`${s.engine}:${s.ready}:${s.loading}:${s.tabHidden}:${s.timer}:${s.waterFrozen}:${Number.isFinite(s.gpu)}:${s.frameMeasured}`,now=performance.now();
    if(state===lastState&&now-lastUpdate<200)return;
    lastState=state;lastUpdate=now;
    traceRows.hidden=s.engine==='raster';
    for(const [id,value] of Object.entries(statsText(s,stream))){
      if(!elements.has(id))elements.set(id,document.getElementById(id));
      const element=elements.get(id);
      if(element.textContent!==value)element.textContent=value;
    }
  };
}
