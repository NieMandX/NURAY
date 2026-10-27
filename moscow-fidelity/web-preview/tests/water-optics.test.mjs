import test from 'node:test';
import assert from 'node:assert/strict';
import {linearColor,absorptionCoefficients,waterTransmission} from '../src/district/ocean/optics.js';
import {VIEWER_DEFAULTS} from '../src/district/viewer-defaults.js';
import {cleanWaterSettings,waterFrameKey,WaterClock} from '../src/district/ocean/settings.js';
test('Beer–Lambert transmittance matches the selected colour at the reference distance',()=>{
 const p=cleanWaterSettings({absorptionColor:'#4080c0',attenuationDistance:12}),c=linearColor(p.absorptionColor);
 const once=waterTransmission(p,12),twice=waterTransmission(p,24);
 for(let i=0;i<3;i++){assert.ok(Math.abs(once[i]-c[i])<1e-10);assert.ok(Math.abs(twice[i]-c[i]*c[i])<1e-10);}
 assert.deepEqual(waterTransmission(p,0),[1,1,1]);
 const shorter=waterTransmission({...p,attenuationDistance:6},12);assert.deepEqual(shorter,twice);
});
test('white absorbs nothing; black stays finite; colours and optics persist safely',()=>{
 assert.deepEqual(absorptionCoefficients(cleanWaterSettings({absorptionColor:'#ffffff'})),[-0,-0,-0]);
 assert.ok(absorptionCoefficients(cleanWaterSettings({absorptionColor:'#000000'})).every(Number.isFinite));
 const p=cleanWaterSettings(JSON.parse(JSON.stringify({absorptionColor:'#11AAee',scatteringColor:'#aabbcc',attenuationDistance:14.5,waterIOR:1.41,turbidity:0})));
 assert.equal(p.absorptionColor,'#11aaee');assert.equal(p.scatteringColor,'#aabbcc');assert.equal(p.attenuationDistance,14.5);assert.equal(p.waterIOR,1.41);assert.equal(p.turbidity,0);
 const bad=cleanWaterSettings({waterIOR:0,attenuationDistance:0,absorptionColor:'red',scatteringColor:'#zzz000'});assert.equal(bad.waterIOR,1);assert.equal(bad.attenuationDistance,.1);assert.equal(bad.absorptionColor,'#8ac6d1');
});
test('all optical controls wake frozen water without advancing simulation time',()=>{
 const o={waterSettings:cleanWaterSettings(),waterClock:new WaterClock(),chunks:[],stats:{geometryBytes:12},canvas:{width:800,height:600}};
 for(const [name,value] of Object.entries({absorptionColor:'#123456',scatteringColor:'#654321',attenuationDistance:25,waterIOR:1.5,turbidity:0})){
  const before=waterFrameKey(o);o.waterSettings[name]=value;assert.notEqual(waterFrameKey(o),before);assert.equal(o.waterClock.time,VIEWER_DEFAULTS.waterTime);
 }
});
