import test from 'node:test';
import assert from 'node:assert/strict';
import {installInstanceCulling} from '../prototype/tiles/main-instance-culling.js';

test('merged review URLs can switch to WebGL and tile renderers without GPU allocation',()=>{
  for(const owner of [{merged:false},{merged:false,device:{}},{merged:true}]){
    assert.equal(installInstanceCulling(owner),null);
    assert.equal(owner.instanceCulling,undefined);
  }
});
import {instanceBounds,clipPlanes,instanceVisible,compactVisibleInstances} from '../src/district/instance-culling.js';
import {perspective,orthographic,multiply,lookAt,visible} from '../src/district/math.js';

const identity=[1,0,0,0,0,1,0,0,0,0,1,0];
const chunk={id:7,name:'plant',instanced:true,instanceFirst:1,instanceCount:1,localBounds:{min:[-2,-1,-3],max:[4,8,2]}};

test('transformed bounds include every corner under rotation, nonuniform scale and shear',()=>{
  const transform=[0,0,-2,100,0,.7,.3,-20,-1.2,0,0,35];
  const source=new Float32Array([...identity,...transform]),b=instanceBounds([chunk],source);
  for(let bits=0;bits<8;bits++){
    const p=[0,1,2].map(k=>chunk.localBounds[bits&(1<<k)?'max':'min'][k]);
    for(let k=0;k<3;k++){
      const at=12+k*4,x=source[at]*p[0]+source[at+1]*p[1]+source[at+2]*p[2]+source[at+3];
      assert.ok(Math.abs(x-b[6+k])<=b[9+k]);
    }
  }
});

test('plane tests agree with independent eight-corner clipping for perspective and orthographic views',()=>{
  let seed=551;const rand=()=>((seed=(Math.imul(seed,1664525)+1013904223)>>>0)/2**32);
  const view=lookAt([20,15,90],[0,3,-15]);
  for(const matrix of [multiply(perspective(1,1.5,1,900,true),view),multiply(perspective(1,1.5,1,900),view),multiply(orthographic(70,.1,900),view)]){
    const planes=clipPlanes(matrix);
    for(let i=0;i<2500;i++){
      const center=[rand()*400-200,rand()*80-20,rand()*1200-1000],half=[rand()*15+.01,rand()*40+.01,rand()*15+.01];
      const bounds={min:center.map((x,k)=>x-half[k]),max:center.map((x,k)=>x+half[k])};
      assert.equal(instanceVisible(new Float64Array([...center,...half]),0,planes),visible(bounds,matrix));
    }
  }
});

test('objects straddling the camera and near plane remain visible',()=>{
  const p=clipPlanes(perspective(1,1,1,100,true));
  assert.equal(instanceVisible(new Float64Array([0,0,0,2,2,2]),0,p),true);
  assert.equal(instanceVisible(new Float64Array([0,0,5,1,1,1]),0,p),false);
  assert.equal(instanceVisible(new Float64Array([0,0,-1000,10,10,10]),0,p),false);
});

test('compaction preserves the original shadow buffer and restores full counts when disabled',()=>{
  const source=new Float32Array([...identity,...identity,...identity,...identity]);
  source[12+11]=-10;source[24+3]=1000;source[24+11]=-10;source[36+11]=-12;
  const c={...chunk,instanceCount:3},staticChunk={id:0,instanceFirst:0,instanceCount:1};
  const original=source.slice(),bounds=instanceBounds([staticChunk,c],source),output=source.slice();
  let r=compactVisibleInstances([staticChunk,c],source,bounds,clipPlanes(perspective(1,1,1,100,true)),new Set([3]),output);
  assert.deepEqual([r.total,r.visible,r.culled,r.substituted],[3,1,1,1]);
  assert.deepEqual(source,original);assert.deepEqual(output.subarray(0,12),source.subarray(0,12));assert.equal(r.counts.has(0),false);
  r=compactVisibleInstances([c],source,bounds,null,new Set(),output);
  assert.equal(r.counts.get(7),3);assert.deepEqual(output,original);
});
