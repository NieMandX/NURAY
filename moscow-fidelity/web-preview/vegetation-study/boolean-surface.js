import Module from './vendor/manifold-3d/manifold.js';
import {MeshoptSimplifier} from './vendor/meshoptimizer/meshopt_simplifier.js';
import {fragmentTransform,normalizeSettings} from './foliage-editor.js';

let runtime;
async function ready(){
  runtime??=Module().then(module=>{module.setup();return module;});
  await MeshoptSimplifier.ready;return runtime;
}

export function validateSurface(surface){
  const edges=new Map(),p=surface.positions,ix=surface.indices;let volume=0;
  for(let t=0;t<ix.length;t+=3){
    const [a,b,c]=Array.from(ix.slice(t,t+3),i=>Array.from(p.slice(i*3,i*3+3)));
    if(![...a,...b,...c].every(Number.isFinite))throw Error('Некорректные координаты оболочки');
    const u=b.map((v,i)=>v-a[i]),v=c.map((v,i)=>v-a[i]),cross=[u[1]*v[2]-u[2]*v[1],u[2]*v[0]-u[0]*v[2],u[0]*v[1]-u[1]*v[0]];
    if(Math.hypot(...cross)<1e-12)throw Error('Вырожденная грань оболочки');
    volume+=(a[0]*(b[1]*c[2]-b[2]*c[1])+a[1]*(b[2]*c[0]-b[0]*c[2])+a[2]*(b[0]*c[1]-b[1]*c[0]))/6;
    for(let j=0;j<3;j++){
      const x=ix[t+j],y=ix[t+(j+1)%3],key=`${Math.min(x,y)}/${Math.max(x,y)}`,edge=edges.get(key)??[0,0];
      edge[0]++;edge[1]+=x<y?1:-1;edges.set(key,edge);
    }
  }
  if(!ix.length||volume<=0||[...edges.values()].some(e=>e[0]!==2||e[1]!==0))throw Error('Оболочка не замкнута');
  return {closed:true,volume};
}

function unpackMesh(mesh){
  const parent=Uint32Array.from({length:mesh.numVert},(_,i)=>i);
  for(let i=0;i<mesh.mergeFromVert.length;i++)parent[mesh.mergeFromVert[i]]=mesh.mergeToVert[i];
  function root(i){while(parent[i]!==i)i=parent[i];return i;}
  const positions=[],map=new Map(),indices=Uint32Array.from(mesh.triVerts,index=>{
    const key=root(index),p=Array.from(mesh.vertProperties.slice(key*3,key*3+3));
    if(!map.has(key)){map.set(key,positions.length/3);positions.push(...p);}return map.get(key);
  });
  return {positions:Float32Array.from(positions),indices};
}

export async function createBooleanSurface(data,input){
  const {Manifold,Mesh}=await ready(),settings=normalizeSettings({...input,optimize:100});
  const materialBase=Manifold.reserveIDs(data.materials.length),parts=[];let union;
  try{
    for(const fragment of data.fragments){
      // Boolean always starts from full-resolution, transformed fragments.
      const level=fragment.levels[0],transform=fragmentTransform(fragment,settings),p=[];
      for(let i=0;i<level.positions.length;i+=3)p.push(...transform(level.positions.slice(i,i+3)));
      parts.push(new Manifold(new Mesh({numProp:3,vertProperties:Float32Array.from(p),triVerts:Uint32Array.from(level.indices),
        runIndex:Uint32Array.from([0,level.indices.length]),runOriginalID:Uint32Array.from([materialBase+fragment.material])})));
    }
    union=Manifold.union(parts);const mesh=union.getMesh(),materials=new Uint16Array(mesh.numTri);
    for(let r=0;r<mesh.runOriginalID.length;r++){
      const material=mesh.runOriginalID[r]-materialBase;
      if(material<0||material>=data.materials.length)throw Error('Потерян материал оболочки');
      materials.fill(material,mesh.runIndex[r]/3,mesh.runIndex[r+1]/3);
    }
    const surface={...unpackMesh(mesh),materials,settings,baseFoliageTriangles:mesh.numTri,
      originalFoliageTriangles:data.fragments.reduce((n,f)=>n+f.levels[0].triangles,0)};
    surface.quality=validateSurface(surface);return surface;
  }finally{union?.delete();parts.forEach(p=>p.delete());}
}

function triangleDistance(px,py,pz,f){
  const wx=px-f[0],wy=py-f[1],wz=pz-f[2],uw=f[3]*wx+f[4]*wy+f[5]*wz,vw=f[6]*wx+f[7]*wy+f[8]*wz;
  const s=(f[11]*uw-f[10]*vw)/f[12],t=(f[9]*vw-f[10]*uw)/f[12];
  if(s>=0&&t>=0&&s+t<=1){const x=wx-s*f[3]-t*f[6],y=wy-s*f[4]-t*f[7],z=wz-s*f[5]-t*f[8];return x*x+y*y+z*z;}
  function segment(x,y,z,ex,ey,ez){const k=Math.max(0,Math.min(1,(x*ex+y*ey+z*ez)/(ex*ex+ey*ey+ez*ez)));x-=k*ex;y-=k*ey;z-=k*ez;return x*x+y*y+z*z;}
  return Math.min(segment(wx,wy,wz,f[3],f[4],f[5]),segment(wx,wy,wz,f[6],f[7],f[8]),segment(wx-f[3],wy-f[4],wz-f[5],f[6]-f[3],f[7]-f[4],f[8]-f[5]));
}
const materialCaches=new WeakMap();
const triangleKey=(p,ids)=>ids.map(id=>Array.from(p.slice(id*3,id*3+3)).join(',')).sort().join('/');
function transferMaterials(source,positions,indices){
  let cache=materialCaches.get(source);
  if(!cache){
    const p=source.positions,faces=[],exact=new Map();
    for(let i=0;i<source.indices.length;i+=3){
      const ids=Array.from(source.indices.slice(i,i+3)),[a,b,c]=ids.map(id=>Array.from(p.slice(id*3,id*3+3)));
      exact.set(triangleKey(p,ids),source.materials[i/3]);
      const u=b.map((x,j)=>x-a[j]),v=c.map((x,j)=>x-a[j]),dot=(x,y)=>x.reduce((s,n,j)=>s+n*y[j],0),uu=dot(u,u),uv=dot(u,v),vv=dot(v,v);
      faces.push([...a,...u,...v,uu,uv,vv,uu*vv-uv*uv,...a.map((x,j)=>Math.min(x,b[j],c[j])),...a.map((x,j)=>Math.max(x,b[j],c[j])),source.materials[i/3]]);
    }
    cache={faces,exact};materialCaches.set(source,cache);
  }
  const materials=new Uint16Array(indices.length/3);
  for(let i=0;i<indices.length;i+=3){
    const ids=Array.from(indices.slice(i,i+3)),same=cache.exact.get(triangleKey(positions,ids));
    if(same!==undefined){materials[i/3]=same;continue;}
    const [px,py,pz]=[0,1,2].map(axis=>ids.reduce((n,id)=>n+positions[id*3+axis]/3,0));let closest=Infinity;
    for(const f of cache.faces){
      const dx=Math.max(f[13]-px,0,px-f[16]),dy=Math.max(f[14]-py,0,py-f[17]),dz=Math.max(f[15]-pz,0,pz-f[18]);
      if(dx*dx+dy*dy+dz*dz>closest)continue;
      const d=triangleDistance(px,py,pz,f);if(d<closest){closest=d;materials[i/3]=f[19];}
    }
  }
  return materials;
}
export async function simplifySurface(source,percent){
  const {Manifold,Mesh}=await ready(),optimize=normalizeSettings({optimize:percent}).optimize;
  if(optimize===100)return source;
  const target=Math.max(4,Math.round(source.baseFoliageTriangles/(optimize/100)/2)*2);
  const [indices,error]=MeshoptSimplifier.simplify(source.indices,source.positions,3,target*3,1,[]);
  // Edge collapses can leave coincident opposite faces. Manifold removes those
  // and verifies oriented topology before the mesh is accepted by the renderer.
  const cleaned=new Manifold(new Mesh({numProp:3,vertProperties:source.positions,triVerts:indices}));
  try{
    const surface={...source,...unpackMesh(cleaned.getMesh()),error,settings:{...source.settings,optimize}};
    surface.quality=validateSurface(surface);
    surface.materials=transferMaterials(source,surface.positions,surface.indices);return surface;
  }finally{cleaned.delete();}
}
