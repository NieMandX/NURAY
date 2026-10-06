// A zero pixel budget means native canvas size, including Retina/HiDPI density.
export function renderSize(cssWidth,cssHeight,dpr,pixels,limits,bytesPerPixel=16){
  const w=Math.max(1,cssWidth),h=Math.max(1,cssHeight);
  const density=Math.max(.01,dpr||1);
  const maxPixels=Math.floor(Math.min(limits.maxStorageBufferBindingSize,limits.maxBufferSize)/bytesPerPixel);
  const budget=pixels>0?Math.min(pixels,maxPixels):maxPixels;
  const scale=Math.min(density,Math.sqrt(budget/(w*h)),limits.maxTextureDimension2D/w,limits.maxTextureDimension2D/h);
  const width=Math.max(1,Math.floor(w*scale)),height=Math.max(1,Math.floor(h*scale));
  return {width,height,limited:pixels===0&&scale<density-1e-6};
}
