import {isStandardGround} from '../../src/district/ground-surfaces.js?v=ground-reflections-1';
import {absorptionCoefficients,linearColor} from '../../src/district/ocean/optics.js?v=shore-water-1';
import {HosekCache} from '../../src/district/hosek/model.js?v=moscow-defaults-1';
import {waterSkyVertex,waterSkyFragment} from './water-webgl-sky.js?v=shore-water-1';
import {installSurfaceField,isRoad} from '../../src/district/surface-effects.js?v=moscow-defaults-1';
import {sunCascades,shadowUniform,inverseMatrix} from '../../src/district/sun-shadows.js?v=moscow-defaults-1';
import {isFacade,facadePixels} from '../../src/district/facade-relief.js?v=moscow-defaults-1';
import {contactVertex,contactFragment,contactComposite} from './webgl-contact-ao.js?v=moscow-defaults-1';
import {TileRenderer} from './tile-renderer.js?v=shore-water-1';
import {activeChunkIds,sceneInstances,rasterLayout} from './tile-scene.js?v=moscow-defaults-1';
import {lookAt,perspective,orthographic,multiply,normalize,visible} from '../../src/district/math.js?v=moscow-defaults-1';
import {budgetTiles,overviewDistance} from './webgl-budget.js?v=moscow-defaults-1';
import {WebGLReflection} from './planar-webgl.js?v=ground-reflections-1';
import {vertex,fragment,shadowFragment,captureFragment} from './webgl-shaders.js?v=shore-water-1';

function program(gl,vs,fs){
  const shaders=[];const p=gl.createProgram();
  try{
    for(const [type,code] of [[gl.VERTEX_SHADER,vs],[gl.FRAGMENT_SHADER,fs]]){
      const s=gl.createShader(type);shaders.push(s);gl.shaderSource(s,code);gl.compileShader(s);
      if(!gl.getShaderParameter(s,gl.COMPILE_STATUS))throw Error('WebGL: '+gl.getShaderInfoLog(s));
      gl.attachShader(p,s);
    }
    gl.linkProgram(p);if(!gl.getProgramParameter(p,gl.LINK_STATUS))throw Error('WebGL: '+gl.getProgramInfoLog(p));
    const uniforms={};for(let i=0;i<gl.getProgramParameter(p,gl.ACTIVE_UNIFORMS);i++){
      const u=gl.getActiveUniform(p,i);uniforms[u.name.replace(/\[0\]$/,'')]=gl.getUniformLocation(p,u.name);
    }
    return {program:p,uniforms};
  }catch(e){gl.deleteProgram(p);throw e;}finally{shaders.forEach(s=>gl.deleteShader(s));}
}

export class WebGLTileRenderer extends TileRenderer {
  constructor(canvas,onStatus,onError){
    super(canvas,onStatus,onError);this.backend='webgl2';
    this.hosekCache=new HosekCache();this.mobile=matchMedia('(pointer: coarse)').matches||/iPad|iPhone|Android/.test(navigator.userAgent);
    this.geometryBudget=(this.mobile?96:192)*1048576;this.tileLimit=this.mobile?64:256;
    this.triangleBudget=this.mobile?2000000:6000000;
    this.cacheBudget=(this.mobile?12:24)*1048576;this.queries=[];this.state.engine='raster';
  }
  async init(){
    const gl=this.canvas.getContext('webgl2',{alpha:false,antialias:false,depth:true,stencil:false,powerPreference:'high-performance'});
    if(!gl)throw Error('WebGL 2 недоступен. Включите аппаратное ускорение или откройте сцену в обновлённом браузере.');
    this.gl=gl;installSurfaceField(this);
    if(typeof DecompressionStream==='undefined')throw Error('Для загрузки тайлов нужен браузер с поддержкой DecompressionStream. Обновите Safari / браузер.');
    if(!globalThis.crypto?.subtle)throw Error('Откройте viewer через HTTPS или localhost: проверка файлов сцены требует защищённого соединения.');
    this.contactProgram=program(gl,contactVertex,contactFragment);this.contactComposite=program(gl,contactVertex,contactComposite);this.shadowKeys=[];this.mainProgram=program(gl,vertex,fragment);this.shadowProgram=program(gl,vertex,shadowFragment);
    this.sun=normalize([-.62,1,.45]);this.instanceBuffer=gl.createBuffer();
    this.timerExtension=gl.getExtension('EXT_disjoint_timer_query_webgl2');this.timer={enabled:!!this.timerExtension};
    this.shadowSize=this.mobile?1024:2048;
    this.shadowTexture=gl.createTexture();gl.bindTexture(gl.TEXTURE_2D_ARRAY,this.shadowTexture);
    gl.texStorage3D(gl.TEXTURE_2D_ARRAY,1,gl.DEPTH_COMPONENT24,this.shadowSize,this.shadowSize,3);
    gl.texParameteri(gl.TEXTURE_2D_ARRAY,gl.TEXTURE_MIN_FILTER,gl.LINEAR);gl.texParameteri(gl.TEXTURE_2D_ARRAY,gl.TEXTURE_MAG_FILTER,gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D_ARRAY,gl.TEXTURE_WRAP_S,gl.CLAMP_TO_EDGE);gl.texParameteri(gl.TEXTURE_2D_ARRAY,gl.TEXTURE_WRAP_T,gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D_ARRAY,gl.TEXTURE_COMPARE_MODE,gl.COMPARE_REF_TO_TEXTURE);gl.texParameteri(gl.TEXTURE_2D_ARRAY,gl.TEXTURE_COMPARE_FUNC,gl.LEQUAL);
    this.shadowFramebuffer=gl.createFramebuffer();gl.bindFramebuffer(gl.FRAMEBUFFER,this.shadowFramebuffer);
    gl.framebufferTextureLayer(gl.FRAMEBUFFER,gl.DEPTH_ATTACHMENT,this.shadowTexture,0,0);gl.drawBuffers([gl.NONE]);gl.readBuffer(gl.NONE);
    if(gl.checkFramebufferStatus(gl.FRAMEBUFFER)!==gl.FRAMEBUFFER_COMPLETE)throw Error('WebGL: не удалось создать карту теней.');
    gl.bindFramebuffer(gl.FRAMEBUFFER,null);gl.enable(gl.DEPTH_TEST);gl.depthFunc(gl.LEQUAL);gl.enable(gl.CULL_FACE);gl.cullFace(gl.BACK);
    this.onContextLost=e=>{e.preventDefault();this.ready=false;this.running=false;cancelAnimationFrame(this.raf);this.onError('Графический контекст потерян. Обновите страницу, чтобы восстановить сцену.');};
    this.canvas.addEventListener('webglcontextlost',this.onContextLost);
    this.resizeObserver=new ResizeObserver(()=>this.resize());this.resizeObserver.observe(this.canvas);this.resize();
    this.waterSkyProgram=program(this.gl,waterSkyVertex,waterSkyFragment);
    this.reflection=new WebGLReflection(this,program(gl,vertex,captureFragment));
    this.groundReflection=new WebGLReflection(this,this.reflection.program,true);
    this.running=true;this.raf=requestAnimationFrame(t=>this.frame(t));
  }
  async open(url){
    const r=await fetch(url,{cache:'no-cache'});if(!r.ok)throw Error('Не найден каталог тайлов');
    this.tileset=await r.json();this.city=this.tileset;this.base=new URL('.',url);this.sceneName='moscow';
    this.assets=new Map(this.tileset.chunks.map(c=>[c.id,c]));this.state.exposure=.85;
    this.loading=true;this.phase='Загружаем PBR-материалы';this.progress=0;this.publish(true);
    await this.loadMaterials();this.loading=false;
  }
  async loadMaterials(){
    const gl=this.gl,materials=this.tileset.materials,size=this.mobile?256:512;
    const images=[null,...new Set(materials.map(m=>m.texture).filter(Boolean))],layers=new Map(images.map((s,i)=>[s,i]));
    if(images.length>gl.getParameter(gl.MAX_ARRAY_TEXTURE_LAYERS))throw Error('Слишком много текстур для этого WebGL-устройства.');
    if(materials.length>gl.getParameter(gl.MAX_TEXTURE_SIZE))throw Error('Слишком много материалов для этого WebGL-устройства.');
    this.albedo=gl.createTexture();gl.activeTexture(gl.TEXTURE0);gl.bindTexture(gl.TEXTURE_2D_ARRAY,this.albedo);
    gl.texStorage3D(gl.TEXTURE_2D_ARRAY,Math.log2(size)+1,gl.SRGB8_ALPHA8,size,size,images.length);
    gl.texParameteri(gl.TEXTURE_2D_ARRAY,gl.TEXTURE_MIN_FILTER,gl.LINEAR_MIPMAP_LINEAR);gl.texParameteri(gl.TEXTURE_2D_ARRAY,gl.TEXTURE_MAG_FILTER,gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D_ARRAY,gl.TEXTURE_WRAP_S,gl.REPEAT);gl.texParameteri(gl.TEXTURE_2D_ARRAY,gl.TEXTURE_WRAP_T,gl.REPEAT);
    const anisotropy=gl.getExtension('EXT_texture_filter_anisotropic');
    if(anisotropy)gl.texParameterf(gl.TEXTURE_2D_ARRAY,anisotropy.TEXTURE_MAX_ANISOTROPY_EXT,Math.min(4,gl.getParameter(anisotropy.MAX_TEXTURE_MAX_ANISOTROPY_EXT)));
    gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL,false);gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL,false);
    gl.pixelStorei(gl.UNPACK_COLORSPACE_CONVERSION_WEBGL,gl.NONE);
    const white=new Uint8Array(size*size*4).fill(255);
    gl.texSubImage3D(gl.TEXTURE_2D_ARRAY,0,0,0,0,size,size,1,gl.RGBA,gl.UNSIGNED_BYTE,white);
    const scratch=document.createElement('canvas');scratch.width=scratch.height=size;const ctx=scratch.getContext('2d');
    const facadeImages=new Set(materials.filter(isFacade).map(m=>m.texture));
    for(let i=1;i<images.length;i++){
      if(facadeImages.has(images[i])){gl.bindTexture(gl.TEXTURE_2D_ARRAY,this.albedo);gl.texSubImage3D(gl.TEXTURE_2D_ARRAY,0,0,0,i,size,size,1,gl.RGBA,gl.UNSIGNED_BYTE,facadePixels(size,size));continue;}
      const r=await fetch(new URL(images[i],this.base));if(!r.ok)throw Error('Не найдена текстура '+images[i]);
      // Canvas resizing also works in Safari, where createImageBitmap resize
      // options have varied between versions. Preserve the source UV origin.
      const bitmap=await createImageBitmap(await r.blob(),{premultiplyAlpha:'none',colorSpaceConversion:'none'});
      ctx.clearRect(0,0,size,size);ctx.drawImage(bitmap,0,0,size,size);bitmap.close();
      gl.bindTexture(gl.TEXTURE_2D_ARRAY,this.albedo);
      gl.texSubImage3D(gl.TEXTURE_2D_ARRAY,0,0,0,i,size,size,1,gl.RGBA,gl.UNSIGNED_BYTE,scratch);
      this.progress=i/(images.length-1);this.publish();
    }
    gl.generateMipmap(gl.TEXTURE_2D_ARRAY);
    const data=new Float32Array(materials.length*12);
    materials.forEach((m,i)=>data.set([...m.color,m.roughness,m.metallic,m.ior,m.kind,m.alphaCutoff,layers.get(m.texture)||0,isFacade(m)?1:isStandardGround(m)?-1:0,isRoad(m)?1:0,0],i*12));
    this.materialTexture=gl.createTexture();gl.activeTexture(gl.TEXTURE1);gl.bindTexture(gl.TEXTURE_2D,this.materialTexture);
    gl.texStorage2D(gl.TEXTURE_2D,1,gl.RGBA32F,3,materials.length);gl.texSubImage2D(gl.TEXTURE_2D,0,0,0,3,materials.length,gl.RGBA,gl.FLOAT,data);
    gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MIN_FILTER,gl.NEAREST);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MAG_FILTER,gl.NEAREST);
    this.state.materials=materials.length;this.stats.textureBytes=Math.ceil(size*size*4*4/3)*images.length+data.byteLength;
    this.facadeNormal=gl.createTexture();gl.activeTexture(gl.TEXTURE3);gl.bindTexture(gl.TEXTURE_2D,this.facadeNormal);
    gl.texStorage2D(gl.TEXTURE_2D,10,gl.RGBA8,8,512);gl.texSubImage2D(gl.TEXTURE_2D,0,0,0,8,512,gl.RGBA,gl.UNSIGNED_BYTE,facadePixels(8,512,true));gl.generateMipmap(gl.TEXTURE_2D);
    gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MIN_FILTER,gl.LINEAR_MIPMAP_LINEAR);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MAG_FILTER,gl.LINEAR);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_S,gl.REPEAT);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_T,gl.REPEAT);
    this.assertGL('материалы');
  }
  assertGL(stage){const e=this.gl.getError();if(e!==this.gl.NO_ERROR)throw Error(`WebGL: ${stage}, ошибка 0x${e.toString(16)}`);}
  resize(){
    if(!this.gl)return;const rect=this.canvas.getBoundingClientRect(),ratio=devicePixelRatio||1;
    let w=Math.max(1,rect.width*ratio),h=Math.max(1,rect.height*ratio);
    const budget=this.state.pixels,scale=budget>0?Math.min(1,Math.sqrt(budget/(w*h))):1;
    w*=scale;h*=scale;const max=this.gl.getParameter(this.gl.MAX_RENDERBUFFER_SIZE),limit=Math.min(1,max/w,max/h);
    const width=Math.max(1,Math.floor(w*limit)),height=Math.max(1,Math.floor(h*limit));this.resolutionLimited=limit<1;
    this.pixelRatio=devicePixelRatio;
    if(width!==this.canvas.width||height!==this.canvas.height||!this.contactFramebuffer){this.canvas.width=width;this.canvas.height=height;this.revision++;this.gpu=null;this.resizeContact(width,height);}
  }
  resizeContact(width,height){
    const gl=this.gl;gl.deleteTexture(this.contactColor);gl.deleteTexture(this.contactDepth);gl.deleteTexture(this.contactResult);gl.deleteFramebuffer(this.contactFramebuffer);gl.deleteFramebuffer(this.contactResultFramebuffer);
    const texture=(format)=>{const t=gl.createTexture();gl.bindTexture(gl.TEXTURE_2D,t);gl.texStorage2D(gl.TEXTURE_2D,1,format,width,height);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MIN_FILTER,gl.NEAREST);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MAG_FILTER,gl.NEAREST);return t;};
    this.contactColor=texture(gl.RGBA8);this.contactDepth=texture(gl.DEPTH_COMPONENT24);this.contactFramebuffer=gl.createFramebuffer();gl.bindFramebuffer(gl.FRAMEBUFFER,this.contactFramebuffer);
    gl.framebufferTexture2D(gl.FRAMEBUFFER,gl.COLOR_ATTACHMENT0,gl.TEXTURE_2D,this.contactColor,0);gl.framebufferTexture2D(gl.FRAMEBUFFER,gl.DEPTH_ATTACHMENT,gl.TEXTURE_2D,this.contactDepth,0);
    if(gl.checkFramebufferStatus(gl.FRAMEBUFFER)!==gl.FRAMEBUFFER_COMPLETE)throw Error('WebGL: контактные тени, framebuffer incomplete');gl.bindFramebuffer(gl.FRAMEBUFFER,null);
    this.contactResult=texture(gl.R8);this.contactResultFramebuffer=gl.createFramebuffer();gl.bindFramebuffer(gl.FRAMEBUFFER,this.contactResultFramebuffer);gl.framebufferTexture2D(gl.FRAMEBUFFER,gl.COLOR_ATTACHMENT0,gl.TEXTURE_2D,this.contactResult,0);
    if(gl.checkFramebufferStatus(gl.FRAMEBUFFER)!==gl.FRAMEBUFFER_COMPLETE)throw Error('WebGL: буфер AO incomplete');gl.bindFramebuffer(gl.FRAMEBUFFER,null);
  }
  drawContact(matrix,eye){
    const gl=this.gl,{program,uniforms:u}=this.contactProgram;gl.bindFramebuffer(gl.FRAMEBUFFER,this.contactResultFramebuffer);gl.disable(gl.DEPTH_TEST);gl.disable(gl.CULL_FACE);gl.useProgram(program);
    gl.uniformMatrix4fv(u.inverseView,false,inverseMatrix(matrix,eye));gl.uniform3fv(u.camera,[0,0,0]);gl.uniform2f(u.size,this.canvas.width,this.canvas.height);
    gl.activeTexture(gl.TEXTURE1);gl.bindTexture(gl.TEXTURE_2D,this.contactDepth);gl.uniform1i(u.depthMap,1);
    gl.bindVertexArray(null);gl.drawArrays(gl.TRIANGLES,0,3);
    const combine=this.contactComposite,v=combine.uniforms;gl.bindFramebuffer(gl.FRAMEBUFFER,null);gl.useProgram(combine.program);gl.uniformMatrix4fv(v.inverseView,false,inverseMatrix(matrix,eye));gl.uniform2f(v.size,this.canvas.width,this.canvas.height);
    gl.activeTexture(gl.TEXTURE0);gl.bindTexture(gl.TEXTURE_2D,this.contactColor);gl.uniform1i(v.colorMap,0);gl.uniform1i(v.depthMap,1);gl.activeTexture(gl.TEXTURE2);gl.bindTexture(gl.TEXTURE_2D,this.contactResult);gl.uniform1i(v.contactMap,2);gl.drawArrays(gl.TRIANGLES,0,3);gl.enable(gl.DEPTH_TEST);gl.enable(gl.CULL_FACE);
  }
  overviewCamera(target){
    const previous=this.camera,camera={yaw:.12,pitch:1.03,distance:400,target:[...target]};
    try{
      this.camera=camera;
      camera.distance=overviewDistance(this.tileset.extentMetres*1.8,distance=>{
        camera.distance=distance;
        const selected=budgetTiles(this.tileset,super.chooseTiles(),camera.target,this.geometryBudget*.9,this.tileLimit,this.triangleBudget*.9);
        return !selected.limited;
      });
      return camera;
    }finally{this.camera=previous;}
  }
  chooseTiles(options={}){
    const selection=budgetTiles(this.tileset,super.chooseTiles(options),this.camera.target,this.geometryBudget,this.tileLimit,this.triangleBudget);
    Object.assign(this.streamStats,{budgetLimited:selection.limited,budgetBytes:this.geometryBudget,candidateTiles:selection.candidates});
    if(!selection.modes.size&&selection.candidates)throw Error('Даже один тайл превышает бюджет памяти WebGL. Нужен более лёгкий уровень детализации.');
    return selection.modes;
  }
  releaseMesh(c){const gl=this.gl;gl.deleteVertexArray(c.vao);gl.deleteBuffer(c.vertex);gl.deleteBuffer(c.index);this.streamStats.releasedGpuBytes+=c.vertexBytes+c.indexBytes;}
  uploadMesh(c){
    const gl=this.gl,vao=gl.createVertexArray(),vertexBuffer=gl.createBuffer(),index=gl.createBuffer();gl.bindVertexArray(vao);
    gl.bindBuffer(gl.ARRAY_BUFFER,vertexBuffer);gl.bufferData(gl.ARRAY_BUFFER,c.vertices,gl.STATIC_DRAW);
    for(const [location,size,type,normalized,offset] of [[0,3,gl.FLOAT,false,0],[1,2,gl.SHORT,true,12],[2,2,gl.FLOAT,false,16],[4,1,gl.FLOAT,false,28]]){
      gl.enableVertexAttribArray(location);gl.vertexAttribPointer(location,size,type,normalized,32,offset);
    }
    gl.enableVertexAttribArray(3);gl.vertexAttribIPointer(3,1,gl.UNSIGNED_INT,32,24);
    gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER,index);gl.bufferData(gl.ELEMENT_ARRAY_BUFFER,c.indices,gl.STATIC_DRAW);
    gl.bindBuffer(gl.ARRAY_BUFFER,this.instanceBuffer);
    for(let i=5;i<8;i++){gl.enableVertexAttribArray(i);gl.vertexAttribPointer(i,4,gl.FLOAT,false,48,(i-5)*16);gl.vertexAttribDivisor(i,1);}
    gl.bindVertexArray(null);
    return {...this.assets.get(c.id),vao,vertex:vertexBuffer,index};
  }
  async updateTiles(modes,{force=false}={}){
    const key=JSON.stringify([...modes]);if(!force&&key===this.streamKey)return;
    const started=performance.now();this.ready=false;this.loading=true;this.phase='Подгружаем участки';this.progress=0;this.publish(true);
    const active=activeChunkIds(this.tileset,modes);
    for(const [id,c] of this.rasterMeshes)if(!active.has(id)){this.releaseMesh(c);this.rasterMeshes.delete(id);}
    let upload=0,done=0;
    for(const id of active){
      if(!this.rasterMeshes.has(id)){
        const c=await this.mesh(id);if(!this.running)return;
        const t=performance.now();this.rasterMeshes.set(id,this.uploadMesh(c));upload+=performance.now()-t;
        this.trimCache(active);
      }
      this.progress=++done/active.size;this.publish();
    }
    const layout=rasterLayout(sceneInstances(this.tileset,modes),this.assets),gl=this.gl,t=performance.now();
    gl.bindBuffer(gl.ARRAY_BUFFER,this.instanceBuffer);gl.bufferData(gl.ARRAY_BUFFER,layout.transforms,gl.STATIC_DRAW);
    this.streamStats.releasedGpuBytes+=this.rasterInstanceBytes??0;this.rasterInstanceBytes=layout.transforms.byteLength;
    this.chunks=layout.draws.map(d=>({...this.rasterMeshes.get(d.id),...d}));
    this.stats.geometryBytes=[...this.rasterMeshes.values()].reduce((n,c)=>n+c.vertexBytes+c.indexBytes,0)+this.rasterInstanceBytes;
    this.stats.bvhBytes=0;this.stats.uploadMs=upload+performance.now()-t;this.stats.bvhBuildMs=0;
    this.streamStats.residentBytes=this.stats.geometryBytes;this.streamStats.peakResidentBytes=Math.max(this.streamStats.peakResidentBytes,this.stats.geometryBytes);
    this.tileModes=new Map(modes);this.streamKey=key;this.updateCounts();this.trimCache(active);
    const min=[Infinity,Infinity,Infinity],max=[-Infinity,-Infinity,-Infinity];
    for(const c of this.chunks)for(let a=0;a<3;a++){min[a]=Math.min(min[a],c.bounds.min[a]);max[a]=Math.max(max[a],c.bounds.max[a]);}
    const center=min.map((v,i)=>(v+max[i])/2),span=Math.max(50,Math.hypot(...min.map((v,i)=>max[i]-v))*.55);
    this.shadowMatrix=multiply(orthographic(span,.1,span*4),lookAt(this.sun.map((x,i)=>center[i]+x*span*2),center));
    this.assertGL('геометрия');this.revision++;this.gpu=null;this.lastTime=0;this.shadowDirty=true;this.shadowMs=null;
    this.stats.buildMs=performance.now()-started;this.ready=true;this.loading=false;
    this.streamStats.fullTiles=[...modes.values()].filter(m=>m==='full').length;this.streamStats.coarseTiles=modes.size-this.streamStats.fullTiles;
    this.publish(true);
  }
  draw(chunks){
    const gl=this.gl;
    for(const c of chunks){
      gl.bindVertexArray(c.vao);gl.bindBuffer(gl.ARRAY_BUFFER,this.instanceBuffer);
      for(let i=5;i<8;i++)gl.vertexAttribPointer(i,4,gl.FLOAT,false,48,c.instanceFirst*48+(i-5)*16);
      gl.drawElementsInstanced(gl.TRIANGLES,c.triangles*3,gl.UNSIGNED_INT,0,c.instanceCount);
    }
    gl.bindVertexArray(null);
  }
  pollTimer(){
    const gl=this.gl,ext=this.timerExtension;if(!ext)return;
    const disjoint=gl.getParameter(ext.GPU_DISJOINT_EXT);
    this.queries=this.queries.filter(q=>{
      if(!disjoint&&!gl.getQueryParameter(q.query,gl.QUERY_RESULT_AVAILABLE))return true;
      if(!disjoint&&q.revision===this.revision){this.gpu=gl.getQueryParameter(q.query,gl.QUERY_RESULT)/1e6;this.publish(true);}
      gl.deleteQuery(q.query);return false;
    });
    if(disjoint)this.gpu=null;
  }
  bindCityProgram(target,matrix,eye,shadowData,cascades,waterData){
    const gl=this.gl,P=this.waterSettings;
    const {program,uniforms:u}=target;gl.useProgram(program);
    gl.uniformMatrix4fv(u.view,false,matrix);gl.uniformMatrix4fv(u.shadow,false,shadowData.subarray(0,48));gl.uniform4fv(u.shadowParams,shadowData.subarray(48,60));gl.uniform1i(u.shadowCount,this.state.shadows?cascades.length:0);gl.uniform1ui(u.materialCount,this.state.materials);
    gl.uniform3fv(u.camera,eye);gl.uniform3fv(u.sun,this.sun);gl.uniform1f(u.sunPower,this.waterSettings.lighting==='hosek'?1:(this.sunPower??1));gl.uniform1f(u.exposure,this.state.exposure*(this.waterSettings.lighting==='ocean'?this.waterSettings.exposure/1.2:1));gl.uniform1f(u.shadowSize,this.shadowSize);
    if(target===this.mainProgram&&this.lightingRevision!==this.revision){this.lightingRevision=this.revision;this.canvas.dataset.lighting=JSON.stringify({texels:cascades.map(c=>c.params[0]),count:gl.getUniform(program,u.shadowCount),shadow:Array.from(gl.getUniform(program,u.shadow)),shadowSize:gl.getUniform(program,u.shadowSize)});}
    gl.activeTexture(gl.TEXTURE0);gl.bindTexture(gl.TEXTURE_2D_ARRAY,this.albedo);gl.uniform1i(u.albedo,0);
    gl.activeTexture(gl.TEXTURE1);gl.bindTexture(gl.TEXTURE_2D,this.materialTexture);gl.uniform1i(u.materials,1);
    gl.activeTexture(gl.TEXTURE2);gl.bindTexture(gl.TEXTURE_2D_ARRAY,this.shadowTexture);gl.uniform1i(u.shadowMap,2);
    gl.activeTexture(gl.TEXTURE3);gl.bindTexture(gl.TEXTURE_2D,this.facadeNormal);gl.uniform1i(u.facadeNormal,3);
    gl.activeTexture(gl.TEXTURE4);gl.bindTexture(gl.TEXTURE_2D,this.surfaceField);gl.uniform1i(u.surfaceField,4);gl.uniform1f(u.waterTime,this.waterClock.time);
    gl.uniform4fv(u.waterP,waterData);
    if(P.lighting==='hosek')gl.uniform4fv(u.hwP,this.hosekCache.update(this.sun,P));
  }
  frame(time){
    if(!this.running)return;this.raf=requestAnimationFrame(t=>this.frame(t));
    if(document.hidden){this.waterClock.last=null;this.lastTime=0;return;}
    if(this.pixelRatio!==devicePixelRatio)this.resize();if(!this.ready)return;
    this.pollTimer();if(!this.waterFrame(time))return;
    const gl=this.gl,c=this.camera,aspect=this.canvas.width/this.canvas.height;
    const eye=[Math.sin(c.yaw)*Math.cos(c.pitch)*c.distance+c.target[0],Math.sin(c.pitch)*c.distance+c.target[1],Math.cos(c.yaw)*Math.cos(c.pitch)*c.distance+c.target[2]];
    const fov=2*Math.atan(Math.tan(44*Math.PI/360)*Math.max(1,1.1/aspect));
    const matrix=multiply(perspective(fov,aspect,1,this.tileset.extentMetres*6),lookAt(eye,c.target));
    const chunks=this.chunks.filter(c=>this.isChunkVisible(c)&&visible(c.bounds,matrix));
    this.pollTimer();let query;
    if(this.timerExtension&&this.queries.length<3){query=gl.createQuery();gl.beginQuery(this.timerExtension.TIME_ELAPSED_EXT,query);}
    let shadowDraws=0;const cascades=sunCascades(this,this.shadowSize),shadowData=shadowUniform(cascades,this.shadowSize);
    if(this.state.shadows){
      const {program,uniforms:u}=this.shadowProgram;gl.useProgram(program);gl.bindFramebuffer(gl.FRAMEBUFFER,this.shadowFramebuffer);gl.viewport(0,0,this.shadowSize,this.shadowSize);
      for(let i=0;i<cascades.length;i++){
        const c=cascades[i];if(!this.shadowDirty&&this.shadowKeys[i]===c.key)continue;
        gl.uniformMatrix4fv(u.view,false,c.matrix);gl.framebufferTextureLayer(gl.FRAMEBUFFER,gl.DEPTH_ATTACHMENT,this.shadowTexture,0,i);gl.clearDepth(1);gl.clear(gl.DEPTH_BUFFER_BIT);
        gl.enable(gl.POLYGON_OFFSET_FILL);gl.polygonOffset(1,1);const casters=this.chunks.filter(mesh=>this.isChunkVisible(mesh)&&visible(mesh.bounds,c.matrix));shadowDraws+=casters.length;this.draw(casters);gl.disable(gl.POLYGON_OFFSET_FILL);this.shadowKeys[i]=c.key;
      }
      this.shadowDirty=false;
    }
    gl.bindFramebuffer(gl.FRAMEBUFFER,this.state.contactAO?this.contactFramebuffer:null);gl.viewport(0,0,this.canvas.width,this.canvas.height);
    gl.clearColor(.70,.735,.745,1);gl.clearDepth(1);gl.clear(gl.COLOR_BUFFER_BIT|gl.DEPTH_BUFFER_BIT);
    const P=this.waterSettings;const waterData=new Float32Array([P.windSpeed,P.windDir*Math.PI/180,P.fetchKm,P.choppy,P.swellHs,P.swellLength,P.swellDir*Math.PI/180,P.turbidity,P.foam,P.shoreFoam,P.haze,P.clouds,P.veil,P.lighting==='classic'?1:P.lighting==='seascape'?2:P.lighting==='blend'?3:P.lighting==='hosek'?4:0,P.waterModel==='seascape'?1:0,P.lightingMix/100,P.seaHeight,P.seaFrequency,P.seaChoppy,P.seaSpeed,P.seaExposure,P.sunIntensity/100,P.shadowStrength/100,0,...absorptionCoefficients(P),P.waterIOR,...linearColor(P.scatteringColor),0]);
    const bindCapture=(target,m,e)=>this.bindCityProgram(target,m,e,shadowData,cascades,waterData);
    const reflectionDraws=this.reflection.draw(matrix,eye,bindCapture)+this.groundReflection.draw(matrix,eye,bindCapture);
    gl.bindFramebuffer(gl.FRAMEBUFFER,this.state.contactAO?this.contactFramebuffer:null);gl.viewport(0,0,this.canvas.width,this.canvas.height);
    this.bindCityProgram(this.mainProgram,matrix,eye,shadowData,cascades,waterData);this.reflection.bind(this.mainProgram.uniforms);this.groundReflection.bind(this.mainProgram.uniforms);
    this.draw(chunks);
    if(P.lighting!=='classic'){
    const sky=this.waterSkyProgram;gl.useProgram(sky.program);gl.disable(gl.CULL_FACE);gl.depthFunc(gl.LEQUAL);gl.depthMask(false);gl.bindVertexArray(null);
    const fwd=normalize(c.target.map((x,i)=>x-eye[i])),right=normalize([ -fwd[2],0,fwd[0]]),up=[right[1]*fwd[2]-right[2]*fwd[1],right[2]*fwd[0]-right[0]*fwd[2],right[0]*fwd[1]-right[1]*fwd[0]],tanY=Math.tan(fov/2);
    gl.uniform3fv(sky.uniforms.camForward,fwd);gl.uniform3fv(sky.uniforms.camRight,right.map(x=>x*tanY*aspect));gl.uniform3fv(sky.uniforms.camUp,up.map(x=>x*tanY));
    gl.uniform3fv(sky.uniforms.sun,this.sun);gl.uniform1f(sky.uniforms.sunPower,this.sunPower??1);gl.uniform1f(sky.uniforms.waterTime,this.waterClock.time);gl.uniform4fv(sky.uniforms.waterP,waterData);gl.uniform1f(sky.uniforms.exposure,P.lighting==='seascape'?P.seaExposure:P.exposure);
    if(P.lighting==='hosek')gl.uniform4fv(sky.uniforms.hwP,this.hosekCache.update(this.sun,P));
    gl.drawArrays(gl.TRIANGLES,0,3);gl.depthMask(true);gl.depthFunc(gl.LESS);gl.enable(gl.CULL_FACE);
    }
    this.canvas.dataset.water=JSON.stringify({time:this.waterClock.time,renders:this.waterRenders=(this.waterRenders||0)+1,animated:P.animated,backend:'WebGL',waterModel:P.waterModel,lighting:P.lighting,lightingMix:P.lightingMix,sunIntensity:P.sunIntensity,shadowStrength:P.shadowStrength,settings:this.waterRevision||0});
    if(this.state.contactAO)this.drawContact(matrix,eye);
    if(query){gl.endQuery(this.timerExtension.TIME_ELAPSED_EXT);this.queries.push({query,revision:this.revision});}
    this.stats.submitted=chunks.reduce((n,c)=>n+c.triangles*c.instanceCount,0);this.stats.draws=chunks.length+(this.state.contactAO?2:0)+shadowDraws+reflectionDraws+(P.lighting!=='classic'?1:0);
    const dt=this.lastTime?time-this.lastTime:16.7;this.lastTime=time;this.frameMs=this.frameMs*.92+dt*.08;this.publish();
  }
  dispose(){
    this.running=false;cancelAnimationFrame(this.raf);this.resizeObserver?.disconnect();this.canvas.removeEventListener('webglcontextlost',this.onContextLost);
    const gl=this.gl;if(!gl)return;this.groundReflection?.dispose();this.reflection?.dispose();
    for(const c of this.rasterMeshes.values())this.releaseMesh(c);this.rasterMeshes.clear();this.meshCache.clear();
    gl.deleteBuffer(this.instanceBuffer);gl.deleteTexture(this.albedo);gl.deleteTexture(this.materialTexture);gl.deleteTexture(this.shadowTexture);
    for(const texture of [this.surfaceField,this.facadeNormal,this.contactColor,this.contactDepth,this.contactResult])gl.deleteTexture(texture);gl.deleteFramebuffer(this.contactFramebuffer);gl.deleteFramebuffer(this.contactResultFramebuffer);gl.deleteProgram(this.waterSkyProgram?.program);gl.deleteProgram(this.contactProgram?.program);gl.deleteProgram(this.contactComposite?.program);
    gl.deleteFramebuffer(this.shadowFramebuffer);gl.deleteProgram(this.mainProgram?.program);gl.deleteProgram(this.shadowProgram?.program);
    this.queries.forEach(q=>gl.deleteQuery(q.query));
    gl.getExtension('WEBGL_lose_context')?.loseContext();
  }
}
