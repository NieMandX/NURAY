import {createBooleanSurface,simplifySurface} from './boolean-surface.js';
let source,queue=Promise.resolve();
self.onmessage=({data})=>{
  // Serialize jobs, including WASM initialization; the UI coalesces slider requests.
  queue=queue.then(async()=>{
    try{
      if(data.type==='build')source=await createBooleanSurface(data.editor,data.settings);
      if(!source)throw Error('Сначала постройте Boolean-оболочку');
      const surface=data.type==='build'?source:await simplifySurface(source,data.optimize);
      self.postMessage({id:data.id,surface});
    }catch(error){self.postMessage({id:data.id,error:error.message||String(error)});}
  });
};
