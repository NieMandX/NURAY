// Shared immutable templates + small instance transforms; no duplicated PLYs.
export function transformPoint(m, p){return [0,4,8].map(k=>m[k]*p[0]+m[k+1]*p[1]+m[k+2]*p[2]+m[k+3]);}
export function project(m,p){return [0,1,2,3].map(k=>m[k]*p[0]+m[4+k]*p[1]+m[8+k]*p[2]+m[12+k]);}
export function plantBounds(instances,models){
  return instances.map(i=>{
    const b=models[i.model].bounds,m=i.matrix,half=b.min.map((x,k)=>(b.max[k]-x)/2);
    const center=transformPoint(m,b.min.map((x,k)=>(x+b.max[k])/2));
    const extent=[0,1,2].map(k=>half.reduce((n,h,j)=>n+Math.abs(m[k*4+j])*h,0));
    return {center,extent,radius:Math.hypot(...extent)};
  });
}

export function selectPlants(instances,models,matrix,width,height,budget=350000,eye=null,bounds=plantBounds(instances,models),includeOffscreen=false){
  const focal=Math.hypot(matrix[1],matrix[5],matrix[9])*height;
  const planes=new Float64Array(24);
  [[0,1,1.25],[0,-1,1.25],[1,1,1.25],[1,-1,1.25],[2,1,0],[2,-1,1]].forEach(([axis,sign,guard],i)=>{
    for(let k=0;k<4;k++)planes[i*4+k]=guard*matrix[k*4+3]+sign*matrix[k*4+axis];
  });
  const chosen=[];
  for(let id=0;id<instances.length;id++){
    const {center,extent,radius}=bounds[id],clip=project(matrix,center);
    // LOD allocation covers the whole scene and depends on eye distance, not
    // the set currently inside the frame. Turning the view cannot swap trees.
    const distance=eye?Math.hypot(center[0]-eye[0],center[1]-eye[1],center[2]-eye[2]):Math.abs(clip[3]);
    const size=radius*focal/Math.max(.1,distance);
    const levels=models[instances[id].model].levels;
    const target=Math.max(1,Math.min(8192,size*size*.65));
    let level=levels.length-1;
    while(level>0&&levels[level-1].count<=target)level--;
    let visible=true;
    // Test the entire crown against six homogeneous planes, including crowns
    // straddling the camera/near plane. Keep a guard band while sorting off-thread.
    for(let k=0;k<24;k+=4){
      const d=planes[k]*center[0]+planes[k+1]*center[1]+planes[k+2]*center[2]+planes[k+3];
      const e=extent[0]*Math.abs(planes[k])+extent[1]*Math.abs(planes[k+1])+extent[2]*Math.abs(planes[k+2]);
      if(d+e<0){visible=false;break;}
    }
    chosen.push({id,level,size,target,count:levels[level].count,visible});
  }
  let total=chosen.reduce((n,x)=>n+x.count,0);
  const minimum=instances.reduce((n,i)=>n+models[i.model].levels.at(-1).count,0);
  if(minimum>budget)throw Error('Gaussian budget cannot cover every plant; add coarser splat LODs');
  if(total>budget){
    // Share detail proportionally instead of spending it all on a handful of
    // near crowns and reducing every other visible tree to a single blob.
    const allocate=(scale,apply=false)=>{
      let sum=0;
      for(const x of chosen){
        const levels=models[instances[x.id].model].levels,target=Math.max(1,x.target*scale);
        let level=levels.length-1;
        while(level>0&&levels[level-1].count<=target)level--;
        sum+=levels[level].count;if(apply){x.level=level;x.count=levels[level].count;}
      }
      return sum;
    };
    let lo=0,hi=1;
    for(let k=0;k<14;k++){const mid=(lo+hi)/2;if(allocate(mid)>budget)hi=mid;else lo=mid;}
    total=allocate(lo,true);
  }
  return includeOffscreen?chosen:chosen.filter(x=>x.visible&&x.size>=.4);
}

export function replacementSet(manifest,chunks,models){
  const ranges=chunks.filter(c=>c.instanced&&c.name.startsWith('nuray-approved-'));
  const byDraw=new Map(ranges.map(c=>[c.id,c])),replaced=new Set();
  for(const i of manifest.instances){
    const c=byDraw.get(i.sourceDraw);
    if(!c||i.sourceType!==c.name||!Number.isInteger(i.sourceInstance)||i.sourceInstance<c.instanceFirst||i.sourceInstance>=c.instanceFirst+c.instanceCount||replaced.has(i.sourceInstance))throw Error('Invalid or duplicate Gaussian plant replacement');
    if(!models[i.model]||!Array.isArray(i.matrix)||i.matrix.length!==12||!i.matrix.every(Number.isFinite))throw Error('Invalid Gaussian transform');
    replaced.add(i.sourceInstance);
  }
  if(manifest.scope?.fullScene&&replaced.size!==ranges.reduce((n,c)=>n+c.instanceCount,0))throw Error('Full-scene splats must cover every plant');
  return replaced;
}

// Stable 16-bit counting sort, far-to-near (eye distance along view direction).
export function sortedPairs(chosen,instances,models,points,matrix){
  const count=chosen.reduce((n,x)=>n+x.count,0),pairs=new Uint32Array(count*2),depth=new Float64Array(count);
  let at=0,near=Infinity,far=-Infinity;
  for(const item of chosen){
    const inst=instances[item.id],model=models[inst.model],level=model.levels[item.level];
    for(let n=0;n<level.count;n++){
      const index=model.offset+level.offset+n,k=index*16;
      const m=inst.matrix,x=points[k],y=points[k+1],z=points[k+2];
      const px=m[0]*x+m[1]*y+m[2]*z+m[3],py=m[4]*x+m[5]*y+m[6]*z+m[7],pz=m[8]*x+m[9]*y+m[10]*z+m[11];
      const d=matrix[3]*px+matrix[7]*py+matrix[11]*pz+matrix[15];
      pairs[2*at]=index;pairs[2*at+1]=item.id;depth[at++]=d;near=Math.min(near,d);far=Math.max(far,d);
    }
  }
  const bins=new Uint32Array(65536),keys=new Uint16Array(count),out=new Uint32Array(count*2),scale=65535/Math.max(1e-9,far-near);
  for(let n=0;n<count;n++){keys[n]=Math.min(65535,Math.max(0,Math.floor((far-depth[n])*scale)));bins[keys[n]]++;}
  let sum=0;for(let k=0;k<65536;k++){const n=bins[k];bins[k]=sum;sum+=n;}
  for(let n=0;n<count;n++){const k=bins[keys[n]]++*2;out[k]=pairs[n*2];out[k+1]=pairs[n*2+1];}
  return out;
}

// Compact raster transforms, keeping each source draw's allocated range.
// Main view and reflections share these; shadow/trace buffers keep the originals.
export function compactMeshInstances(chunks,source,replaced){
  const transforms=source.slice(),counts=new Map();
  for(const chunk of chunks){
    if(!chunk.instanced)continue;
    let write=chunk.instanceFirst;
    for(let read=write;read<chunk.instanceFirst+chunk.instanceCount;read++){
      if(replaced.has(read))continue;
      if(write!==read)transforms.set(source.subarray(read*12,read*12+12),write*12);
      write++;
    }
    counts.set(chunk.id,write-chunk.instanceFirst);
  }
  return {transforms,counts};
}
