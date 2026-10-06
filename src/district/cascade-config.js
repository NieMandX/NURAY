// The same interval/angular hierarchy as the sphere experiment, sized for meshes.
export const CASCADE_LEVELS = [
  [16,8,16,4], [8,4,8,8], [4,2,4,16], [2,1,2,32],
];
export const CACHE_LIMIT=16;
export function cacheField(camera,city=false,previous=null){
  const minimum=city?256:32, maximum=city?8192:256;
  const wanted=Math.max(minimum,Math.min(maximum,camera.distance*.8));
  if(previous && wanted>=previous.size[0]*.35 && wanted<=previous.size[0] &&
    camera.target.every((x,i)=>i===1 ? x>=previous.min[1]&&x<=previous.min[1]+previous.size[1]*.8 : Math.abs(x-previous.center[i])<=previous.size[i]*.3))return previous;
  const span=2**Math.ceil(Math.log2(wanted)),height=Math.min(span,city?512:64);
  const size=[span,height,span],step=span/4;
  const min=[Math.round(camera.target[0]/step)*step-span/2,
    Math.max(city?-8:-1,Math.floor((camera.target[1]-height*.4)/(height/4))*(height/4)),
    Math.round(camera.target[2]/step)*step-span/2];
  const center=min.map((x,i)=>x+size[i]/2);
  return {min,size,center,key:[...min,...size].join(',')};
}
export const cascadeBytes=()=>CASCADE_LEVELS.reduce((n,d)=>n+d[0]*d[1]*d[2]*d[3]*d[3]*16,0)+16*8*16*6*16;
