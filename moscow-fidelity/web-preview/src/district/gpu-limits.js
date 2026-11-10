export const DEFAULT_GPU_PAGE_BYTES=256*1024*1024;
export const REGION_GPU_PAGE_BYTES=1024*1024*1024;

// This is a device capability request, not an allocation. Each page buffer
// still uses only the bytes required by the currently resident tile meshes.
export function gpuPageLimit(limits,preferred=DEFAULT_GPU_PAGE_BYTES){
  const values=[preferred,limits.maxStorageBufferBindingSize,limits.maxBufferSize];
  if(values.some(v=>!Number.isFinite(v)||v<4))throw Error('Недопустимый лимит GPU-буфера');
  return Math.floor(Math.min(...values)/4)*4;
}

export function gpuDeviceLimits(limits,preferred=DEFAULT_GPU_PAGE_BYTES){
  const page=gpuPageLimit(limits,preferred),layers=limits.maxTextureArrayLayers;
  if(!Number.isSafeInteger(layers)||layers<1)throw Error('Недопустимый лимит слоёв текстур GPU');
  // Device defaults may expose only 256 layers even when the adapter can
  // handle the larger city's materials. Request the advertised capability;
  // allocation remains proportional to the actual scene, not this limit.
  return {maxStorageBufferBindingSize:page,maxBufferSize:page,maxTextureArrayLayers:layers};
}
