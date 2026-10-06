export const MAX_BATCH=8;
// Leave headroom for UI/compositing; zero/quantized timer readings aren't useful estimates.
export function chooseBatch({requested=0,remaining,pathPerSample,overhead=0,current=1,budget=12}) {
  if(remaining<=0)return 0;
  if(requested>0)return Math.min(MAX_BATCH,requested,remaining);
  if(!(pathPerSample>0))return 1;
  const available=Math.max(0,budget-overhead);
  let target=1;
  for(const batch of [2,4,8])if(batch*pathPerSample<=available)target=batch;
  // Grow slowly, drop immediately when the GPU budget is exceeded.
  return Math.min(remaining,target,Math.max(1,current)*2,MAX_BATCH);
}
