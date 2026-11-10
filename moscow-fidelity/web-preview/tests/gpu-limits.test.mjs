import test from 'node:test';
import assert from 'node:assert/strict';
import {gpuDeviceLimits,REGION_GPU_PAGE_BYTES} from '../src/district/gpu-limits.js';

test('large city requests advertised material capacity independently of buffer pages',()=>{
  const limits={maxStorageBufferBindingSize:2**30,maxBufferSize:2**32,maxTextureArrayLayers:2048};
  assert.deepEqual(gpuDeviceLimits(limits,REGION_GPU_PAGE_BYTES),{
    maxStorageBufferBindingSize:2**30,maxBufferSize:2**30,maxTextureArrayLayers:2048});
});
test('smaller devices never receive an unsupported limit',()=>{
  const limits={maxStorageBufferBindingSize:128*1024**2,maxBufferSize:256*1024**2,maxTextureArrayLayers:256};
  assert.deepEqual(gpuDeviceLimits(limits,REGION_GPU_PAGE_BYTES),{
    maxStorageBufferBindingSize:128*1024**2,maxBufferSize:128*1024**2,maxTextureArrayLayers:256});
});
test('invalid adapter capabilities are rejected before device creation',()=>{
  for(const layers of [undefined,NaN,0,1.5])assert.throws(()=>gpuDeviceLimits({
    maxStorageBufferBindingSize:2**30,maxBufferSize:2**30,maxTextureArrayLayers:layers}));
});
