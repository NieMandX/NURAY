// BLAS allocation is an internal acceleration layout, independent of map tiles.
// The same buffers serve raster draws and ray traversal; no second geometry copy.
export function planMergedTrace(draws,manifest,limit,maxPages=4){
  if(manifest.format!=='nuray-merged-trace-v1'||manifest.draws.length!==draws.length)throw Error('Неполный ускоритель единого GLB');
  const records=new Map(manifest.draws.map(d=>[d.id,d]));
  if(records.size!==draws.length)throw Error('Повторяющийся блок ускорителя GLB');
  const items=draws.map(d=>{
    const b=records.get(d.id);
    if(!b||b.vertexBytes!==d.vertexBytes||b.indexBytes!==d.indexBytes||b.triangles!==d.triangles||b.nodeBytes!==b.nodeCount*32||!b.nodeCount)throw Error('Ускоритель не соответствует GLB: '+d.id);
    const bytes=d.vertexBytes+d.indexBytes+b.nodeBytes;
    if(!Number.isSafeInteger(bytes)||bytes%4||bytes>limit)throw Error('Блок цельной сцены превышает лимит GPU');
    return {...b,bytes};
  }).sort((a,b)=>b.bytes-a.bytes||a.id-b.id);
  const sizes=Array(maxPages).fill(0),descriptors=new Map();
  for(const c of items){
    const page=sizes.indexOf(Math.min(...sizes));
    if(sizes[page]+c.bytes>limit)throw Error(`Вся сцена не помещается в ${maxPages} GPU-буфера по ${Math.round(limit/1048576)} МиБ. Полная трассировка требует большего лимита памяти; геометрия не была обрезана.`);
    const vertex=sizes[page]/4,index=vertex+c.vertexBytes/4,nodes=index+c.indexBytes/4;
    descriptors.set(c.id,{page,vertex,index,nodes,nodeCount:c.nodeCount});sizes[page]+=c.bytes;
  }
  return {sizes:sizes.filter(Boolean),descriptors,records};
}
export function mergedInstances(draws,transforms){
  const instances=[];
  for(const d of draws){
    const end=(d.instanceFirst+d.instanceCount)*12;
    if(!Number.isInteger(d.instanceCount)||d.instanceCount<1||end>transforms.length)throw Error('Неверный диапазон инстансов GLB');
    for(let n=0;n<d.instanceCount;n++){
      const offset=(d.instanceFirst+n)*12;
      instances.push({mesh:d.id,matrix:Array.from(transforms.subarray(offset,offset+12))});
    }
  }
  return instances;
}
export async function sha256(bytes){return Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes)),x=>x.toString(16).padStart(2,'0')).join('');}
