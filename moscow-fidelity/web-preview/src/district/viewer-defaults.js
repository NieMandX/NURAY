// Approved in the live Saint Petersburg viewer on 2026-10-24.
// Repository defaults also work in a new browser, without localStorage or a review URL.
export const VIEWER_DEFAULTS=Object.freeze({
  id:'approved-20261024-01',
  waterTime:43.217200000000034,
  water:Object.freeze({
    windSpeed:9.9,windDir:181,fetchKm:22,
    swellHs:1,swellLength:191,swellDir:196,swellSpread:48,choppy:.19,
    turbidity:.62,absorptionColor:'#8ac6d1',scatteringColor:'#2c3f36',
    attenuationDistance:4.4,waterIOR:1.4,
    foam:3,shoreFoam:2,haze:3,clouds:.4,veil:.36,exposure:1.2,bloom:.08,
    animated:false,lighting:'hosek',lightingMix:50,
    hwTurbidity:3,hwAlbedo:.2,hwExposure:2.55,hwSkyIntensity:180,
    sunIntensity:15,shadowStrength:100,waterModel:'ocean',
    groundReflectionEnabled:false,groundReflectionQuality:50,groundReflectionStrength:75,groundReflectionBlur:2,groundReflectionDetail:true,
    reflectionEnabled:false,reflectionQuality:50,reflectionStrength:100,reflectionBlur:1,reflectionDistortion:1,reflectionDetail:true,
    seaHeight:.6,seaFrequency:.16,seaChoppy:4,seaSpeed:.8,seaExposure:1,
  }),
  sun:Object.freeze({date:'2026-06-21',minute:1206}),
  display:Object.freeze({renderer:'webgpu',engine:'trace',pixels:0,samples:64,contactAO:true,shadows:true}),
  // The camera is local to this scene; never reuse these coordinates in another city.
  scene:Object.freeze({
    catalogs:Object.freeze(['assets-spb-10km-live-20261024-r13/tileset.json','assets-hosek-check/tileset.json']),
    layout:'merged',
    camera:Object.freeze({
      distance:3825.9007002412377,pitch:.7189999999999996,yaw:-40.0224675587353,
      target:Object.freeze([-2653.9375929093776,5.038,-2915.690550365216]),
    }),
  }),
});

// Approved Chrome water/light/reflection state: docs/moscow-approved-20261027-02.json.
// Kept independent from the Saint Petersburg baseline and previous local overrides.
export const MOSCOW_DEFAULTS=Object.freeze({
  id:'moscow-approved-20261027-02',
  waterTime:48.38810000000599,
  water:Object.freeze({...VIEWER_DEFAULTS.water,
    windSpeed:2,windDir:104,fetchKm:28,swellHs:.1,swellLength:35,swellDir:110,choppy:0,
    turbidity:.92,scatteringColor:'#2b2822',attenuationDistance:15.7,hwExposure:3.3,
    reflectionEnabled:true,reflectionQuality:100,reflectionBlur:.9,reflectionDistortion:1.15,
    groundReflectionQuality:100,groundReflectionStrength:100,
  }),
  sun:Object.freeze({date:'2026-06-21',minute:1206}),
  display:Object.freeze({...VIEWER_DEFAULTS.display,engine:'raster'}),
  scene:Object.freeze({
    catalogs:Object.freeze(['assets-moscow-style-20261024-r14/tileset.json','assets-moscow-10km-20261108-r1/tileset.json']),layout:'merged',
    camera:Object.freeze({"distance": 1540.6722721722172, "pitch": 0.548, "target": [754.9159720320167, 0, -1421.4774717587673], "yaw": -3.513093750000067}),
  }),
});

// Only the Ocean surface and its reflection pass are shared between cities.
export const WATER_ONLY_KEYS=Object.freeze([
  'windSpeed','windDir','fetchKm','swellHs','swellLength','swellDir','swellSpread','choppy',
  'turbidity','absorptionColor','scatteringColor','attenuationDistance','waterIOR','foam','shoreFoam','animated','waterModel',
  'reflectionEnabled','reflectionQuality','reflectionStrength','reflectionBlur','reflectionDistortion','reflectionDetail',
]);
const moscowWater=Object.fromEntries(WATER_ONLY_KEYS.map(key=>[key,MOSCOW_DEFAULTS.water[key]]));
const regionalWater=Object.freeze({...VIEWER_DEFAULTS.water,...moscowWater});
export const PETERSBURG_DEFAULTS=Object.freeze({
  ...VIEWER_DEFAULTS,id:'spb-moscow-water-20261125-01',
  waterTime:MOSCOW_DEFAULTS.waterTime,water:Object.freeze({...regionalWater,reflectionEnabled:false}),
});
export const KURSK_DEFAULTS=Object.freeze({
  ...VIEWER_DEFAULTS,id:'kursk-moscow-water-20261113-01',
  sun:Object.freeze({date:'2026-06-21',minute:1127}),
  display:Object.freeze({...VIEWER_DEFAULTS.display,engine:'raster'}),
  waterTime:MOSCOW_DEFAULTS.waterTime,water:regionalWater,
});

// A cloud prefix must not change a scene's visual identity or saved defaults.
export function catalogKey(catalog=''){
  return String(catalog).split(/[?#]/)[0].split('/').slice(-2).join('/');
}
export function viewerDefaults(catalog=''){
  const key=catalogKey(catalog);
  if(/^assets-kursk-3km-[^/]+\/tileset\.json$/.test(key))return KURSK_DEFAULTS;
  if(key==='assets-hosek-check/tileset.json'||key.startsWith('assets-spb-')&&key.endsWith('/tileset.json'))return PETERSBURG_DEFAULTS;
  return MOSCOW_DEFAULTS.scene.catalogs.includes(key)?MOSCOW_DEFAULTS:VIEWER_DEFAULTS;
}
export function waterStorageKey(defaults,catalog){
  return `nuray-water:${defaults.id}:${catalogKey(catalog)}`;
}
export function loadSavedWater(storage,defaults,catalog){
  const current=storage.getItem(waterStorageKey(defaults,catalog));
  let saved={};
  if(current!==null){
    saved=JSON.parse(current);
  }else if(defaults===KURSK_DEFAULTS||defaults===PETERSBURG_DEFAULTS){
    const previous=JSON.parse(storage.getItem(waterStorageKey(VIEWER_DEFAULTS,catalog))||'{}');
    saved={...previous,...moscowWater,waterTime:MOSCOW_DEFAULTS.waterTime};
  }
  // Petersburg's full-city mirror is opt-in for each visit.
  return defaults===PETERSBURG_DEFAULTS?{...saved,reflectionEnabled:false}:saved;
}
export function defaultSunPreset(params,defaults=VIEWER_DEFAULTS){
  const date=params.get('sunDate')??defaults.sun.date;
  const raw=params.get('sunMinute'),minute=raw===null?defaults.sun.minute:Number(raw);
  return {date,minute:Number.isFinite(minute)&&minute>=0&&minute<=1440?minute:defaults.sun.minute};
}
