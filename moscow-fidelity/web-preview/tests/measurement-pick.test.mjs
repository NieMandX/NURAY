import test from 'node:test';
import assert from 'node:assert/strict';
import {createMeasurementGeometry} from '../prototype/tiles/measurement-pick.js';
import {lookAt,multiply,perspective} from '../src/district/math.js';

const camera={yaw:-1.2,pitch:.58,distance:180,target:[2230,11,-1380]};
function fixture(width,height,scale){
  const canvas={width:Math.round(width*scale),height:Math.round(height*scale),clientWidth:width,clientHeight:height};
  return createMeasurementGeometry(()=>({camera,canvas}));
}
function close(actual,expected){
  assert.ok(actual&&actual.every((v,i)=>Math.abs(v-expected[i])<.002),JSON.stringify({actual,expected}));
}
test('projects world metres with the city FOV in CSS pixels at wide and portrait resolutions',()=>{
  for(const [w,h,scale] of [[1000,500,2],[500,800,1.5]]){
    const geometry=fixture(w,h,scale),aspect=w/h,c=camera;
    const eye=[Math.sin(c.yaw)*Math.cos(c.pitch),Math.sin(c.pitch),Math.cos(c.yaw)*Math.cos(c.pitch)].map((n,i)=>c.target[i]+n*c.distance);
    const matrix=multiply(perspective(2*Math.atan(Math.tan(44*Math.PI/360)*Math.max(1,1.1/aspect)),aspect,1,60000,true),lookAt(eye,c.target));
    const p=[2210,24,-1393];
    const clip=[0,1,2,3].map(i=>matrix[i]*p[0]+matrix[4+i]*p[1]+matrix[8+i]*p[2]+matrix[12+i]);
    close(geometry.project(p),[(1+clip[0]/clip[3])*w/2,(1-clip[1]/clip[3])*h/2]);
    close([geometry.depth(p)],[clip[3]]);
    assert.equal(geometry.project(eye.map((n,i)=>n+(n-c.target[i]))),null);
  }
});
test('vertical and surface-normal distances are signed and share the first picked anchor',()=>{
  const geometry=fixture(700,600,1.5),hit={point:[2220,13,-1360],normal:[.6,0,.8]};
  for(const [mode,axis] of [['vertical',[0,1,0]],['normal',hit.normal]]){
    for(const distance of [-19,0,27]){
      const end=hit.point.map((n,i)=>n+axis[i]*distance);
      close(geometry.constrain(hit,...geometry.project(end),mode),end);
    }
  }
  assert.equal(geometry.constrain({...hit,normal:null},300,200,'normal'),null);
});
