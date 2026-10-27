const cache=new WeakMap();
const cross=(a,b)=>[a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]];
const dot=(a,b)=>a.reduce((sum,v,k)=>sum+v*b[k],0);
const sub=(a,b)=>a.map((v,k)=>v-b[k]);
export function normalizeStrength(value){const n=Number(value);return Number.isFinite(n)?Math.max(0,Math.min(100,Math.round(n))):0;}

// Signed integrated mean curvature from oriented geometric dihedral angles.
// Calculated once per geometry, independent of shade normals, camera and light.
export function foliageCurvature(base){
  let result=cache.get(base.positions);if(result)return result;
  const points=new Map(),edges=new Map(),faces=[];
  const parent=Int32Array.from({length:base.vertexCount},(_,i)=>i);
  const root=i=>{while(parent[i]!==i){parent[i]=parent[parent[i]];i=parent[i];}return i;};
  const join=(a,b)=>{a=root(a);b=root(b);if(a!==b)parent[b]=a;};
  for(let t=0;t<base.triangles;t++){
    if(base.materials[t]>=4)continue;
    const p=Array.from({length:3},(_,k)=>Array.from(base.positions.subarray(t*9+k*3,t*9+k*3+3)));
    const n=cross(sub(p[1],p[0]),sub(p[2],p[0])),length=Math.hypot(...n);if(length<1e-12)continue;
    const face={t,p,n:n.map(v=>v/length),area:length/2};faces.push(face);
    const ids=p.map(v=>{const key=v.join(',');if(!points.has(key))points.set(key,points.size);return points.get(key);});
    for(let k=0;k<3;k++){
      const next=(k+1)%3,a=ids[k],b=ids[next],key=`${Math.min(a,b)}/${Math.max(a,b)}`;
      const group=edges.get(key)??[];group.push({a,b,ca:t*3+k,cb:t*3+next,e:sub(p[next],p[k]),face});edges.set(key,group);
    }
  }
  const paired=[];
  for(const edge of edges.values()){
    if(edge.length!==2)continue;
    const [a,b]=edge;if(a.a!==b.b||a.b!==b.a)continue;
    join(a.ca,b.cb);join(a.cb,b.ca);paired.push(edge);
  }
  // Corner fans stay separate at non-manifold edges and point-only contacts.
  const sums=new Float64Array(base.vertexCount),areas=new Float64Array(base.vertexCount);
  for(const face of faces)for(let k=0;k<3;k++)areas[root(face.t*3+k)]+=face.area/3;
  for(const [a,b] of paired){
    const length=Math.hypot(...a.e),direction=a.e.map(v=>v/length);
    const angle=Math.atan2(dot(direction,cross(a.face.n,b.face.n)),Math.max(-1,Math.min(1,dot(a.face.n,b.face.n))));
    const value=length*angle/4;sums[root(a.ca)]+=value;sums[root(a.cb)]+=value;
  }
  const values=Array.from(areas, (area,i)=>area>0?sums[i]/area:0);
  const magnitudes=values.map(Math.abs).filter(v=>v>1e-9).sort((a,b)=>a-b);
  const reference=magnitudes[Math.floor((magnitudes.length-1)*.75)]??1;
  const curvature=new Float32Array(base.vertexCount);
  for(const face of faces)for(let k=0;k<3;k++){
    const c=face.t*3+k,h=values[root(c)];curvature[c]=h/(Math.abs(h)+reference*.65);
  }
  result=curvature;cache.set(base.positions,result);return result;
}

export function colorCurvature(geometry,palette,input){
  const strength=normalizeStrength(input),curvature=foliageCurvature(geometry);
  const words=geometry.words.slice(),floats=new Float32Array(words.buffer),colors=new Float32Array(geometry.vertexCount*3).fill(1);
  for(let i=0;i<geometry.vertexCount;i++){
    const mat=geometry.materials[Math.floor(i/3)],h=curvature[i];
    const factor=mat<4?1+strength/100*h*(h<0?.55:.30):1;
    floats[i*8+7]=factor;
    if(mat<4)for(let k=0;k<3;k++)colors[i*3+k]=Math.min(1,palette[mat].color[k]*floats[i*8+7]);
  }
  return {...geometry,words,colors,extras:{...geometry.extras,foliageCurvatureStrength:strength,foliageCurvatureMethod:'signed-dihedral-mean-v1'}};
}

// Older renderers need the extension; current city and workshop share it.
export function workshopShader(source){
  if(source.includes('@location(4) tint:f32')&&source.includes('m.color.rgb*v.tint'))return source;
  for(const [from,to] of [
    ['@location(3) face:u32 }','@location(3) face:u32, @location(4) tint:f32 }'],
    ['@interpolate(flat) material:u32 }','@interpolate(flat) material:u32, @location(4) tint:f32 }'],
    ['input.uv,material);','input.uv,material,select(1.0,input.tint,input.tint>0));'],
    ['var color=m.color.rgb;','var color=clamp(m.color.rgb*v.tint,vec3f(0),vec3f(1));']
  ]){
    if(source.split(from).length!==2)throw Error('Изменился формат шейдера мастерской');
    source=source.replace(from,to);
  }
  return source;
}
