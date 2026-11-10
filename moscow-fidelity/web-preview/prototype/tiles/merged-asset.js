import {openAsset} from '../../src/district/asset-fetch.js?v=asset-delivery-1';

// Bounded reads for GLB and standard glTF with a large external binary buffer.
export class GlbStream {
  constructor(reader,onBytes=()=>{}){this.reader=reader;this.chunk=new Uint8Array();this.offset=0;this.bytes=0;this.onBytes=onBytes;}
  async take(size,keep=true){
    if(!Number.isSafeInteger(size)||size<0)throw Error('Неверный размер блока сцены');
    const out=keep?new Uint8Array(size):null;let written=0;
    while(written<size){
      if(this.offset===this.chunk.length){const next=await this.reader.read();if(next.done)throw Error('Файл сцены оборван');this.chunk=next.value;this.offset=0;}
      const n=Math.min(size-written,this.chunk.length-this.offset);
      if(out)out.set(this.chunk.subarray(this.offset,this.offset+n),written);
      this.offset+=n;written+=n;this.bytes+=n;this.onBytes(this.bytes);
    }
    return out;
  }
  async finish(){if(this.offset!==this.chunk.length||!(await this.reader.read()).done)throw Error('Лишние данные после сцены');}
}

export async function openMergedAsset(url,{base=url,spec,bufferSpec,onBytes=()=>{},onProgress=()=>{},fetcher=fetch}={}){
  url=new URL(url);let length=spec?.decodedBytes??0;
  let headerTransferred=0;
  const stream=await openAsset(spec??{url:url.href},base,bytes=>{headerTransferred=bytes;onBytes(bytes);},fetcher);
  if(url.pathname.endsWith('.gltf')){
    const header=new Uint8Array(await new Response(stream).arrayBuffer()),doc=JSON.parse(new TextDecoder().decode(header));
    const buffers=doc.buffers??[],buffer=buffers[0];
    if(buffers.length!==1||buffer.uri!=='model.bin'||!Number.isSafeInteger(buffer.byteLength)||buffer.byteLength<0)throw Error('Неверный внешний буфер glTF');
    length=header.byteLength+buffer.byteLength;
    const payload=await openAsset(bufferSpec??{url:new URL(buffer.uri,url).href,decodedBytes:buffer.byteLength},base,
      bytes=>onBytes(headerTransferred+bytes),fetcher);
    const reader=new GlbStream(payload.getReader(),bytes=>onProgress(header.byteLength+bytes,length));
    return {reader,doc,header,length,binaryLength:buffer.byteLength,expectedStreamBytes:buffer.byteLength,format:'gltf'};
  }
  const reader=new GlbStream(stream.getReader(),bytes=>onProgress(bytes,length));
  try{
    const head=new DataView((await reader.take(20)).buffer);
    if(head.getUint32(0,true)!==0x46546c67||head.getUint32(4,true)!==2||head.getUint32(16,true)!==0x4e4f534a)throw Error('Неверный заголовок GLB');
    length=head.getUint32(8,true);
    const header=await reader.take(head.getUint32(12,true)),doc=JSON.parse(new TextDecoder().decode(header));
    const binHead=new DataView((await reader.take(8)).buffer),binaryLength=binHead.getUint32(0,true);
    if(binHead.getUint32(4,true)!==0x004e4942||reader.bytes+binaryLength!==length)throw Error('Неверный BIN в GLB');
    return {reader,doc,header,length,binaryLength,expectedStreamBytes:length,format:'glb'};
  }catch(error){await reader.reader.cancel().catch(()=>{});throw error;}
}
