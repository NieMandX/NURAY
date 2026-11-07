import {mapConcurrent} from '../../src/district/asset-fetch.js?v=asset-delivery-1';

function packEntry(file,pack){
  const entry=pack.entries?.[file],total=pack.bytes;
  if(pack.version!==1||!entry||!Number.isSafeInteger(total)||total<=0)throw Error('Некорректный индекс контейнера тайлов');
  const [offset,length]=entry,end=offset+length-1;
  if(!Number.isSafeInteger(offset)||!Number.isSafeInteger(length)||offset<0||length<=0||!Number.isSafeInteger(end)||end>=total)throw Error('Некорректный диапазон тайла');
  return {file,offset,length,end};
}

async function rangeBytes(base,pack,start,end,fetcher){
  const r=await fetcher(new URL(pack.url,base),{headers:{Range:`bytes=${start}-${end}`}});
  // Do not buffer a whole multi-GB object if a proxy ignores or shifts Range.
  if(r.status!==206||r.headers.get('Content-Range')!==`bytes ${start}-${end}/${pack.bytes}`){
    await r.body?.cancel();throw Error('Хранилище не вернуло нужный диапазон тайла');
  }
  const bytes=await r.arrayBuffer();
  if(bytes.byteLength!==end-start+1)throw Error('Неполный блок в контейнере тайлов');
  return bytes;
}

// Each compressed mesh remains byte-identical, including in a combined range.
export async function meshBytes(file,base,pack=null,fetcher=fetch){
  if(!pack){
    const r=await fetcher(new URL(file,base));
    if(!r.ok)throw Error('Не найден блок '+file);
    return r.arrayBuffer();
  }
  const {offset,end}=packEntry(file,pack);
  return rangeBytes(base,pack,offset,end,fetcher);
}

export function planMeshBatches(files,pack,{maxBytes=8*1048576,maxGapBytes=32768}={}){
  const entries=[...new Set(files)].map(file=>packEntry(file,pack)).sort((a,b)=>a.offset-b.offset);
  const batches=[];
  for(const entry of entries){
    let group=batches.at(-1);
    if(!group||entry.end-group.start+1>maxBytes||entry.offset-group.end-1>maxGapBytes){
      group={start:entry.offset,end:entry.end,entries:[]};batches.push(group);
    }
    group.end=Math.max(group.end,entry.end);group.entries.push(entry);
  }
  return batches;
}

export async function visitMeshBatches(files,base,pack,visit,{fetcher=fetch,onTransfer=()=>{},concurrency=4,...limits}={}){
  if(!pack)return mapConcurrent([...new Set(files)],async file=>{
    const bytes=await meshBytes(file,base,null,fetcher);onTransfer(bytes.byteLength);await visit(file,bytes);
  },concurrency);
  const batches=planMeshBatches(files,pack,limits);
  await mapConcurrent(batches,async group=>{
    const bytes=await rangeBytes(base,pack,group.start,group.end,fetcher);onTransfer(bytes.byteLength);
    // Release each range after consumption; never cache an entire 848-MB pack.
    for(const e of group.entries)await visit(e.file,bytes.slice(e.offset-group.start,e.offset-group.start+e.length));
  },concurrency);
}
