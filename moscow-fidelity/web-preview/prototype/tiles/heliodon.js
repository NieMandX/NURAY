import {calendarDate,localClock,solarPosition,daylight,clockLabel} from './solar-position.js?v=moscow-defaults-1';
export function sceneGeography(data,configured){
 if(configured)return configured;
 if(data.geography)return data.geography;
 // The current regional builder uses a local transverse Mercator centred on the site.
 const lat=Number(data.crsProj?.match(/\+lat_0=([-\d.]+)/)?.[1]),lon=Number(data.crsProj?.match(/\+lon_0=([-\d.]+)/)?.[1]);
 if(data.regionName==='Санкт-Петербург'&&Number.isFinite(lat)&&lat>50&&Number.isFinite(lon))return {latitude:lat,longitude:lon,timeZone:'Europe/Moscow',utcOffset:3,label:data.regionName};
 return null;
}
export function installHeliodon(renderer,geo,onChange,preset={}){
 const $=id=>document.getElementById(id),panel=$('heliodon');
 if(!geo){$('sun-status').textContent='Нет координат участка';return;}
 const now=new Date(),date=$('sun-date'),time=$('sun-time');let range,desiredTime=localClock(now,geo.timeZone);
 date.value=calendarDate(now,geo.timeZone);time.value=desiredTime;
 let restored=false;
 if(/^\d{4}-\d{2}-\d{2}$/.test(preset.date||'')&&Number.isFinite(preset.minute)&&preset.minute>=0&&preset.minute<=1440){
  date.value=preset.date;
  if(date.value){desiredTime=preset.minute;restored=true;}else date.value=calendarDate(now,geo.timeZone);
 }
 const refreshDate=()=>{
  range=daylight(date.value,geo);time.min=Math.ceil(range.rise);time.max=Math.floor(range.set);time.disabled=range.polar==='night';
  time.value=Math.max(Number(time.min),Math.min(Number(time.max),desiredTime));
  $('sun-rise').textContent=range.polar==='day'?'Полярный день':range.polar==='night'?'Полярная ночь':`Восход ${clockLabel(range.rise)}`;
  $('sun-set').textContent=range.polar?'':`Закат ${clockLabel(range.set)}`;
 };
 const update=()=>{
  const solar=solarPosition(date.value,Number(time.value),geo);renderer.sun=solar.direction;renderer.shadowDirty=true;
  const t=Math.max(0,Math.min(1,solar.altitude/5));renderer.sunPower=t*t*(3-2*t);
  $('sun-hour').textContent=clockLabel(Number(time.value));time.setAttribute('aria-valuetext',`${clockLabel(Number(time.value))}, высота солнца ${solar.altitude.toFixed(1)}°`);
  $('sun-status').textContent=`${geo.label} · UTC${geo.utcOffset>=0?'+':''}${geo.utcOffset} · азимут ${solar.azimuth.toFixed(0)}° · высота ${solar.altitude.toFixed(1)}°`;
  panel.dataset.solar=JSON.stringify({date:date.value,minute:Number(time.value),...solar,geo});onChange();
 };
 date.addEventListener('change',()=>{if(!date.value||!date.validity.valid)return;refreshDate();update();});
 let scheduled=false;time.addEventListener('input',()=>{desiredTime=Number(time.value);if(scheduled)return;scheduled=true;requestAnimationFrame(()=>{scheduled=false;update();});});
 $('sun-today').onclick=()=>{date.value=calendarDate(new Date(),geo.timeZone);desiredTime=localClock(new Date(),geo.timeZone);refreshDate();if(desiredTime<range.rise||desiredTime>range.set)time.value=Math.round((range.rise+range.set)/2);desiredTime=Number(time.value);update();};
 refreshDate();
 // At night open at solar-day midpoint, keeping today's date and a useful daylight view.
 const minute=localClock(now,geo.timeZone);if(!restored&&(minute<range.rise||minute>range.set))time.value=Math.round((range.rise+range.set)/2);
 desiredTime=Number(time.value);panel.disabled=false;update();
}
