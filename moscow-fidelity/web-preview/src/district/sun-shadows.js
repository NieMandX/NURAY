import {normalize,cross,multiply,orthographic,lookAt} from './math.js?v=moscow-defaults-1';
const dot=(a,b)=>a.reduce((s,x,i)=>s+x*b[i],0);
// Nested light-space clipmaps. Fine maps follow the orbit target, while the
// outer map retains the entire city. Quantized centres keep stationary texels
// stable and cache maps until geometry or the quantized focus changes.
export function sunCascades(owner,size=2048){
  if(owner.sceneName!=='moscow'){const m=owner.shadowMatrix,texel=2/(size*Math.hypot(m[0],m[4],m[8])),depth=1/Math.hypot(m[2],m[6],m[10]);return [{matrix:m,params:[texel,(.008+texel*.85)/depth,Math.min(.12,.004+texel*.12),1],key:Array.from(m).join(',')}];}
  const extent=owner.city.extentMetres,far=Math.max(256,extent*.8),sun=owner.sun;
  const right=normalize(cross([0,1,0],sun)),up=cross(sun,right);
  const near=Math.min(far/8,Math.max(32,2**Math.ceil(Math.log2(owner.camera.distance*.55))));
  const b=owner.city.boundsMSK,o=owner.city.origin;
  const regionCenter=b&&o?[(b[0]+b[2])/2-o[0],0,o[1]-(b[1]+b[3])/2]:[0,0,0];
  const spans=[near,Math.min(far/2,Math.max(256,near*4)),far];
  return spans.map((half,i)=>{
    const focus=i===2?regionCenter:owner.camera.target,step=half/8;
    const coords=[right,up,sun].map((axis,j)=>Math.round(dot(focus,axis)/(j===2?64:step))*(j===2?64:step));
    const center=[0,1,2].map(k=>right[k]*coords[0]+up[k]*coords[1]+sun[k]*coords[2]);
    const depth=Math.max(2000,half*4),eye=center.map((v,k)=>v+sun[k]*depth/2),texel=2*half/size;
    return {matrix:multiply(orthographic(half,.1,depth),lookAt(eye,center)),
      params:[texel,(.008+texel*.85)/depth,Math.min(.12,.004+texel*.12),1],
      key:[half,depth,...coords,...sun].join(',')};
  });
}
export function shadowUniform(cascades,size){
 const data=new Float32Array(64);
 for(let i=0;i<3;i++){const c=cascades[Math.min(i,cascades.length-1)];data.set(c.matrix,i*16);data.set(c.params,48+i*4);}
 data.set([size,cascades.length,0,0],60);return data;
}
export function inverseMatrix(m,origin=[0,0,0]){
 // Pivoted Gauss-Jordan in double precision; matrices are column-major.
 const a=Array.from({length:4},(_,r)=>Array.from({length:8},(_,c)=>c<4?m[c*4+r]:(c-4===r?1:0)));
 for(let i=0;i<4;i++){
  let pivot=i;for(let j=i+1;j<4;j++)if(Math.abs(a[j][i])>Math.abs(a[pivot][i]))pivot=j;
  if(Math.abs(a[pivot][i])<1e-15)throw Error('Singular camera matrix');
  [a[i],a[pivot]]=[a[pivot],a[i]];const v=a[i][i];a[i]=a[i].map(x=>x/v);
  for(let j=0;j<4;j++)if(j!==i){const f=a[j][i];a[j]=a[j].map((x,k)=>x-f*a[i][k]);}
 }
 return Float32Array.from({length:16},(_,i)=>a[i%4][4+Math.floor(i/4)]-(i%4<3?origin[i%4]*a[3][4+Math.floor(i/4)]:0));
}
