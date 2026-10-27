export const isFacade=m=>m.family==='generated-facade-storeys';
export function facadePixels(width=8,height=512,normal=false){
 const pixels=new Uint8Array(width*height*4);
 for(let y=0;y<height;y++){
  const v=(y+.5)/height,d=Math.min(v,1-v)*3,t=Math.max(0,Math.min(1,(d-.012)/.028));
  const smooth=t*t*(3-2*t),color=.045+.955*smooth;
  const slope=.018*6*t*(1-t)/.028*(v<.5?1:-1),length=Math.hypot(slope,1);
  const s=color<.0031308?12.92*color:1.055*color**(1/2.4)-.055;
  const rgba=normal?[128,Math.round((-.5*slope/length+.5)*255),Math.round((.5/length+.5)*255),255]:[Math.round(s*255),Math.round(s*255),Math.round(s*255),255];
  for(let x=0;x<width;x++)pixels.set(rgba,(y*width+x)*4);
 }
 return pixels;
}
