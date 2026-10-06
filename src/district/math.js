export const normalize=v=>{const n=Math.hypot(...v);return v.map(x=>x/n);};
export const cross=(a,b)=>[a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]];
const dot=(a,b)=>a.reduce((n,v,i)=>n+v*b[i],0);
export function multiply(a,b){
  const out=new Float32Array(16);
  for(let c=0;c<4;c++)for(let r=0;r<4;r++)for(let k=0;k<4;k++)out[c*4+r]+=a[k*4+r]*b[c*4+k];return out;
}
export function lookAt(eye,target){
  const z=normalize(eye.map((v,i)=>v-target[i])),x=normalize(cross([0,1,0],z)),y=cross(z,x);
  return new Float32Array([x[0],y[0],z[0],0,x[1],y[1],z[1],0,x[2],y[2],z[2],0,-dot(x,eye),-dot(y,eye),-dot(z,eye),1]);
}
export function perspective(fov,aspect,near,far,reverse=false){const f=1/Math.tan(fov/2);return new Float32Array([f/aspect,0,0,0,0,f,0,0,0,0,reverse?near/(far-near):far/(near-far),-1,0,0,reverse?far*near/(far-near):far*near/(near-far),0]);}
export function orthographic(size,near,far){return new Float32Array([1/size,0,0,0,0,1/size,0,0,0,0,1/(near-far),0,0,0,near/(near-far),1]);}
export function visible(bounds,matrix){
  const planes=Array.from({length:6},()=>0);
  for(let bits=0;bits<8;bits++){
    const p=[0,1,2].map(i=>(bits&(1<<i))?bounds.max[i]:bounds.min[i]);
    const c=[0,1,2,3].map(i=>matrix[i]*p[0]+matrix[4+i]*p[1]+matrix[8+i]*p[2]+matrix[12+i]);
    [c[0]<-c[3],c[0]>c[3],c[1]<-c[3],c[1]>c[3],c[2]<0,c[2]>c[3]].forEach((v,i)=>{if(v)planes[i]++;});
  }
  return !planes.some(n=>n===8);
}
