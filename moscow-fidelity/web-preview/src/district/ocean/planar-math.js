import {isStandardGround,upwardPackedNormal} from '../ground-surfaces.js?v=ground-reflections-1';
import {multiply,visible} from '../math.js';

export function reflectedView(view,height){
 return multiply(view,new Float32Array([1,0,0,0,0,-1,0,0,0,0,1,0,0,2*height,0,1]));
}
export const reflectedEye=(eye,height)=>[eye[0],2*height-eye[1],eye[2]];
export function reflectionSize(width,height,quality=50){
 const scale=Math.min(1,quality/100,1536/Math.max(width,height));
 return [Math.max(1,Math.round(width*scale)),Math.max(1,Math.round(height*scale))];
}
// Sparse surface-height indices, not a second copy of city geometry. Ground
// separates overlapping levels and ignores vertical faces of the same material.
// A local plane is safer than a city-wide Y=0 for both terrain and source water.
export class WaterHeights {
 constructor(ground=false){this.ground=ground;this.cells=new Map();this.seen=new Set();this.version=0;}
 add(id,bytes,materials,instanced=false){
  if(instanced||this.seen.has(id))return;this.seen.add(id);
  const surfaces=new Set(materials.flatMap((m,i)=>(this.ground?isStandardGround(m):m.kind===12)?[i]:[]));
  const buffer=bytes.buffer??bytes,offset=bytes.byteOffset??0,length=bytes.byteLength/4;
  const f=new Float32Array(buffer,offset,length),u=new Uint32Array(buffer,offset,length);
  for(let i=0;i+7<length;i+=8){
   if(!(u[i+6]&0x80000000)||!surfaces.has(u[i+6]&0x7fffffff))continue;
   if(this.ground&&!upwardPackedNormal(u[i+3]))continue;
   const x=f[i],y=f[i+1],z=f[i+2];if(!Number.isFinite(x+y+z))continue;
   const key=Math.floor(x/16)+','+Math.floor(z/16)+(this.ground?','+Math.floor(y/2):''),p=this.cells.get(key)??[0,0,0,0];
   p[0]+=x;p[1]+=y;p[2]+=z;p[3]++;this.cells.set(key,p);
  }
  this.version++;
 }
 height(target,view){
  const key=JSON.stringify([target,Array.from(view),this.version]);
  if(key===this.heightKey)return this.lastHeight;
  let best=Infinity,point;
  for(const p of this.cells.values()){
   const v=p.slice(0,3).map(x=>x/p[3]);
   if(!visible({min:v,max:v},view))continue;
   const d=(v[0]-target[0])**2+(v[2]-target[2])**2;
   if(d<best){best=d;point=v;}
  }
  this.heightKey=key;return this.lastHeight=point?.[1]??null;
 }
}
// Waves, blur and strength only change sampling. They must not re-render the city.
export function reflectionKey(o,height,size,ground=false){
 const p=o.waterSettings;
 return JSON.stringify([o.camera,o.sun,o.sunPower,o.sceneLayers,o.state.textures,o.state.shadows,o.stats.geometryBytes,
  o.chunks.length,(ground?o.groundHeights:o.waterHeights).version,height,size,ground?p.groundReflectionDetail:p.reflectionDetail,p.lighting,p.hwTurbidity,p.hwAlbedo,
  p.hwSkyIntensity,p.sunIntensity,p.shadowStrength]);
}
export function reflectionChunks(o,matrix,height,ground=false){
 return o.chunks.filter(c=>o.isChunkVisible(c)&&c.bounds.max[1]>height+.03&&visible(c.bounds,matrix)&&
  ((ground?o.waterSettings.groundReflectionDetail:o.waterSettings.reflectionDetail)||!(c.instanceCount>1||c.instanced||c.layer||/^street-/.test(c.name??''))));
}
export function reflectionState(o,matrix,eye,ground=false){
 const p=reflectionParameters(o.waterSettings,ground);
 if(!p.enabled)return null;
 const height=(ground?o.groundHeights:o.waterHeights).height(o.camera.target,matrix);
 if(height===null||eye[1]<=height+.1)return null;
 const size=reflectionSize(o.canvas.width,o.canvas.height,p.quality);
 return {height,size,matrix:reflectedView(matrix,height),eye:reflectedEye(eye,height),key:reflectionKey(o,height,size,ground)};
}

export function reflectionParameters(p,ground=false){
 const key=ground?'groundReflection':'reflection';
 return {enabled:p[key+'Enabled'],quality:p[key+'Quality'],strength:p[key+'Strength']/100,blur:p[key+'Blur'],distortion:ground?0:p.reflectionDistortion};
}
