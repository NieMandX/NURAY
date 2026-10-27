// Optional cloud packaging: each compressed mesh remains byte-identical.
export async function meshBytes(file,base,pack=null,fetcher=fetch){
  if(!pack){
    const r=await fetcher(new URL(file,base));
    if(!r.ok)throw Error('Не найден блок '+file);
    return r.arrayBuffer();
  }
  const entry=pack.entries?.[file],total=pack.bytes;
  if(pack.version!==1||!entry||!Number.isSafeInteger(total)||total<=0)throw Error('Некорректный индекс контейнера тайлов');
  const [offset,length]=entry,end=offset+length-1;
  if(!Number.isSafeInteger(offset)||!Number.isSafeInteger(length)||offset<0||length<=0||!Number.isSafeInteger(end)||end>=total)throw Error('Некорректный диапазон тайла');
  const r=await fetcher(new URL(pack.url,base),{headers:{Range:`bytes=${offset}-${end}`}});
  // Never accidentally download the entire pack for one tile if a host ignores Range.
  if(r.status!==206||r.headers.get('Content-Range')!==`bytes ${offset}-${end}/${total}`){
    await r.body?.cancel();throw Error('Хранилище не вернуло нужный диапазон тайла');
  }
  const bytes=await r.arrayBuffer();
  if(bytes.byteLength!==length)throw Error('Неполный блок в контейнере тайлов');
  return bytes;
}
