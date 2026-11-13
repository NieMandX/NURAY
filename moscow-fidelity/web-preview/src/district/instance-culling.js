// Conservative world AABBs for the *main view* only. The original instance
// buffer stays immutable for sunlight, reflections and ray traversal.
export function instanceBounds(chunks,source){
  const bounds=new Float64Array(source.length/12*6);
  for(const c of chunks){
    if(!c.instanced)continue;
    if(!c.localBounds)throw Error('Missing template bounds: '+c.name);
    const lo=c.localBounds.min,hi=c.localBounds.max;
    const center=lo.map((x,k)=>(x+hi[k])/2),half=lo.map((x,k)=>(hi[k]-x)/2);
    if(c.instanceFirst+c.instanceCount>source.length/12)throw Error('Invalid instance range');
    for(let i=c.instanceFirst;i<c.instanceFirst+c.instanceCount;i++){
      for(let axis=0;axis<3;axis++){
        const k=i*12+axis*4;
        bounds[i*6+axis]=source[k]*center[0]+source[k+1]*center[1]+source[k+2]*center[2]+source[k+3];
        bounds[i*6+3+axis]=Math.abs(source[k])*half[0]+Math.abs(source[k+1])*half[1]+Math.abs(source[k+2])*half[2]+.01;
      }
    }
  }
  return bounds;
}

export function clipPlanes(m){
  const p=new Float64Array(24);
  for(let k=0;k<4;k++){
    p[k]=m[k*4+3]+m[k*4];p[4+k]=m[k*4+3]-m[k*4];
    p[8+k]=m[k*4+3]+m[k*4+1];p[12+k]=m[k*4+3]-m[k*4+1];
    p[16+k]=m[k*4+2];p[20+k]=m[k*4+3]-m[k*4+2];
  }
  return p;
}

export function instanceVisible(bounds,id,p){
  const b=id*6;
  for(let k=0;k<24;k+=4){
    const distance=p[k]*bounds[b]+p[k+1]*bounds[b+1]+p[k+2]*bounds[b+2]+p[k+3];
    const extent=Math.abs(p[k])*bounds[b+3]+Math.abs(p[k+1])*bounds[b+4]+Math.abs(p[k+2])*bounds[b+5];
    if(distance+extent<0)return false;
  }
  return true;
}

export function compactVisibleInstances(chunks,source,bounds,planes,replaced,output=source.slice()){
  const counts=new Map();let total=0,visible=0,substituted=0;
  for(const c of chunks){
    if(!c.instanced)continue;
    let write=c.instanceFirst;
    for(let read=write;read<c.instanceFirst+c.instanceCount;read++){
      total++;
      if(replaced.has(read)){substituted++;continue;}
      if(planes&&!instanceVisible(bounds,read,planes))continue;
      output.set(source.subarray(read*12,read*12+12),write*12);write++;visible++;
    }
    counts.set(c.id,write-c.instanceFirst);
  }
  return {transforms:output,counts,total,visible,substituted,culled:total-visible-substituted};
}
