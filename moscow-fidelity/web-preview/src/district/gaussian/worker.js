import {selectPlants,sortedPairs} from './model.js';
let scene;
self.onmessage=({data})=>{
  try{
    if(data.type==='init'){scene=data;postMessage({type:'ready'});return;}
    if(!scene)return;
    const start=performance.now(),{matrix,width,height,budget,key}=data;
    const chosen=selectPlants(scene.instances,scene.models,matrix,width,height,budget);
    const pairs=sortedPairs(chosen,scene.instances,scene.models,scene.points,matrix);
    postMessage({type:'sorted',key,pairs,active:chosen.map(x=>x.id),ms:performance.now()-start},[pairs.buffer]);
  }catch(e){postMessage({type:'error',message:e.message});}
};
