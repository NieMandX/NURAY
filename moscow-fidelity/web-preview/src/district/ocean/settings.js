import {VIEWER_DEFAULTS} from '../viewer-defaults.js?v=water-reflections-1';
// Time is independent of wall-clock time: pausing never jumps the waves.
export class WaterClock {
  constructor(){this.time=VIEWER_DEFAULTS.waterTime;this.last=null;this.playing=false;}
  tick(now,playing){
    const dt=this.last!==null&&this.playing&&playing?Math.min(.1,Math.max(0,(now-this.last)/1000)):0;
    this.last=now;this.playing=playing;this.time+=dt;return dt;
  }
}
export const WATER_DEFAULTS=VIEWER_DEFAULTS.water;
export const WATER_COLORS=[['absorptionColor','Цвет поглощения · вода'],['scatteringColor','Цвет мутности']];
export const WATER_CONTROLS=[
 ['Свет и тени','sunIntensity','Интенсивность солнца',0,300,5,'%'],
 ['Свет и тени','shadowStrength','Темнота солнечных теней',0,200,5,'%'],
 ['Небо · Hosek–Wilkie','hwTurbidity','Мутность атмосферы · Turbidity',1,10,.1,''],
 ['Небо · Hosek–Wilkie','hwAlbedo','Отражение земли · Albedo',0,1,.01,''],
 ['Небо · Hosek–Wilkie','hwExposure','Экспозиция неба и сцены',.1,4,.05,''],
 ['Небо · Hosek–Wilkie','hwSkyIntensity','Интенсивность света неба',0,300,5,'%'],
 ['Волны','windSpeed','Скорость ветра',2,20,.1,'м/с'],
 ['Волны','windDir','Направление ветра',0,360,1,'°'],
 ['Волны','fetchKm','Разгон ветра',5,800,1,'км'],
 ['Волны','swellHs','Высота зыби',0,4,.05,'м'],
 ['Волны','swellLength','Длина зыби',30,300,1,'м'],
 ['Волны','swellDir','Направление зыби',0,360,1,'°'],
 ['Волны','choppy','Острота волн',0,1.6,.01,''],
 ['Оптика воды','turbidity','Мутность воды',0,3,.01,''],
 ['Оптика воды','attenuationDistance','Дистанция затухания',.1,100,.1,'м'],
 ['Оптика воды','waterIOR','IOR воды',1,2.5,.001,''],
 ['Вода и пена','foam','Пена на волнах',0,3,.01,''],
 ['Вода и пена','shoreFoam','Пена у берега',0,2,.01,''],
 ['Отражения геометрии','reflectionQuality','Разрешение отражения',25,100,25,'%'],
 ['Отражения геометрии','reflectionStrength','Сила отражения',0,100,1,'%'],
 ['Отражения геометрии','reflectionBlur','Размытие отражения',0,8,.1,''],
 ['Отражения геометрии','reflectionDistortion','Искажение волнами',0,3,.05,''],
];
export function cleanWaterSettings(raw={},defaults=WATER_DEFAULTS){
 if(!raw||typeof raw!=="object")raw={};
 const p={...defaults};for(const [,key,,min,max] of WATER_CONTROLS)if(typeof raw[key]==='number'&&Number.isFinite(raw[key]))p[key]=Math.min(max,Math.max(min,raw[key]));
 for(const [key] of WATER_COLORS)if(typeof raw[key]==='string'&&/^#[0-9a-f]{6}$/i.test(raw[key]))p[key]=raw[key].toLowerCase();
 if(typeof raw.animated==='boolean')p.animated=raw.animated;
 for(const key of ['reflectionEnabled','reflectionDetail'])if(typeof raw[key]==='boolean')p[key]=raw[key];
 if(['classic','hosek'].includes(raw.lighting))p.lighting=raw.lighting;
 p.waterModel='ocean'; // The sole supported water model.
 return p;
}
export function waterFrameKey(o){return JSON.stringify([o.revision,o.camera,o.sun,o.sunPower,o.waterSettings,o.state,o.chunks.length,o.stats.geometryBytes,o.canvas.width,o.canvas.height]);}
