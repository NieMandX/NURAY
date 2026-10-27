import {reflectionState,reflectionChunks,reflectionParameters} from '../../src/district/ocean/planar-math.js?v=dry-ground-1';
export class WebGLReflection {
 constructor(owner,program,ground=false){this.ground=ground;this.name=ground?'groundReflection':'reflection';this.o=owner;this.gl=owner.gl;this.program=program;this.updates=0;this.resize([1,1]);}
 resize(size){
  if(String(size)===String(this.size))return;
  const g=this.gl;this.disposeTargets();this.size=size;this.key=null;
  this.color=g.createTexture();g.bindTexture(g.TEXTURE_2D,this.color);g.texImage2D(g.TEXTURE_2D,0,g.RGBA8,...size,0,g.RGBA,g.UNSIGNED_BYTE,null);
  for(const [key,value] of [[g.TEXTURE_MIN_FILTER,g.LINEAR],[g.TEXTURE_MAG_FILTER,g.LINEAR],[g.TEXTURE_WRAP_S,g.CLAMP_TO_EDGE],[g.TEXTURE_WRAP_T,g.CLAMP_TO_EDGE]])g.texParameteri(g.TEXTURE_2D,key,value);
  this.depth=g.createRenderbuffer();g.bindRenderbuffer(g.RENDERBUFFER,this.depth);g.renderbufferStorage(g.RENDERBUFFER,g.DEPTH_COMPONENT24,...size);
  this.framebuffer=g.createFramebuffer();g.bindFramebuffer(g.FRAMEBUFFER,this.framebuffer);g.framebufferTexture2D(g.FRAMEBUFFER,g.COLOR_ATTACHMENT0,g.TEXTURE_2D,this.color,0);g.framebufferRenderbuffer(g.FRAMEBUFFER,g.DEPTH_ATTACHMENT,g.RENDERBUFFER,this.depth);
  if(g.checkFramebufferStatus(g.FRAMEBUFFER)!==g.FRAMEBUFFER_COMPLETE)throw Error('Не удалось создать буфер отражения WebGL');
  g.bindFramebuffer(g.FRAMEBUFFER,null);
 }
 draw(matrix,eye,bind){
  const o=this.o,g=this.gl,state=reflectionState(o,matrix,eye,this.ground);this.state=state;let draws=0;
  if(state){
   this.resize(state.size);
   if(this.key!==state.key||this.chunks!==o.chunks){
    g.bindFramebuffer(g.FRAMEBUFFER,this.framebuffer);g.viewport(0,0,...state.size);g.clearColor(0,0,0,0);g.clearDepth(1);g.clear(g.COLOR_BUFFER_BIT|g.DEPTH_BUFFER_BIT);g.frontFace(g.CW);
    bind(this.program,state.matrix,state.eye);g.uniform1f(this.program.uniforms.captureHeight,state.height);
    const meshes=reflectionChunks(o,state.matrix,state.height,this.ground);o.draw(meshes);draws=meshes.length;this.triangles=meshes.reduce((n,c)=>n+c.triangles*c.instanceCount,0);
    g.frontFace(g.CCW);this.updates++;this.key=state.key;this.chunks=o.chunks;
   }
  }
  o.canvas.dataset[this.name]=JSON.stringify({enabled:!!state,height:state?.height,size:this.size,updates:this.updates,triangles:this.triangles??0,bytes:this.size[0]*this.size[1]*8});o.syncReflectionStatus?.();return draws;
 }
 bind(uniforms){
  const g=this.gl,p=reflectionParameters(this.o.waterSettings,this.ground),s=this.state,unit=this.ground?6:5,k=this.name;
  g.activeTexture(g.TEXTURE0+unit);g.bindTexture(g.TEXTURE_2D,this.color);g.uniform1i(uniforms[k+'Map'],unit);
  g.uniform3f(uniforms[k+'Size'],...this.size,s?1:0);
  if(s){g.uniformMatrix4fv(uniforms[k+'View'],false,s.matrix);g.uniform4f(uniforms[k+'Params'],s.height,p.strength,p.blur,p.distortion);}
 }
 disposeTargets(){const g=this.gl;g.deleteTexture(this.color);g.deleteRenderbuffer(this.depth);g.deleteFramebuffer(this.framebuffer);}
 dispose(){this.disposeTargets();if(!this.ground)this.gl.deleteProgram(this.program.program);}
}
