export function pan(camera,dx,dy){
  const k=camera.distance*.0014;
  camera.target[0]-=(Math.cos(camera.yaw)*dx+Math.sin(camera.yaw)*dy)*k;
  camera.target[2]+=(Math.sin(camera.yaw)*dx-Math.cos(camera.yaw)*dy)*k;
}
export function pinch(camera,before,after,maxDistance){
  const span=p=>Math.hypot(p[1].x-p[0].x,p[1].y-p[0].y);
  const a=span(before),b=span(after);
  if(a>2&&b>2)camera.distance=Math.max(8,Math.min(maxDistance,camera.distance*a/b));
  pan(camera,(after[0].x+after[1].x-before[0].x-before[1].x)/2,(after[0].y+after[1].y-before[0].y-before[1].y)/2);
}
export function bindCameraInput(canvas,getRenderer,isReady,onMove){
  const pointers=new Map(),point=e=>({x:e.clientX,y:e.clientY});
  const max=r=>Math.max(1800,r.tileset.extentMetres*2.3);
  canvas.onpointerdown=e=>{if(!isReady())return;canvas.setPointerCapture(e.pointerId);pointers.set(e.pointerId,point(e));};
  const end=e=>{pointers.delete(e.pointerId);};
  canvas.onpointerup=end;canvas.onpointercancel=end;canvas.onlostpointercapture=end;
  canvas.onpointermove=e=>{
    if(!pointers.has(e.pointerId)||!isReady())return;
    const before=[...pointers.values()],old=pointers.get(e.pointerId);pointers.set(e.pointerId,point(e));
    const r=getRenderer(),c=r.camera,after=[...pointers.values()];
    if(pointers.size===2)pinch(c,before,after,max(r));
    else if(pointers.size===1){
      const dx=e.clientX-old.x,dy=e.clientY-old.y;
      if(e.shiftKey||e.buttons===2)pan(c,dx,dy);
      else{c.yaw-=dx*.006;c.pitch=Math.max(.08,Math.min(1.565,c.pitch+dy*.006));}
    }else return;
    onMove();
  };
  canvas.oncontextmenu=e=>e.preventDefault();
  canvas.addEventListener('wheel',e=>{e.preventDefault();if(!isReady())return;
    const r=getRenderer();r.camera.distance=Math.max(8,Math.min(max(r),r.camera.distance*Math.exp(e.deltaY*.001)));onMove();
  },{passive:false});
}
