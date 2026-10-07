import {cityBase} from './city-config.js?v=fidelity-2';
import {buildMeshBvh,planTracePages,transformBounds} from './bvh.js?v=sah-1';
let resume;
self.onmessage=async({data})=>{
  if(data.type==='ack'){resume?.();return;}
  if(data.type!=='build')return;
  try{
    let bvhMs=0;const strategy=data.bvhStrategy??'sah';
    const start=performance.now(),scene=data.scene,base=cityBase;
    const perMesh=scene.chunks.map(()=>[]);for(const i of scene.instances)perMesh[i.mesh].push(i.matrix);
    const transforms=new Float32Array(scene.instances.length*12);let offset=0;
    const info=scene.chunks.map((c,i)=>{
      const first=offset;for(const m of perMesh[i]){transforms.set(m,offset*12);offset++;}
      const bs=perMesh[i].map(m=>transformBounds(c.bounds,m));
      return {...c,instanceFirst:first,instanceCount:perMesh[i].length,renderBounds:{min:[0,1,2].map(a=>Math.min(...bs.map(b=>b.min[a]))),max:[0,1,2].map(a=>Math.max(...bs.map(b=>b.max[a])))}};
    });
    self.postMessage({type:'plan',triangles:scene.stats.uniqueTriangles,groups:scene.chunks.length,expanded:scene.stats.expandedTriangles,transforms:transforms.buffer},[transforms.buffer]);
    const chunks=[];
    // Overlap network latency while keeping only six decoded chunks in flight.
    const read=async c=>{
      const r=await fetch(new URL(c.file,base));if(!r.ok)throw new Error('Не найден '+c.file);
      const bytes=await new Response(r.body.pipeThrough(new DecompressionStream('gzip'))).arrayBuffer();
      if(bytes.byteLength!==c.vertexBytes+c.triangles*12)throw new Error('Повреждён блок '+c.file);
      return bytes;
    };
    const pending=new Map();
    const schedule=i=>{if(i<info.length)pending.set(i,read(info[i]).then(bytes=>({bytes}),error=>({error})));};
    for(let i=0;i<6;i++)schedule(i);
    for(let i=0;i<info.length;i++){
      const c=info[i],result=await pending.get(i);pending.delete(i);schedule(i+6);
      if(result.error)throw result.error;const bytes=result.bytes;
      const mesh={vertices:bytes.slice(0,c.vertexBytes),indices:bytes.slice(c.vertexBytes)};
      if(data.trace){const begin=performance.now();chunks.push({...c,...buildMeshBvh(mesh,strategy)});bvhMs+=performance.now()-begin;self.postMessage({type:'progress',completed:i+1});}
      else{
        const ack=new Promise(resolve=>{resume=resolve;});self.postMessage({type:'chunk',...c,...mesh,completed:i+1},[mesh.vertices,mesh.indices]);await ack;resume=null;
      }
    }
    if(data.trace){
      const begin=performance.now(),plan=planTracePages(chunks,data.limit,scene.instances,strategy);bvhMs+=performance.now()-begin;
      self.postMessage({type:'trace-plan',sizes:plan.sizes,scene:plan.scene},[plan.scene]);
      for(let i=0;i<chunks.length;i++){
        const c=chunks[i],ack=new Promise(resolve=>{resume=resolve;});
        self.postMessage({type:'trace-chunk',...c,descriptor:plan.descriptors[i],completed:i+1},[c.vertices,c.indices,c.nodes]);chunks[i]=null;await ack;resume=null;
      }
    }
    self.postMessage({type:'done',bvhMs,bvhStrategy:strategy,elapsed:performance.now()-start});
  }catch(error){self.postMessage({type:'error',message:error.message});}
};
