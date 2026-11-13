// Shared immutable templates + small instance transforms; no duplicated PLYs.
export function transformPoint(m, p){return [0,4,8].map(k=>m[k]*p[0]+m[k+1]*p[1]+m[k+2]*p[2]+m[k+3]);}
export function project(m,p){return [0,1,2,3].map(k=>m[k]*p[0]+m[4+k]*p[1]+m[8+k]*p[2]+m[12+k]);}
export function selectPlants(instances,models,matrix,width,height,budget=350000){
  const chosen=[];
  for(let id=0;id<instances.length;id++){
    const i=instances[id],b=models[i.model].bounds,m=i.matrix;
    const lo=b.min,hi=b.max,center=transformPoint(m,lo.map((x,k)=>(x+hi[k])/2));
    const radius=Math.hypot(...[0,1,2].map(k=>Math.hypot(m[k],m[k+4],m[k+8])*(hi[k]-lo[k])/2));
    const clip=project(matrix,center),w=clip[3];if(w<=radius+.01)continue;
    const margin=radius*Math.max(Math.hypot(matrix[0],matrix[4],matrix[8]),Math.hypot(matrix[1],matrix[5],matrix[9]));
    if(Math.abs(clip[0])>w+margin||Math.abs(clip[1])>w+margin||clip[2]<-radius||clip[2]>w+radius)continue;
    const size=radius*Math.hypot(matrix[1],matrix[5],matrix[9])*height/w*2;
    if(size<2)continue;
    const levels=models[i.model].levels;
    let level=size>900?0:size>360?1:size>100?2:size>30?3:4;
    level=Math.min(level,levels.length-1);chosen.push({id,level,size,count:levels[level].count});
  }
  let total=chosen.reduce((n,x)=>n+x.count,0);
  // Coarsen the smallest projected plants first, then leave overflow as meshes.
  const ordered=[...chosen].sort((a,b)=>a.size-b.size||a.id-b.id);
  for(const x of ordered){
    const levels=models[instances[x.id].model].levels;
    while(total>budget&&x.level<levels.length-1){total-=x.count;x.count=levels[++x.level].count;total+=x.count;}
    if(total>budget){total-=x.count;x.count=0;}
  }
  return chosen.filter(x=>x.count);
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

// Compact only the main raster transforms, keeping each source draw's allocated
// range. Shadow/reflection/trace buffers retain every original instance.
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
