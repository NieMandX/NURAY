import {packedNormal} from './foliage-editor.js';

export function normalizeAngle(value){
  const n=Number(value);return Number.isFinite(n)?Math.max(0,Math.min(180,Math.round(n))):0;
}
function decodeNormal(word){
  let x=(word<<16>>16)/32767,y=(word>>16)/32767,z=1-Math.abs(x)-Math.abs(y);
  const t=Math.max(0,-z);x+=x>=0?-t:t;y+=y>=0?-t:t;
  const d=Math.hypot(x,y,z);return [x/d,y/d,z/d];
}

// Expand the existing indexed mesh without changing any GPU vertex attributes.
// This also allows per-corner split normals along the selected sharp edges.
export function decodePackedGeometry(raw,chunk){
  const source=new Uint32Array(raw,0,chunk.vertexBytes/4),indices=new Uint32Array(raw,chunk.vertexBytes);
  const words=new Uint32Array(indices.length*8),floats=new Float32Array(words.buffer);
  const positions=new Float32Array(indices.length*3),normals=new Float32Array(indices.length*3),materials=new Uint16Array(indices.length/3);
  for(let i=0;i<indices.length;i++){
    words.set(source.subarray(indices[i]*8,indices[i]*8+8),i*8);
    positions.set(floats.subarray(i*8,i*8+3),i*3);normals.set(decodeNormal(words[i*8+3]),i*3);
    if(i%3===0)materials[i/3]=words[i*8+6]&0x7fffffff;
  }
  // Accepted live Boolean meshes keep full-precision base normals. Round-trip
  // through the GPU's oct16 encoding must not change the next GLB export.
  if(chunk.cornerNormals){
    if(chunk.cornerNormals.length!==normals.length||!chunk.cornerNormals.every(Number.isFinite))throw Error('Некорректные нормали сохранённой модели');
    normals.set(chunk.cornerNormals);
    for(let i=0;i<indices.length;i++)words[i*8+3]=packedNormal(normals.subarray(i*3,i*3+3));
  }
  // Workshop palette 0..3 = foliage/needles, 4..6 = wood/birch bark.
  const foliageTriangles=materials.reduce((n,m)=>n+(m<4),0);
  return {words,positions,normals,materials,triangles:indices.length/3,vertexCount:indices.length,bounds:chunk.bounds,
    foliageTriangles,woodTriangles:indices.length/3-foliageTriangles,baseFoliageTriangles:foliageTriangles};
}

const topologyCache=new WeakMap();
const cross=(a,b)=>[a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]];
const dot=(a,b)=>a.reduce((s,v,i)=>s+v*b[i],0);
function topology(base){
  let data=topologyCache.get(base);if(data)return data;
  const vertices=new Map(),edges=new Map(),faces=[],weights=new Float64Array(base.vertexCount);
  for(let t=0;t<base.triangles;t++){
    if(base.materials[t]>=4)continue;
    const p=Array.from({length:3},(_,k)=>Array.from(base.positions.subarray((t*3+k)*3,(t*3+k+1)*3)));
    const ids=p.map(point=>{const key=point.join(',');if(!vertices.has(key))vertices.set(key,vertices.size);return vertices.get(key);});
    const u=p[1].map((v,j)=>v-p[0][j]),v=p[2].map((v,j)=>v-p[0][j]),n=cross(u,v),length=Math.hypot(...n);
    if(length<1e-12)continue;
    const face={t,n:n.map(x=>x/length)};faces.push(face);
    for(let k=0;k<3;k++){
      const next=(k+1)%3,prev=(k+2)%3,a=ids[k],b=ids[next],key=`${Math.min(a,b)}/${Math.max(a,b)}`;
      const group=edges.get(key)??[];group.push({a,b,ca:t*3+k,cb:t*3+next,face});edges.set(key,group);
      const u=p[next].map((v,j)=>v-p[k][j]),v=p[prev].map((v,j)=>v-p[k][j]);
      weights[t*3+k]=Math.atan2(Math.hypot(...cross(u,v)),dot(u,v));
    }
  }
  data={faces,weights,edges:[...edges.values()]};topologyCache.set(base,data);return data;
}

export function smoothFoliage(base,input){
  const angle=normalizeAngle(input);
  if(angle===0)return {...base,smoothingAngle:0}; // Exact original normals and words.
  const {faces,weights,edges}=topology(base),parent=Int32Array.from({length:base.vertexCount},(_,i)=>i);
  function root(i){while(parent[i]!==i){parent[i]=parent[parent[i]];i=parent[i];}return i;}
  function join(a,b){a=root(a);b=root(b);if(a!==b)parent[b]=a;}
  const threshold=Math.cos(angle*Math.PI/180);
  for(const edge of edges){
    // Do not bridge disconnected vertex contacts, boundaries or non-manifold edges.
    if(edge.length!==2)continue;
    const [a,b]=edge;if(a.a!==b.b||a.b!==b.a||dot(a.face.n,b.face.n)<threshold-1e-10)continue;
    join(a.ca,b.cb);join(a.cb,b.ca);
  }
  const groups=new Map();
  for(const {t,n} of faces)for(let k=0;k<3;k++){
    const corner=t*3+k,key=root(corner),group=groups.get(key)??{n:[0,0,0],corners:[]};
    group.corners.push(corner);for(let j=0;j<3;j++)group.n[j]+=n[j]*weights[corner];groups.set(key,group);
  }
  const words=base.words.slice(),normals=base.normals.slice();
  for(const {n,corners} of groups.values()){
    const length=Math.hypot(...n);if(corners.length<2||length<1e-12)continue;
    const normal=n.map(v=>v/length),packed=packedNormal(normal);
    for(const corner of corners){normals.set(normal,corner*3);words[corner*8+3]=packed;}
  }
  return {...base,words,normals,smoothingAngle:angle};
}
