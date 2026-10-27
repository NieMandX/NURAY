// Spatial tiles and GPU bindings are independent. Reserve space using each
// tile's FULL detail size so streaming cannot overflow or reshuffle the pages.
export function planGpuPages(tileset,limit,maxPages=4,modes=null){
  const assets=new Map(tileset.chunks.map(c=>[c.id,c]));
  const selected=tileset.tiles.filter(t=>!modes||modes.has(t.id));
  const weighted=selected.map(tile=>({id:tile.id,bytes:(modes&&modes.get(tile.id)!=='full'?tile.coarseChunks:tile.chunks).reduce((sum,id)=>{
    const c=assets.get(id);if(!c)throw Error('Missing tile chunk '+id);
    return sum+c.vertexBytes+c.indexBytes+c.nodeBytes;
  },0)})).sort((a,b)=>b.bytes-a.bytes||a.id.localeCompare(b.id));
  const pages=Array.from({length:maxPages},()=>({tiles:[],bytes:0}));
  // Shared BLAS geometry is reserved once, independently of owner tiles.
  const shared=new Set(selected.flatMap(t=>(t.instances??[]).map(i=>i.mesh)));
  for(const c of [...assets.values()].filter(c=>c.instanced&&(!modes||shared.has(c.id))).sort((a,b)=>a.id.localeCompare(b.id))){
    const bytes=c.vertexBytes+c.indexBytes+c.nodeBytes;
    const target=pages.filter(p=>p.bytes+bytes<=limit).sort((a,b)=>a.bytes-b.bytes)[0];
    if(!target)throw Error('Общая геометрия превышает бюджет GPU-страниц');
    (target.shared??=[]).push(c.id);target.bytes+=bytes;
  }
  for(const tile of weighted){
    const target=pages.filter(p=>p.bytes+tile.bytes<=limit).sort((a,b)=>a.bytes-b.bytes)[0];
    if(!target)throw Error('Регион превышает бюджет GPU-страниц; требуется ограничить резидентный набор тайлов');
    target.tiles.push(tile.id);target.bytes+=tile.bytes;
  }
  return pages.filter(p=>p.tiles.length||p.shared?.length).map(p=>({...p,tiles:p.tiles.sort()}));
}
