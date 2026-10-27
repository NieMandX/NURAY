import test from 'node:test';
import assert from 'node:assert/strict';
import {VIEWER_DEFAULTS} from '../src/district/viewer-defaults.js';
import {WaterClock,cleanWaterSettings,WATER_DEFAULTS,waterFrameKey} from '../src/district/ocean/settings.js';
test('freeze holds time; resume does not integrate time spent paused',()=>{
 const c=new WaterClock();c.tick(1000,false);assert.equal(c.time,VIEWER_DEFAULTS.waterTime);c.tick(6000,true);assert.equal(c.time,VIEWER_DEFAULTS.waterTime);c.tick(6050,true);assert.equal(c.time,VIEWER_DEFAULTS.waterTime+.05);
 c.tick(6100,false);const frozen=c.time;c.tick(100000,false);assert.equal(c.time,frozen);c.tick(200000,true);assert.equal(c.time,frozen);c.tick(200016,true);assert.ok(Math.abs(c.time-frozen-.016)<1e-9);
});
test('persisted values cannot inject NaN, invalid ranges, or truthy animation',()=>{
 const p=cleanWaterSettings({windSpeed:Infinity,swellHs:-20,haze:999,turbidity:null,animated:'true'});
 assert.equal(p.windSpeed,WATER_DEFAULTS.windSpeed);assert.equal(p.swellHs,0);assert.equal(p.haze,WATER_DEFAULTS.haze);assert.equal(p.turbidity,WATER_DEFAULTS.turbidity);assert.equal(p.animated,false);
});
test('invalid stored documents recover defaults',()=>{assert.deepEqual(cleanWaterSettings(null),WATER_DEFAULTS);assert.deepEqual(cleanWaterSettings(false),WATER_DEFAULTS);});
test('partial presets use the approved light without losing wave settings',()=>{
 const previous={windSpeed:8.4,foam:1.3,animated:false};
 const migrated=cleanWaterSettings(JSON.parse(JSON.stringify(previous)));
 assert.equal(migrated.lighting,WATER_DEFAULTS.lighting);assert.equal(migrated.windSpeed,8.4);assert.equal(migrated.foam,1.3);
 assert.equal(cleanWaterSettings({...previous,lighting:'classic'}).lighting,'classic');
 assert.equal(cleanWaterSettings({...previous,lighting:'unknown'}).lighting,WATER_DEFAULTS.lighting);
});
test('changing illumination wakes a frozen frame without changing water time',()=>{
 const o={waterSettings:cleanWaterSettings(),waterClock:new WaterClock(),chunks:[],stats:{geometryBytes:12},canvas:{width:800,height:600}};
 const before=waterFrameKey(o),time=o.waterClock.time;o.waterSettings.lighting='classic';
 assert.notEqual(waterFrameKey(o),before);assert.equal(o.waterClock.time,time);assert.equal(o.waterSettings.animated,false);
});
test('only classic and physical sky persist; retired lighting and water modes recover safely',()=>{
 for(const lighting of ['classic','hosek']){
  const p=cleanWaterSettings(JSON.parse(JSON.stringify({lighting,windSpeed:9.2,animated:false})));
  assert.equal(p.waterModel,'ocean');assert.equal(p.lighting,lighting);assert.equal(p.windSpeed,9.2);
 }
 for(const lighting of ['ocean','seascape','blend','invalid']) {
  const p=cleanWaterSettings({lighting,waterModel:'seascape',windSpeed:8.4});
  assert.equal(p.lighting,WATER_DEFAULTS.lighting);assert.equal(p.waterModel,'ocean');assert.equal(p.windSpeed,8.4);
 }
});
test('solar controls retain valid zero and clamp invalid ranges',()=>{
 const p=cleanWaterSettings(JSON.parse(JSON.stringify({lighting:'classic',sunIntensity:0,shadowStrength:175})));
 assert.equal(p.sunIntensity,0);assert.equal(p.shadowStrength,175);
 const bad=cleanWaterSettings({sunIntensity:-10,shadowStrength:999});
 assert.equal(bad.sunIntensity,0);assert.equal(bad.shadowStrength,200);
});
test('lighting sliders wake frozen frames without advancing the waves',()=>{
 const o={waterSettings:cleanWaterSettings(),waterClock:new WaterClock(),chunks:[],stats:{geometryBytes:12},canvas:{width:800,height:600}};
 for(const key of ['hwSkyIntensity','sunIntensity','shadowStrength']) {
  const before=waterFrameKey(o);o.waterSettings[key]+=5;
  assert.notEqual(waterFrameKey(o),before);assert.equal(o.waterClock.time,VIEWER_DEFAULTS.waterTime);
 }
});

test('Physical sky controls keep supported fit ranges and retain saved settings',()=>{
 const p=cleanWaterSettings({lighting:'hosek',hwTurbidity:25,hwAlbedo:-1,hwExposure:2.1,hwSkyIntensity:140});
 assert.equal(p.lighting,'hosek');assert.equal(p.hwTurbidity,10);assert.equal(p.hwAlbedo,0);assert.equal(p.hwExposure,2.1);assert.equal(p.hwSkyIntensity,140);
});
