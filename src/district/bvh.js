// Preorder, stackless BVH. Internal word 3 is the escape node; leaf word 3
// is the first primitive in the reordered index array. Word 7 is leaf count.
export function buildHierarchy(bounds,leafSize=8){
  const count=bounds.length/6,order=Uint32Array.from({length:count},(_,i)=>i);
  const memory=new ArrayBuffer(Math.max(1,2*count-1)*32),f=new Float32Array(memory),u=new Uint32Array(memory);
  let used=0,maxDepth=0;
  function build(start,end,depth){
    const node=used++,o=node*8;maxDepth=Math.max(maxDepth,depth);
    const lo=[Infinity,Infinity,Infinity],hi=[-Infinity,-Infinity,-Infinity];
    const clo=[Infinity,Infinity,Infinity],chi=[-Infinity,-Infinity,-Infinity];
    for(let i=start;i<end;i++){
      const b=order[i]*6;for(let a=0;a<3;a++){
        lo[a]=Math.min(lo[a],bounds[b+a]);hi[a]=Math.max(hi[a],bounds[b+3+a]);
        const c=(bounds[b+a]+bounds[b+3+a])*.5;clo[a]=Math.min(clo[a],c);chi[a]=Math.max(chi[a],c);
      }
    }
    f.set(lo,o);f.set(hi,o+4);
    if(end-start<=leafSize){u[o+3]=start;u[o+7]=end-start;return;}
    let axis=0;for(let a=1;a<3;a++)if(chi[a]-clo[a]>chi[axis]-clo[axis])axis=a;
    const split=(clo[axis]+chi[axis])*.5;let middle=start;
    for(let i=start;i<end;i++){
      const b=order[i]*6;
      if((bounds[b+axis]+bounds[b+3+axis])*.5<split){const t=order[middle];order[middle++]=order[i];order[i]=t;}
    }
    if(middle===start||middle===end||depth>40)middle=(start+end)>>>1;
    build(start,middle,depth+1);build(middle,end,depth+1);u[o+3]=used;
  }
  if(count)build(0,count,0);
  return {nodes:memory.slice(0,used*32),order,nodeCount:used,maxDepth};
}
export function buildMeshBvh(mesh){
  const f=new Float32Array(mesh.vertices),indices=new Uint32Array(mesh.indices),count=indices.length/3;
  const bounds=new Float32Array(count*6);
  for(let t=0;t<count;t++)for(let a=0;a<3;a++){
    const x=f[indices[t*3]*8+a],y=f[indices[t*3+1]*8+a],z=f[indices[t*3+2]*8+a];
    bounds[t*6+a]=Math.min(x,y,z)-.00002;bounds[t*6+3+a]=Math.max(x,y,z)+.00002;
  }
  const tree=buildHierarchy(bounds),sorted=new Uint32Array(indices.length);
  for(let t=0;t<count;t++)sorted.set(indices.subarray(tree.order[t]*3,tree.order[t]*3+3),t*3);
  return {vertices:mesh.vertices,indices:sorted.buffer,nodes:tree.nodes,nodeCount:tree.nodeCount};
}
export const identityTransform=()=>[1,0,0,0,0,1,0,0,0,0,1,0];
export function inverseTransform(m){
  const [a,b,c,x,d,e,f,y,g,h,i,z]=m;
  const det=a*(e*i-f*h)-b*(d*i-f*g)+c*(d*h-e*g);
  if(Math.abs(det)<1e-12)throw new Error('Вырожденный масштаб экземпляра');
  const r=[(e*i-f*h)/det,(c*h-b*i)/det,(b*f-c*e)/det,0,(f*g-d*i)/det,(a*i-c*g)/det,(c*d-a*f)/det,0,(d*h-e*g)/det,(b*g-a*h)/det,(a*e-b*d)/det,0];
  for(let k=0;k<3;k++)r[k*4+3]=-(r[k*4]*x+r[k*4+1]*y+r[k*4+2]*z);return r;
}
export function transformBounds(bounds,m){
  const min=[Infinity,Infinity,Infinity],max=[-Infinity,-Infinity,-Infinity];
  for(let mask=0;mask<8;mask++)for(let a=0;a<3;a++){
    let p=m[a*4+3];for(let b=0;b<3;b++)p+=m[a*4+b]*(mask&(1<<b)?bounds.max[b]:bounds.min[b]);
    min[a]=Math.min(min[a],p-.001);max[a]=Math.max(max[a],p+.001);
  }return {min,max};
}
export function planTracePages(chunks,limit,instances=null){
  const sizes=[0],descriptors=[];let page=0;
  for(const chunk of chunks){
    const length=chunk.vertices.byteLength+chunk.indices.byteLength+chunk.nodes.byteLength;
    if(length>limit)throw new Error('Один блок сцены превышает лимит GPU-буфера.');
    if(sizes[page]+length>limit){page++;sizes.push(0);}
    if(page>=4)throw new Error('BVH и геометрия не помещаются в четыре буфера этого GPU.');
    const vertex=sizes[page]/4,index=vertex+chunk.vertices.byteLength/4,nodes=index+chunk.indices.byteLength/4;
    descriptors.push({page,vertex,index,nodes,nodeCount:chunk.nodeCount});sizes[page]+=length;
  }
  const leaves=instances??chunks.map((c,mesh)=>({mesh})),stride=instances?20:8;
  const bounds=Float32Array.from(leaves.flatMap(i=>{const b=instances?transformBounds(chunks[i.mesh].bounds,i.matrix):chunks[i.mesh].bounds;return [...b.min,...b.max];}));
  const top=buildHierarchy(bounds,1),scene=new ArrayBuffer(16+top.nodes.byteLength+leaves.length*stride*4);
  const words=new Uint32Array(scene),floats=new Float32Array(scene);words.set([top.nodeCount,4+top.nodes.byteLength/4,leaves.length,instances?stride:0]);
  words.set(new Uint32Array(top.nodes),4);
  for(let i=0;i<top.order.length;i++){
    const instance=leaves[top.order[i]],d=descriptors[instance.mesh],o=words[1]+i*stride;
    words.set([d.page,d.vertex,d.index,d.nodes,d.nodeCount,0,0,0],o);
    if(instances)floats.set(inverseTransform(instance.matrix),o+8);
  }
  return {sizes,descriptors,scene};
}
