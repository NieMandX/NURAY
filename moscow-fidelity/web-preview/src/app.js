import { Renderer } from './renderer.js';
const $=id=>document.getElementById(id);
const canvas=$('scene');
const controls=[['light-x','lightX',2],['light-y','lightY',2],['power','power',1],['ior','ior',2],['metal','metal',2],['stone','stone',2]];
function showError(message){$('loading').hidden=true;$('error').hidden=false;$('error').textContent=message;$('device-status').textContent='Ошибка WebGPU';console.error(message);}
const milliseconds=value=>value===undefined||value===null?'—':`${value.toFixed(2)} мс`;
const renderer=new Renderer(canvas,({samples,ms,width,height,state,gpu,timerAvailable,batch,cacheSamples,cacheLimit,cacheVersion,cacheUpdates})=>{
  $('loading').hidden=true;$('samples').textContent=samples.toLocaleString('ru');$('frame-time').textContent=timerAvailable?milliseconds(gpu?.total):'недоступно';$('resolution').textContent=`${width} × ${height}`;
  $('batch-size').textContent=`${batch}×`;
  $('gpu-note').textContent=timerAvailable?'Измерено на GPU. Авто подбирает пакет под бюджет 12 мс.':'GPU-таймер недоступен. Авто использует 1 сэмпл; пакет можно выбрать вручную.';
  for(const key of ['path','cascade','irradiance','display'])$(`gpu-${key}`).textContent=milliseconds(gpu?.[key]);
  $('present-time').textContent=milliseconds(ms);
  $('cache-count').textContent=`${cacheSamples} / ${cacheLimit}`;
  $('cache-revision').textContent=cacheVersion;$('cache-updates').textContent=cacheUpdates;
  $('cache-status').hidden=state.mode!==1;
  $('cache-status').textContent=!state.indirect?'Кэш не используется':state.animate?'Кэш обновляется вслед за светом':cacheSamples>=cacheLimit?'Свет накоплен · кэш используется повторно':`Накопление света · ${cacheSamples} / ${cacheLimit}`;
  if(state.animate){$('light-x').value=state.lightX;$('light-x-value').value=state.lightX.toFixed(2);}
},showError);
function sync(){
  const s=renderer.state;
  for(const [id,key,digits] of controls){$(id).value=s[key];$(`${id}-value`).value=s[key].toFixed(digits);}
  $('indirect').checked=s.indirect;$('animate').checked=s.animate;
  $('batch').value=String(s.batch);
  $('path-mode').setAttribute('aria-pressed',s.mode===0);$('cascade-mode').setAttribute('aria-pressed',s.mode===1);
  $('mode-label').textContent=s.mode===0?'Path tracing':'Каскады · эксперимент';
  $('mode-note').textContent=s.mode===0?'Многократные отражения и преломления.':'Первый диффузный отскок из проб. Приближение.';
}
for(const [id,key,digits] of controls){$(id).addEventListener('input',e=>{const value=Number(e.target.value);renderer.set(key,value);$(`${id}-value`).value=value.toFixed(digits);if(key==='lightX'){renderer.state.animate=false;$('animate').checked=false;}});}
for(const id of ['indirect','animate']){$(id).addEventListener('change',e=>renderer.set(id,e.target.checked));}
$('batch').addEventListener('change',e=>renderer.set('batch',Number(e.target.value)));
$('path-mode').addEventListener('click',()=>{renderer.set('mode',0);sync();});
$('cascade-mode').addEventListener('click',()=>{renderer.set('mode',1);sync();});
$('reset').addEventListener('click',()=>{renderer.reset();sync();});
let drag=null;
canvas.addEventListener('pointerdown',e=>{canvas.setPointerCapture(e.pointerId);drag={x:e.clientX,y:e.clientY,light:e.shiftKey};});
canvas.addEventListener('pointermove',e=>{
  if(!drag)return;const dx=e.clientX-drag.x,dy=e.clientY-drag.y;
  if(drag.light||e.shiftKey){renderer.state.lightX=Math.max(-1.7,Math.min(1.7,renderer.state.lightX+dx*0.012));renderer.state.lightY=Math.max(2.7,Math.min(4.05,renderer.state.lightY-dy*0.008));renderer.state.animate=false;sync();}
  else{renderer.state.yaw=Math.max(-0.43,Math.min(0.43,renderer.state.yaw-dx*0.003));renderer.state.pitch=Math.max(-0.02,Math.min(0.32,renderer.state.pitch+dy*0.003));}
  drag.x=e.clientX;drag.y=e.clientY;renderer.resetAccumulation();
});
function endDrag(){drag=null;}
canvas.addEventListener('pointerup',endDrag);canvas.addEventListener('pointercancel',endDrag);
canvas.addEventListener('wheel',e=>{e.preventDefault();renderer.state.distance=Math.max(7.0,Math.min(12.5,renderer.state.distance+e.deltaY*0.008));renderer.resetAccumulation();},{passive:false});
canvas.addEventListener('keydown',e=>{
  const step=e.shiftKey?0.10:0.025;
  if(e.key==='ArrowLeft')renderer.state.yaw-=step;else if(e.key==='ArrowRight')renderer.state.yaw+=step;else if(e.key==='ArrowUp')renderer.state.pitch+=step;else if(e.key==='ArrowDown')renderer.state.pitch-=step;else return;
  e.preventDefault();renderer.state.yaw=Math.max(-0.43,Math.min(0.43,renderer.state.yaw));renderer.state.pitch=Math.max(-0.02,Math.min(0.32,renderer.state.pitch));renderer.resetAccumulation();
});
window.addEventListener('pagehide',()=>renderer.dispose());
sync();
try{await renderer.init();$('device-status').textContent='WebGPU · активен';}catch(e){showError(e.message);}
