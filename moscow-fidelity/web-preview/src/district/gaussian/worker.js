import {selectPlants,sortedPairs,plantBounds} from './model.js?v=gs-15';
let scene;
self.onmessage=({data})=>{
  try{
    if(data.type==='init'){scene={...data,bounds:plantBounds(data.instances,data.models)};postMessage({type:'ready'});return;}
    if(!scene)return;
    const start=performance.now(),{matrix,width,height,budget,key,eye,channel='main'}=data;
    const chosen=selectPlants(scene.instances,scene.models,matrix,width,height,budget,eye,scene.bounds,true);
    const pairs=sortedPairs(chosen,scene.instances,scene.models,scene.points,matrix);
    postMessage({type:'sorted',channel,key,pairs,active:chosen.filter(x=>x.visible&&x.size>=.4).map(x=>x.id),ms:performance.now()-start},[pairs.buffer]);
  }catch(e){postMessage({type:'error',message:e.message});}
};
