import {makeDistrict,tessellateGroup} from './geometry.js';
import {buildMeshBvh,planTracePages} from './bvh.js?v=sah-1';
let resume;
self.onmessage=async({data})=>{
  if(data.type==='ack'){resume?.();return;}
  if(data.type!=='build')return;
  try{
    let bvhMs=0;const strategy=data.bvhStrategy??'sah';
    const started=performance.now(),scene=makeDistrict(data.triangles);
    self.postMessage({type:'plan',triangles:scene.triangles,vertices:scene.vertices,bytes:scene.bytes,groups:scene.groups.length});
    if(data.trace){
      const chunks=[];
      for(let i=0;i<scene.groups.length;i++){
        const g=scene.groups[i],mesh=tessellateGroup(g),begin=performance.now();const built=buildMeshBvh(mesh,strategy);bvhMs+=performance.now()-begin;chunks.push({...built,bounds:g.bounds,id:g.id,triangles:g.triangleCount,vertexCount:g.vertexCount});
        self.postMessage({type:'progress',completed:i+1,phase:'BVH'});
      }
      const begin=performance.now(),plan=planTracePages(chunks,data.limit,null,strategy);bvhMs+=performance.now()-begin;
      self.postMessage({type:'trace-plan',sizes:plan.sizes,scene:plan.scene},[plan.scene]);
      for(let i=0;i<chunks.length;i++){
        const chunk=chunks[i];const accepted=new Promise(resolve=>{resume=resolve;});
        self.postMessage({type:'trace-chunk',...chunk,descriptor:plan.descriptors[i],completed:i+1},[chunk.vertices,chunk.indices,chunk.nodes]);
        chunks[i]=null;await accepted;resume=null;
      }
      self.postMessage({type:'done',bvhMs,bvhStrategy:strategy,elapsed:performance.now()-started});return;
    }
    for(let i=0;i<scene.groups.length;i++){
      const group=scene.groups[i];const mesh=tessellateGroup(group);
      const accepted=new Promise(resolve=>{resume=resolve;});
      self.postMessage({type:'chunk',id:group.id,bounds:group.bounds,triangles:group.triangleCount,vertexCount:group.vertexCount,
        completed:i+1,vertices:mesh.vertices,indices:mesh.indices},[mesh.vertices,mesh.indices]);
      await accepted;resume=null;
    }
    self.postMessage({type:'done',bvhMs,bvhStrategy:strategy,elapsed:performance.now()-started});
  }catch(error){self.postMessage({type:'error',message:error.message});}
};
