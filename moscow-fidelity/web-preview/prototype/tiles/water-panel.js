import {WATER_CONTROLS,WATER_COLORS,cleanWaterSettings} from '../../src/district/ocean/settings.js?v=moscow-defaults-1';
import {viewerDefaults,catalogKey} from '../../src/district/viewer-defaults.js?v=moscow-defaults-1';
export function installWaterPanel(renderer,catalog,onChange){
 // A new approved baseline must not be masked by old experimental browser settings.
 // Later edits are still remembered; earlier keys are retained, not deleted.
 const defaults=viewerDefaults(catalog);
 const $=id=>document.getElementById(id),key=`nuray-water:${defaults.id}:${catalogKey(catalog)}`;
 let saved={};try{saved=JSON.parse(localStorage.getItem(key)||'{}');}catch{}
 renderer.waterSettings=cleanWaterSettings(saved,defaults.water);
 renderer.waterClock.time=defaults.waterTime;renderer.waterClock.last=null;renderer.waterClock.playing=false;
 if(Number.isFinite(saved?.waterTime)&&saved.waterTime>=0&&saved.waterTime<1e8)renderer.waterClock.time=saved.waterTime;
 const panel=$('water-panel'),toggle=$('water-toggle'),fields=$('water-fields'),lighting=$('lighting-model');
 fields.replaceChildren();const controls={};let fieldset,group;
 for(const [section,name,label,min,max,step,unit] of WATER_CONTROLS){
  if(group!==section){fieldset=document.createElement('fieldset');const legend=document.createElement('legend');legend.textContent=section;fieldset.append(legend);fields.append(fieldset);group=section;}
  const row=document.createElement('label'),head=document.createElement('span'),title=document.createElement('span'),out=document.createElement('output'),input=document.createElement('input');
  title.textContent=label;head.className='water-label';head.append(title,out);
  Object.assign(input,{id:'water-'+name,type:'range',min,max,step,value:renderer.waterSettings[name]});input.setAttribute('aria-label',label);out.htmlFor=input.id;
  const update=()=>{input.value=renderer.waterSettings[name];out.textContent=Number(input.value).toLocaleString('ru-RU',{maximumFractionDigits:3})+(unit?' '+unit:'');};update();
  controls[name]={input,row,update};input.addEventListener('input',()=>{renderer.waterSettings[name]=Number(input.value);update();changed();});row.append(head,input);fieldset.append(row);
 }
 const optics=[...fields.children].find(f=>f.querySelector('legend').textContent==='Оптика воды');
 for(const [name,label] of WATER_COLORS){
  const row=document.createElement('label'),title=document.createElement('span'),line=document.createElement('span'),input=document.createElement('input'),hex=document.createElement('input');
  title.textContent=label;line.className='water-color';input.type='color';input.id='water-'+name;input.setAttribute('aria-label',label);
  Object.assign(hex,{type:'text',maxLength:7,spellcheck:false});hex.setAttribute('aria-label',label+' · HEX');
  const update=()=>{input.value=hex.value=renderer.waterSettings[name];hex.setCustomValidity('');};update();
  input.oninput=()=>{renderer.waterSettings[name]=input.value;update();changed();};
  hex.oninput=()=>{const value=hex.value.trim();if(/^#[0-9a-f]{6}$/i.test(value)){renderer.waterSettings[name]=value.toLowerCase();input.value=value;hex.setCustomValidity('');changed();}else hex.setCustomValidity('Введите цвет в формате #RRGGBB');};
  controls[name]={input,row,update};line.append(input,hex);row.append(title,line);optics.append(row);
 }
 const opticsNote=document.createElement('small');opticsNote.id='water-optics-note';optics.append(opticsNote);
 renderer.saveWaterSettings=()=>{try{localStorage.setItem(key,JSON.stringify({...renderer.waterSettings,waterTime:renderer.waterClock.time}));}catch{}};
 function changed(){renderer.saveWaterSettings();renderer.waterRevision=(renderer.waterRevision||0)+1;onChange();sync();}
 const play=$('water-play'),freeze=$('water-freeze');
 function sync(){
  const trace=renderer.state.engine!=='raster';
  opticsNote.textContent='Цвет поглощения — оттенок прошедшего света на заданной дистанции. Меньше метров — сильнее затухание. '+(trace?'Рейтрейс: преломление и затухание по длине луча в воде. Где в модели нет дна, глубина не подставляется.':'Растеризация: глубина оценивается по расстоянию до берега.');
  const p=renderer.waterSettings;
  play.setAttribute('aria-pressed',String(p.animated));freeze.setAttribute('aria-pressed',String(!p.animated));
  $('water-state').textContent=p.animated?'Вода анимируется':'Вода заморожена · ползунки работают';panel.dataset.settings=JSON.stringify(p);
  lighting.value=p.lighting;
  for(const [name,c] of Object.entries(controls)){
   c.row.hidden=name.startsWith('hw')&&p.lighting!=='hosek';
   c.input.disabled=c.row.hidden||(name==='bloom'&&(!!renderer.gl||trace))||(name==='shadowStrength'&&trace);c.input.title=name==='shadowStrength'&&trace?'В рейтрейсе тени рассчитываются лучами без искусственного затемнения':name==='bloom'&&(renderer.gl||trace)?'Свечение доступно в растеризации WebGPU':'';
  }
  for(const f of fields.children)f.hidden=![...f.querySelectorAll('label')].some(row=>!row.hidden);
  $('water-mode').textContent=renderer.gl?'Ocean · облегчённые волны WebGL':'Ocean · спектральные волны WebGPU';
  $('water-lighting-note').textContent=p.lighting==='hosek'?'Физическое дневное небо Hosek–Wilkie. Turbidity: 1 — чистый воздух, 10 — сильная дымка. Albedo: 0 — тёмная земля, 1 — светлая.':'Прежний свет NURAY. Направление солнца задаётся гелиодоном.';
  if(trace)$('water-lighting-note').textContent+=' Рейтрейс: отражения и тени рассчитываются лучами. Заморозьте воду для накопления сэмплов без размытия движения.';
  $('contact-shadows').disabled=trace;$('sun-shadows').disabled=trace;
 }
 lighting.disabled=false;
 lighting.onchange=()=>{renderer.waterSettings.lighting=lighting.value;changed();if(lighting.value==='hosek'){show(true);fields.scrollTop=0;controls.hwTurbidity.input.focus();}};
 play.onclick=()=>{renderer.waterSettings.animated=true;changed();};freeze.onclick=()=>{renderer.waterSettings.animated=false;changed();};
 $('water-reset').onclick=()=>{renderer.waterSettings={...defaults.water};renderer.waterClock.time=defaults.waterTime;renderer.waterClock.last=null;renderer.waterClock.playing=false;Object.values(controls).forEach(c=>c.update());changed();};
 function show(open){panel.hidden=!open;toggle.setAttribute('aria-expanded',String(open));if(open)$('water-close').focus();else toggle.focus();}
 toggle.onclick=()=>show(panel.hidden);$('water-close').onclick=()=>show(false);
 panel.addEventListener('keydown',e=>{if(e.key==='Escape'){show(false);e.stopPropagation();}});
 renderer.syncWaterPanel=sync;toggle.disabled=false;changed();
}
