// Bounded transfers/decodes: a failed task stops scheduling new work, and all
// in-flight tasks settle before the caller can dispose its GPU resources.
export async function mapConcurrent(items,visit,limit=4){
  let next=0,failure;
  const results=new Array(items.length);
  await Promise.all(Array.from({length:Math.min(limit,items.length)},async()=>{
    while(!failure&&next<items.length){
      const i=next++;
      try{results[i]=await visit(items[i],i);}catch(error){failure??=error;}
    }
  }));
  if(failure)throw failure;
  return results;
}

// Explicit gzip files have NO HTTP Content-Encoding. The browser streams the
// compressed bytes; DecompressionStream validates the gzip trailer at EOF.
export async function openAsset(spec,base,onBytes=()=>{},fetcher=fetch){
  const r=await fetcher(new URL(spec.url,base),spec.cache?{cache:spec.cache}:{});
  if(!r.ok||!r.body)throw Error('Не найден файл сцены: '+spec.url);
  let transferred=0,decoded=0;
  const total=spec.bytes??Number(r.headers.get('Content-Length'));
  let stream=r.body.pipeThrough(new TransformStream({
    transform(chunk,c){transferred+=chunk.byteLength;onBytes?.(transferred,total);c.enqueue(chunk);},
    flush(){if(spec.bytes!=null&&transferred!==spec.bytes)throw Error('Неполный файл сцены: '+spec.url);},
  }));
  if(spec.encoding==='gzip')stream=stream.pipeThrough(new DecompressionStream('gzip'));
  else if(spec.encoding)throw Error('Неизвестное сжатие сцены: '+spec.encoding);
  if(spec.decodedBytes!=null)stream=stream.pipeThrough(new TransformStream({
    transform(chunk,c){decoded+=chunk.byteLength;if(decoded>spec.decodedBytes)throw Error('Лишние данные сцены');c.enqueue(chunk);},
    flush(){if(decoded!==spec.decodedBytes)throw Error('Неполные распакованные данные сцены');},
  }));
  return stream;
}

export async function readAssetJSON(spec,base,onBytes,fetcher){
  const stream=await openAsset(spec,base,onBytes,fetcher);
  const bytes=await new Response(stream).arrayBuffer();
  if(spec.decodedSha256){
    const digest=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes)),b=>b.toString(16).padStart(2,'0')).join('');
    if(digest!==spec.decodedSha256)throw Error('Контрольная сумма каталога не совпала');
  }
  return JSON.parse(new TextDecoder().decode(bytes));
}
