// Geometry stays separate from the UI: every edit starts from immutable fragments.
export const DEFAULT_SETTINGS=Object.freeze({scale:100,scaleX:100,scaleY:100,scaleZ:100,rx:0,ry:0,rz:0,optimize:100});
export function normalizeSettings(value={}){
  return Object.fromEntries(Object.entries(DEFAULT_SETTINGS).map(([key,fallback])=>{
    const isScale=key.startsWith('scale');
    const n=Number(value?.[key]??fallback),min=isScale||key==='optimize'?100:0,max=isScale?200:key==='optimize'?1000:100;
    return [key,Math.round(Math.max(min,Math.min(max,Number.isFinite(n)?n:fallback)))];
  }));
}
function randomAngle(id,axis){
  let hash=2166136261;
  for(const ch of `${id}/${axis}`){hash^=ch.charCodeAt(0);hash=Math.imul(hash,16777619);}
  // Avalanche the hash so adjacent fragments and axes have unrelated rotations.
  hash^=hash>>>16;hash=Math.imul(hash,0x7feb352d);hash^=hash>>>15;hash=Math.imul(hash,0x846ca68b);hash^=hash>>>16;
  return (hash>>>0)/4294967296*Math.PI*2;
}
export function chooseLevels(data,optimize){
  const levels=data.fragments.map(()=>0),base=data.fragments.reduce((n,f)=>n+f.levels[0].triangles,0);
  const target=Math.round(base/(normalizeSettings({optimize}).optimize/100)/2)*2;
  let count=base;
  // Balance reduction across fragments, preserving the same deterministic order.
  while(count>target){
    let candidate=-1,ratio=-1;
    data.fragments.forEach((f,i)=>{
      const level=levels[i],next=f.levels[level+1];if(!next)return;
      const drop=f.levels[level].triangles-next.triangles;
      if(Math.abs(count-drop-target)>Math.abs(count-target))return;
      const r=f.levels[level].triangles/f.levels[0].triangles;
      if(r>ratio){candidate=i;ratio=r;}
    });
    if(candidate<0)break;
    const f=data.fragments[candidate],level=levels[candidate]++;
    count-=f.levels[level].triangles-f.levels[level+1].triangles;
  }
  return {levels,foliageTriangles:count,baseFoliageTriangles:base};
}
function normal(a,b,c){
  const u=b.map((x,i)=>x-a[i]),v=c.map((x,i)=>x-a[i]);
  const n=[u[1]*v[2]-u[2]*v[1],u[2]*v[0]-u[0]*v[2],u[0]*v[1]-u[1]*v[0]],length=Math.hypot(...n);
  if(length<1e-12)throw Error('В геометрии найден вырожденный треугольник');
  return n.map(x=>x/length);
}
export function packedNormal(n){
  const d=Math.abs(n[0])+Math.abs(n[1])+Math.abs(n[2]);let x=n[0]/d,y=n[1]/d;
  if(n[2]<0){const old=x;x=(1-Math.abs(y))*(x<0?-1:1);y=(1-Math.abs(old))*(y<0?-1:1);}
  return ((Math.round(x*32767)&0xffff)|((Math.round(y*32767)&0xffff)<<16))>>>0;
}
export function fragmentTransform(fragment,input){
  const settings=normalizeSettings(input);
  const [ax,ay,az]=['x','y','z'].map(axis=>randomAngle(fragment.id,axis)*settings['r'+axis]/100);
  const cx=Math.cos(ax),sx=Math.sin(ax),cy=Math.cos(ay),sy=Math.sin(ay),cz=Math.cos(az),sz=Math.sin(az),scale=settings.scale/100;
  return p=>{
    const [x,y,z]=p.map(v=>v*scale),y1=y*cx-z*sx,z1=y*sx+z*cx,x2=x*cy+z1*sy,z2=-x*sy+z1*cy;
    // Axis sizing follows the shared tree axes after rotation. Only the shape
    // around each fragment's pivot changes; branch attachments never move.
    return [(x2*cz-y1*sz)*(settings.scaleX/100)+fragment.pivot[0],
      (x2*sz+y1*cz)*(settings.scaleY/100)+fragment.pivot[1],
      z2*(settings.scaleZ/100)+fragment.pivot[2]];
  };
}
function packMeshes(meshes,metadata){
  const triangles=meshes.reduce((n,m)=>n+m.mesh.indices.length/3,0),vertices=triangles*3;
  const words=new Uint32Array(vertices*8),floats=new Float32Array(words.buffer);
  const positions=new Float32Array(vertices*3),normals=new Float32Array(vertices*3),materials=new Uint16Array(triangles);
  const bounds={min:[Infinity,Infinity,Infinity],max:[-Infinity,-Infinity,-Infinity]};let t=0;
  function append(mesh,transform,material){
    for(let j=0;j<mesh.indices.length;j+=3){
      const p=Array.from(mesh.indices.slice(j,j+3),index=>transform(Array.from(mesh.positions.slice(index*3,index*3+3))));
      const n=normal(...p),packed=packedNormal(n),mat=material??mesh.materials[j/3];materials[t]=mat;
      for(let k=0;k<3;k++){
        const v=t*3+k;positions.set(p[k],v*3);normals.set(n,v*3);floats.set(p[k],v*8);words[v*8+3]=packed;words[v*8+6]=(0x80000000|mat)>>>0;
        for(let axis=0;axis<3;axis++){bounds.min[axis]=Math.min(bounds.min[axis],positions[v*3+axis]);bounds.max[axis]=Math.max(bounds.max[axis],positions[v*3+axis]);}
      }t++;
    }
  }
  for(const m of meshes)append(m.mesh,m.transform??(p=>p),m.material);
  return {words,positions,normals,materials,bounds,triangles,vertexCount:vertices,...metadata};
}
export function buildGeometry(data,input){
  const settings=normalizeSettings(input),selection=chooseLevels(data,settings.optimize);
  return packMeshes([{mesh:data.wood},...data.fragments.map((fragment,i)=>({mesh:fragment.levels[selection.levels[i]],transform:fragmentTransform(fragment,settings),material:fragment.material}))],
    {model:data.model,label:data.label??data.model,woodTriangles:data.wood.triangles,...selection,settings,mode:'fragments'});
}
export function buildSurfaceGeometry(data,surface,input){
  return packMeshes([{mesh:data.wood},{mesh:surface}],{model:data.model,label:data.label??data.model,woodTriangles:data.wood.triangles,foliageTriangles:surface.indices.length/3,
    baseFoliageTriangles:surface.baseFoliageTriangles,settings:normalizeSettings(input),mode:'boolean'});
}

// Export exactly the edited mesh shown by the renderer, including shading normals and PBR.
export function exportGLB(geometry,palette){
  const views=[],accessors=[],parts=[];let byteLength=0;
  function accessor(array,type,componentType,target,extra={}){
    const bytes=new Uint8Array(array.buffer,array.byteOffset,array.byteLength);
    const view=views.push({buffer:0,byteOffset:byteLength,byteLength:bytes.length,target})-1;
    parts.push(bytes);byteLength+=bytes.length;
    return accessors.push({bufferView:view,componentType,count:array.length/(type==='VEC3'?3:1),type,...extra})-1;
  }
  const position=accessor(geometry.positions,'VEC3',5126,34962,{min:geometry.bounds.min,max:geometry.bounds.max});
  const normal=accessor(geometry.normals,'VEC3',5126,34962),primitives=[];
  const color=geometry.colors?accessor(geometry.colors,'VEC3',5126,34962):undefined;
  palette.forEach((m,material)=>{
    const ix=[];geometry.materials.forEach((mat,i)=>{if(mat===material)ix.push(i*3,i*3+1,i*3+2);});
    if(ix.length)primitives.push({attributes:{POSITION:position,NORMAL:normal,...(color!==undefined?{COLOR_0:color}:{})},indices:accessor(new Uint32Array(ix),'SCALAR',5125,34963),material,mode:4});
  });
  const doc={asset:{version:'2.0',generator:'NURAY vegetation workshop'},scene:0,scenes:[{nodes:[0]}],nodes:[{mesh:0,name:geometry.label??geometry.model??'Tree'}],
    meshes:[{primitives}],materials:palette.map((m,i)=>({name:m.name,pbrMetallicRoughness:{baseColorFactor:[...(geometry.colors&&i<4?[1,1,1]:m.color),1],metallicFactor:m.metallic??0,roughnessFactor:m.roughness??.94}})),
    buffers:[{byteLength}],bufferViews:views,accessors,extras:{...geometry.extras,model:geometry.model,foliageSettings:geometry.settings,foliageMode:geometry.mode,foliageSmoothingAngle:geometry.smoothingAngle??0}};
  const json=new TextEncoder().encode(JSON.stringify(doc)),jsonLength=Math.ceil(json.length/4)*4;
  const buffer=new ArrayBuffer(12+8+jsonLength+8+byteLength),dv=new DataView(buffer),bytes=new Uint8Array(buffer);
  dv.setUint32(0,0x46546c67,true);dv.setUint32(4,2,true);dv.setUint32(8,buffer.byteLength,true);
  dv.setUint32(12,jsonLength,true);dv.setUint32(16,0x4e4f534a,true);bytes.fill(32,20,20+jsonLength);bytes.set(json,20);
  const bin=20+jsonLength;dv.setUint32(bin,byteLength,true);dv.setUint32(bin+4,0x004e4942,true);
  let offset=bin+8;for(const part of parts){bytes.set(part,offset);offset+=part.length;}
  return buffer;
}
