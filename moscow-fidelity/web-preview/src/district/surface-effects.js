// Auxiliary geometry lookup. It never rewrites the baked city/GLB geometry.
export const isRoad=m=>m.family==='Асфальт'&&m.name==='Асфальт';
export function installSurfaceField(owner,values=new Float32Array([0,0,8,0,0,2,0,0,0,0,0,0])){
 owner.surfaceFieldBytes=values.byteLength;owner.surfaceFieldValues=values;
 if(owner.gl){
  const gl=owner.gl;gl.deleteTexture(owner.surfaceField);owner.surfaceField=gl.createTexture();gl.activeTexture(gl.TEXTURE4);gl.bindTexture(gl.TEXTURE_2D,owner.surfaceField);
  const width=Math.min(2048,gl.getParameter(gl.MAX_TEXTURE_SIZE)),height=Math.ceil(values.length/4/width),data=new Float32Array(width*height*4);data.set(values);
  if(height>gl.getParameter(gl.MAX_TEXTURE_SIZE))throw Error('Слишком большой индекс берегов и дорог для WebGL');
  gl.texStorage2D(gl.TEXTURE_2D,1,gl.RGBA32F,width,height);gl.texSubImage2D(gl.TEXTURE_2D,0,0,0,width,height,gl.RGBA,gl.FLOAT,data);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MIN_FILTER,gl.NEAREST);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MAG_FILTER,gl.NEAREST);
 }else{
  const d=owner.device;owner.surfaceField?.destroy();owner.surfaceField=d.createBuffer({size:values.byteLength,usage:GPUBufferUsage.STORAGE|GPUBufferUsage.COPY_DST});d.queue.writeBuffer(owner.surfaceField,0,values);if(owner.mainGroup)owner.bindRaster();
 }
}
export async function loadSurfaceField(owner,url){
 const r=await fetch(url,{cache:'no-cache'});if(!r.ok)throw Error('Не найден индекс берегов и дорожных полос');const meta=await r.json();
 const response=await fetch(new URL(meta.file,url));if(!response.ok)throw Error('Не найден файл берегов и дорожных полос');
 const bytes=await new Response(response.body.pipeThrough(new DecompressionStream('gzip'))).arrayBuffer();
 const hash=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes)),n=>n.toString(16).padStart(2,'0')).join('');
 if(hash!==meta.sha256||bytes.byteLength!==meta.float4Count*16)throw Error('Проверка индекса берегов и дорог не прошла');
 installSurfaceField(owner,new Float32Array(bytes));owner.surfaceEffects=meta;owner.stats.surfaceEffectBytes=owner.surfaceFieldBytes;
 if(owner.streamStats){owner.streamStats.requests+=2;owner.streamStats.downloadBytes+=Number(response.headers.get('Content-Length'))||0;}
}
