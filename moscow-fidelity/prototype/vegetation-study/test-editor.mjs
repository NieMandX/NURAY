import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {gunzipSync} from 'node:zlib';
import {DEFAULT_SETTINGS,normalizeSettings,chooseLevels,fragmentTransform,buildGeometry,exportGLB} from '../../web-preview/vegetation-study/foliage-editor.js';
const data=JSON.parse(gunzipSync(readFileSync(new URL('../../web-preview/vegetation-study/assets/birch/editor.json.gz',import.meta.url))));
const original=buildGeometry(data,DEFAULT_SETTINGS);
assert.equal(original.triangles,1326);assert.equal(original.foliageTriangles,1050);assert.equal(original.woodTriangles,276);
assert.deepEqual(normalizeSettings({scale:900,scaleX:99,scaleY:201,scaleZ:NaN,optimize:1001,rx:-1,ry:NaN}),{...DEFAULT_SETTINGS,scale:200,scaleY:200,optimize:1000});
assert.deepEqual(normalizeSettings({scale:123,ry:100,optimize:1000}),{...DEFAULT_SETTINGS,scale:123,ry:100,optimize:1000},'Older saved settings must keep the original shape');
let previous=1050;
for(let optimize=100;optimize<=1000;optimize++){
  const g=chooseLevels(data,optimize);assert(g.foliageTriangles<=previous);assert(Math.abs(g.foliageTriangles-105000/optimize)<=1.001);previous=g.foliageTriangles;
}
const largest=buildGeometry(data,{scale:200}),start=data.wood.triangles*9;let offset=start;
data.fragments.forEach(f=>{
  f.levels[0].indices.forEach(index=>{
    for(let axis=0;axis<3;axis++){
      const p=f.levels[0].positions[index*3+axis];
      assert.equal(original.positions[offset],Math.fround(p+f.pivot[axis]));
      assert.equal(largest.positions[offset],Math.fround(2*p+f.pivot[axis]));offset++;
    }
  });
});
const settings={scale:153,rx:27,ry:83,rz:100,optimize:1000};
const edited=buildGeometry(data,settings),again=buildGeometry(data,settings);
assert.equal(edited.triangles,382);assert.equal(edited.foliageTriangles,106);
assert.deepEqual(edited.words,again.words);
assert.deepEqual(edited.words.slice(0,data.wood.triangles*3*8),original.words.slice(0,data.wood.triangles*3*8));
assert.deepEqual(buildGeometry(data,DEFAULT_SETTINGS).words,original.words);
// An axis stretches the rotated shape about each fixed pivot, independently
// of the other two axes and of the global scale. Wood is never transformed.
for(const axis of [0,1,2]){
  const key=['scaleX','scaleY','scaleZ'][axis],input={scale:123,rx:28,ry:63,rz:37};
  const resized=buildGeometry(data,{...input,[key]:200});
  assert.deepEqual(resized.words.slice(0,data.wood.triangles*3*8),original.words.slice(0,data.wood.triangles*3*8));
  for(const fragment of data.fragments){
    const before=fragmentTransform(fragment,input),after=fragmentTransform(fragment,{...input,[key]:200});
    assert(after([0,0,0]).every((n,i)=>n===fragment.pivot[i]),'Fragment centers must not move');
    for(let i=0;i<fragment.levels[0].positions.length;i+=3){
      const p=fragment.levels[0].positions.slice(i,i+3),a=before(p),b=after(p);
      for(let j=0;j<3;j++)assert(Math.abs(b[j]-(fragment.pivot[j]+(a[j]-fragment.pivot[j])*(j===axis?2:1)))<1e-12);
    }
  }
  for(let i=0;i<resized.normals.length;i+=3)assert(Math.abs(Math.hypot(...resized.normals.slice(i,i+3))-1)<1e-6);
}
for(let i=0;i<edited.normals.length;i+=3)assert(Math.abs(Math.hypot(...edited.normals.slice(i,i+3))-1)<1e-6);
// Every simplification level must remain a closed, consistently oriented shell.
for(const f of data.fragments)for(const level of f.levels){
  const edges=new Map();let volume=0;
  for(let i=0;i<level.indices.length;i+=3){
    const ids=level.indices.slice(i,i+3),p=ids.map(id=>level.positions.slice(id*3,id*3+3));
    volume+=p[0][0]*(p[1][1]*p[2][2]-p[1][2]*p[2][1])+p[0][1]*(p[1][2]*p[2][0]-p[1][0]*p[2][2])+p[0][2]*(p[1][0]*p[2][1]-p[1][1]*p[2][0]);
    for(let j=0;j<3;j++){const a=ids[j],b=ids[(j+1)%3],key=`${Math.min(a,b)}/${Math.max(a,b)}`,edge=edges.get(key)??[0,0];edge[0]++;edge[1]+=a<b?1:-1;edges.set(key,edge);}
  }
  assert(volume>0);for(const edge of edges.values())assert.deepEqual(edge,[2,0]);
}
const glb=exportGLB(edited,data.materials),dv=new DataView(glb);
assert.equal(dv.getUint32(0,true),0x46546c67);assert.equal(dv.getUint32(8,true),glb.byteLength);
const jsonLength=dv.getUint32(12,true),doc=JSON.parse(new TextDecoder().decode(new Uint8Array(glb,20,jsonLength)));
assert.equal(doc.meshes[0].primitives.reduce((n,p)=>n+doc.accessors[p.indices].count/3,0),edited.triangles);
assert.deepEqual(doc.extras.foliageSettings,normalizeSettings(settings));
const pos=doc.accessors[doc.meshes[0].primitives[0].attributes.POSITION],view=doc.bufferViews[pos.bufferView];
assert.deepEqual(new Float32Array(glb,28+jsonLength+view.byteOffset,pos.count*3),edited.positions);
console.log('PASS: baseline, fixed wood/pivots, uniform and independent axis scaling after rotation, old settings migration, deterministic reset, 901 optimization settings, 500 closed shells, exact GLB export.');
