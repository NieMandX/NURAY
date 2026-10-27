import test from 'node:test';
import assert from 'node:assert/strict';
import {VIEWER_DEFAULTS,MOSCOW_DEFAULTS,viewerDefaults,catalogKey,defaultSunPreset} from '../src/district/viewer-defaults.js';
import {cleanWaterSettings} from '../src/district/ocean/settings.js';
test('Moscow preset survives hosting prefixes without changing Petersburg',()=>{
 for(const path of ['assets-moscow-style-20261024-r14/tileset.json','https://nuray-scenes.s3.cloud.ru/releases/20261027/assets-moscow-style-20261024-r14/tileset.json?cache=1'])assert.equal(viewerDefaults(path),MOSCOW_DEFAULTS);
 for(const path of ['assets-hosek-check/tileset.json','assets-spb-10km-live-20261024-r13/tileset.json','assets-unknown/tileset.json'])assert.equal(viewerDefaults(path),VIEWER_DEFAULTS);
 assert.equal(catalogKey('https://test/a/assets-hosek-check/tileset.json'),'assets-hosek-check/tileset.json');
});
test('fresh Moscow visit preserves the approved complete optical and rendering state',()=>{
 assert.deepEqual(cleanWaterSettings({},MOSCOW_DEFAULTS.water),MOSCOW_DEFAULTS.water);
 assert.equal(MOSCOW_DEFAULTS.display.engine,'raster');assert.equal(MOSCOW_DEFAULTS.display.renderer,'webgpu');assert.equal(MOSCOW_DEFAULTS.display.samples,64);
 assert.equal(MOSCOW_DEFAULTS.water.hwExposure,3.3);assert.equal(MOSCOW_DEFAULTS.water.attenuationDistance,9.3);
 assert.equal(MOSCOW_DEFAULTS.water.animated,false);assert.equal(MOSCOW_DEFAULTS.waterTime,48.38810000000599);
 assert.equal(VIEWER_DEFAULTS.water.hwExposure,2.55);assert.equal(VIEWER_DEFAULTS.display.engine,'trace');
});
test('partial user edits and reset are relative to the current city',()=>{
 const p=cleanWaterSettings({waterIOR:1.333,windSpeed:Infinity},MOSCOW_DEFAULTS.water);
 assert.equal(p.waterIOR,1.333);assert.equal(p.windSpeed,2);assert.equal(p.hwExposure,3.3);
 assert.deepEqual(defaultSunPreset(new URLSearchParams(),MOSCOW_DEFAULTS),{date:'2026-06-21',minute:1206});
 assert.equal(defaultSunPreset(new URLSearchParams('sunMinute=0'),MOSCOW_DEFAULTS).minute,0);
});
