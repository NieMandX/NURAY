import {identityTransform,transformBounds,inverseTransform,buildHierarchy} from '../../src/district/bvh.js?v=moscow-defaults-1';

export function pageChunkIds(allocation,tileset,modes){
  return [...(allocation.shared??[]),...allocation.tiles.flatMap(id=>{
    if(!modes.has(id))return [];
    const tile=tileset.tiles.find(t=>t.id===id);return modes.get(id)==='full'?tile.chunks:tile.coarseChunks;
  })];
}
export function activeChunkIds(tileset,modes){
  return new Set(tileset.tiles.filter(t=>modes.has(t.id)).flatMap(t=>[...(modes.get(t.id)==='full'?t.chunks:t.coarseChunks),...(t.instances??[]).map(i=>i.mesh)]));
}
export function sceneInstances(tileset,modes){
  const result=[];
  for(const tile of tileset.tiles){
    if(!modes.has(tile.id))continue;
    for(const id of modes.get(tile.id)==='full'?tile.chunks:tile.coarseChunks)result.push({mesh:id,matrix:identityTransform()});
    result.push(...(tile.instances??[]));
  }
  return result;
}
export function rasterLayout(instances,assets){
  const byMesh=new Map();for(const i of instances){if(!byMesh.has(i.mesh))byMesh.set(i.mesh,[]);byMesh.get(i.mesh).push(i);}
  const transforms=new Float32Array(instances.length*12),draws=[];let first=0;
  for(const [mesh,items] of byMesh){
    const min=[Infinity,Infinity,Infinity],max=[-Infinity,-Infinity,-Infinity];
    for(const i of items){transforms.set(i.matrix,first*12);first++;const b=transformBounds(assets.get(mesh).bounds,i.matrix);for(let a=0;a<3;a++){min[a]=Math.min(min[a],b.min[a]);max[a]=Math.max(max[a],b.max[a]);}}
    draws.push({id:mesh,instanceFirst:first-items.length,instanceCount:items.length,bounds:{min,max}});
  }
  return {transforms,draws};
}
export function traceScene(instances,assets,descriptors){
  const bounds=Float32Array.from(instances.flatMap(i=>{const b=transformBounds(assets.get(i.mesh).bounds,i.matrix);return [...b.min,...b.max];}));
  const top=buildHierarchy(bounds,1,'sah'),stride=20,scene=new ArrayBuffer(16+top.nodes.byteLength+instances.length*stride*4),words=new Uint32Array(scene),floats=new Float32Array(scene);
  words.set([top.nodeCount,4+top.nodes.byteLength/4,instances.length,stride]);words.set(new Uint32Array(top.nodes),4);
  for(let n=0;n<top.order.length;n++){
    const i=instances[top.order[n]],d=descriptors.get(i.mesh),offset=words[1]+n*stride;
    if(!d)throw Error('Missing shared mesh descriptor '+i.mesh);
    words.set([d.page,d.vertex,d.index,d.nodes,d.nodeCount,0,0,0],offset);floats.set(inverseTransform(i.matrix),offset+8);
  }
  return scene;
}
