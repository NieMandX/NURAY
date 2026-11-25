import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {VIEWER_DEFAULTS,MOSCOW_DEFAULTS,KURSK_DEFAULTS,PETERSBURG_DEFAULTS,WATER_ONLY_KEYS,loadSavedWater,waterStorageKey,viewerDefaults,catalogKey,defaultSunPreset} from '../src/district/viewer-defaults.js';
import {cleanWaterSettings} from '../src/district/ocean/settings.js';
test('city water presets survive hosting prefixes and catalog aliases',()=>{
 for(const path of ['assets-moscow-style-20261024-r14/tileset.json','https://storage.yandexcloud.net/nuray-assets-niemandx/assets-moscow-style-20261024-r14/tileset.json','https://nuray-scenes.s3.cloud.ru/releases/20261027/assets-moscow-style-20261024-r14/tileset.json?cache=1'])assert.equal(viewerDefaults(path),MOSCOW_DEFAULTS);
 for(const path of ['assets-hosek-check/tileset.json','assets-spb-10km-live-20261023-r9/tileset.json','https://storage.yandexcloud.net/nuray-assets-niemandx/assets-spb-10km-live-20261024-r13/tileset.json?cache=1'])assert.equal(viewerDefaults(path),PETERSBURG_DEFAULTS);
 assert.equal(viewerDefaults('assets-unknown/tileset.json'),VIEWER_DEFAULTS);
 assert.equal(catalogKey('https://test/a/assets-hosek-check/tileset.json'),'assets-hosek-check/tileset.json');
});
test('fresh Moscow visit preserves the approved complete optical and rendering state',()=>{
 assert.equal(viewerDefaults('assets-moscow-10km-20261108-r1/tileset.json'),MOSCOW_DEFAULTS);
 assert.deepEqual(cleanWaterSettings({},MOSCOW_DEFAULTS.water),MOSCOW_DEFAULTS.water);
 assert.equal(MOSCOW_DEFAULTS.display.engine,'raster');assert.equal(MOSCOW_DEFAULTS.display.renderer,'webgpu');assert.equal(MOSCOW_DEFAULTS.display.samples,64);
 assert.equal(MOSCOW_DEFAULTS.water.hwExposure,3.3);assert.equal(MOSCOW_DEFAULTS.water.attenuationDistance,15.7);
 assert.equal(MOSCOW_DEFAULTS.water.animated,false);assert.equal(MOSCOW_DEFAULTS.waterTime,48.38810000000599);
 assert.equal(VIEWER_DEFAULTS.water.hwExposure,2.55);assert.equal(VIEWER_DEFAULTS.display.engine,'trace');
});
test('Moscow defaults exactly match the approved Chrome controls, including disabled ground reflections',()=>{
 const capture=JSON.parse(readFileSync(new URL('../../../docs/moscow-approved-20261027-02.json',import.meta.url),'utf8'));
 assert.equal(MOSCOW_DEFAULTS.id,capture.id);
 assert.deepEqual(cleanWaterSettings({},MOSCOW_DEFAULTS.water),capture.water);
 assert.equal(MOSCOW_DEFAULTS.waterTime,capture.waterTime);
 assert.deepEqual(MOSCOW_DEFAULTS.sun,capture.sun);
 assert.deepEqual(MOSCOW_DEFAULTS.display,capture.display);
 assert.equal(VIEWER_DEFAULTS.id,'approved-20261024-01');
 assert.equal(VIEWER_DEFAULTS.water.reflectionEnabled,false);
 assert.equal(VIEWER_DEFAULTS.water.groundReflectionQuality,50);
});
test('partial user edits and reset are relative to the current city',()=>{
 const p=cleanWaterSettings({waterIOR:1.333,windSpeed:Infinity},MOSCOW_DEFAULTS.water);
 assert.equal(p.waterIOR,1.333);assert.equal(p.windSpeed,2);assert.equal(p.hwExposure,3.3);
 assert.deepEqual(defaultSunPreset(new URLSearchParams(),MOSCOW_DEFAULTS),{date:'2026-06-21',minute:1206});
 assert.equal(defaultSunPreset(new URLSearchParams('sunMinute=0'),MOSCOW_DEFAULTS).minute,0);
});

test('Petersburg and Kursk share approved Moscow water and preserve city light, camera and user edits',()=>{
 const previous={...VIEWER_DEFAULTS.water,hwExposure:1.7,sunIntensity:45,lighting:'classic',groundReflectionEnabled:true,waterTime:1};
 for(const [catalog,defaults] of [
  ['assets-spb-10km-live-20261024-r13/tileset.json',PETERSBURG_DEFAULTS],
  ['https://example.test/releases/assets-kursk-3km-20261113-r10/tileset.json',KURSK_DEFAULTS],
 ]){
  assert.equal(viewerDefaults(catalog),defaults);
  const records=new Map(),storage={getItem:key=>records.get(key)??null};
  const legacyKey=waterStorageKey(VIEWER_DEFAULTS,catalog),newKey=waterStorageKey(defaults,catalog);
  assert.notEqual(legacyKey,newKey);
  const fresh=cleanWaterSettings(loadSavedWater(storage,defaults,catalog),defaults.water);
  const expectedWater={...MOSCOW_DEFAULTS.water,reflectionEnabled:defaults===KURSK_DEFAULTS};
  for(const key of WATER_ONLY_KEYS)assert.equal(fresh[key],expectedWater[key],key);
  assert.equal(fresh.hwExposure,VIEWER_DEFAULTS.water.hwExposure);
  records.set(legacyKey,JSON.stringify(previous));
  const migrated=loadSavedWater(storage,defaults,catalog);
  for(const key of WATER_ONLY_KEYS)assert.equal(migrated[key],expectedWater[key],key);
  for(const key of ['hwExposure','sunIntensity','lighting','groundReflectionEnabled'])assert.equal(migrated[key],previous[key]);
  assert.equal(migrated.waterTime,MOSCOW_DEFAULTS.waterTime);
  const edited={...migrated,foam:.2,reflectionEnabled:true,waterTime:6};
  records.set(newKey,JSON.stringify(edited));
  assert.deepEqual(loadSavedWater(storage,defaults,catalog),{...edited,reflectionEnabled:expectedWater.reflectionEnabled});
  edited.reflectionEnabled=false;
  records.set(newKey,JSON.stringify(edited));
  assert.deepEqual(loadSavedWater(storage,defaults,catalog),edited);
  assert.deepEqual(JSON.parse(records.get(legacyKey)),previous);
 }
 assert.equal(PETERSBURG_DEFAULTS.scene,VIEWER_DEFAULTS.scene);
 assert.equal(PETERSBURG_DEFAULTS.display,VIEWER_DEFAULTS.display);
 assert.equal(PETERSBURG_DEFAULTS.sun,VIEWER_DEFAULTS.sun);
});
