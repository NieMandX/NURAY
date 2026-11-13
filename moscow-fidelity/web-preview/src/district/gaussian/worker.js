import {selectPlants,sortedPairs,plantBounds} from './model.js?v=gs-16';
let scene;const previousViews=new Map();
self.onmessage=({data})=>{
  try{
    if(data.type==='init'){scene={...data,bounds:plantBounds(data.instances,data.models)};postMessage({type:'ready'});return;}
    if(!scene)return;
    const start=performance.now(),{matrix,width,height,budget,key,eye,channel='main'}=data;
    const chosen=selectPlants(scene.instances,scene.models,matrix,width,height,budget,eye,scene.bounds,true,previousViews.get(channel));
    previousViews.set(channel,chosen);
    const pairs=sortedPairs(chosen,scene.instances,scene.models,scene.points,matrix);
    const visible=chosen.filter(x=>x.visible&&x.size>=.4);
    const detail={visibleSplats:visible.reduce((n,x)=>n+x.count,0),examples:[...visible].sort((a,b)=>b.size-a.size).slice(0,5).map(x=>({id:x.id,points:x.count,pixels:Math.round(x.size)}))};
    postMessage({type:'sorted',channel,key,pairs,detail,active:chosen.filter(x=>x.visible&&x.size>=.4).map(x=>x.id),ms:performance.now()-start},[pairs.buffer]);
  }catch(e){postMessage({type:'error',message:e.message});}
};
