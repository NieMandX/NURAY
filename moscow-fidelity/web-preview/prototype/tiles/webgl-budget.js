// Budget geometry before fetching it. Shared models count once; transforms
// count per placement. Never exceed the limit just to fill a distant tile.
export function overviewDistance(maximum, fits){
  // Search only the coarse range: below 360 m the detail selector adds paint,
  // so its byte cost is no longer monotonic as the camera approaches.
  let low=Math.min(400,maximum),high=maximum;
  if(fits(high))return high;
  if(!fits(low))return low;
  for(let i=0;i<12;i++){
    const middle=(low+high)/2;
    if(fits(middle))low=middle;else high=middle;
  }
  return low;
}

export function budgetTiles(tileset, requested, target, byteLimit, tileLimit, triangleLimit=Infinity){
  const assets=new Map(tileset.chunks.map(c=>[c.id,c]));
  const candidates=tileset.tiles.filter(t=>requested.has(t.id)).sort((a,b)=>{
    const distance=t=>Math.hypot((t.bounds.min[0]+t.bounds.max[0])/2-target[0],(t.bounds.min[2]+t.bounds.max[2])/2-target[2]);
    return distance(a)-distance(b)||a.id.localeCompare(b.id);
  });
  const modes=new Map(),resident=new Set();let bytes=0,triangles=0;
  for(const tile of candidates){
    if(modes.size>=tileLimit)break;
    for(const mode of requested.get(tile.id)==='full'?['full','coarse']:['coarse']){
      const chunks=mode==='full'?tile.chunks:tile.coarseChunks;
      // Unlike memory, raster work counts every placement of a shared mesh.
      // A single nearest tile may exceed the work budget so it stays usable;
      // the byte limit remains hard even in that case.
      const tileTriangles=mode==='full'?tile.fullTriangles:tile.coarseTriangles;
      const ids=new Set([...chunks,...(tile.instances??[]).map(i=>i.mesh)]);
      const added=[...ids].filter(id=>!resident.has(id)).reduce((n,id)=>{
        const c=assets.get(id);if(!c)throw Error('Неизвестный блок '+id);
        return n+c.vertexBytes+c.indexBytes;
      },0)+(chunks.length+(tile.instances?.length??0))*48;
      if(bytes+added>byteLimit)continue;
      if(Number.isFinite(triangleLimit)&&(!Number.isFinite(tileTriangles)||tileTriangles<0))throw Error('Нет числа треугольников тайла '+tile.id);
      if(modes.size&&triangles+tileTriangles>triangleLimit)continue;
      bytes+=added;triangles+=tileTriangles??0;ids.forEach(id=>resident.add(id));modes.set(tile.id,mode);break;
    }
  }
  return {modes,bytes,triangles,limited:triangles>triangleLimit||modes.size<requested.size||[...modes].some(([id,m])=>m!==requested.get(id)),candidates:requested.size};
}
