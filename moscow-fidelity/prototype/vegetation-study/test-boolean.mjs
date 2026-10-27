import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {gunzipSync} from 'node:zlib';
import Module from '../../web-preview/vegetation-study/vendor/manifold-3d/manifold.js';
import {createBooleanSurface,simplifySurface,validateSurface} from '../../web-preview/vegetation-study/boolean-surface.js';
import {normalizeSettings,buildGeometry,buildSurfaceGeometry,exportGLB} from '../../web-preview/vegetation-study/foliage-editor.js';
const mod=await Module();mod.setup();
const cube=mod.Manifold.cube(1),mesh=cube.getMesh(),level={positions:Array.from(mesh.vertProperties),indices:Array.from(mesh.triVerts),triangles:mesh.numTri};
const cubes={materials:[{},{}],fragments:[0,.5].map((x,i)=>({id:'cube-'+i,pivot:[x,0,0],material:i,levels:[level]}))};
const merged=await createBooleanSurface(cubes,{});
assert(Math.abs(merged.quality.volume-1.5)<1e-6,'Union must remove overlapping volume, not concatenate meshes');
assert.deepEqual(new Set(merged.materials),new Set([0,1]));cube.delete();
for(const model of (process.argv.length>2?process.argv.slice(2):['birch','open','spruce','thuja','growth','low','bush'])){
const data=JSON.parse(gunzipSync(readFileSync(new URL(`../../web-preview/vegetation-study/assets/${model}/editor.json.gz`,import.meta.url))));
assert.equal(data.model,model);
for(const settings of [{ry:82},{},{scale:200,rx:100,ry:100,rz:100},{scale:146,rx:21,ry:49,rz:32},{scale:123,scaleX:200,scaleY:145,scaleZ:172,rx:28,ry:100,rz:37}]){
  const source=await createBooleanSurface(data,settings),baseline=buildGeometry(data,{...settings,optimize:100});
  assert(source.baseFoliageTriangles>0);validateSurface(source);
  const repeat=await createBooleanSurface(data,settings);
  assert.deepEqual(source.positions,repeat.positions);assert.deepEqual(source.indices,repeat.indices);assert.deepEqual(source.materials,repeat.materials);
  let count=source.baseFoliageTriangles;
  for(const optimize of [100,101,125,150,200,300,500,750,1000]){
    const surface=await simplifySurface(source,optimize),geometry=buildSurfaceGeometry(data,surface,{...settings,optimize});
    validateSurface(surface);assert(geometry.foliageTriangles<=count);count=geometry.foliageTriangles;
    assert(Math.abs(count-source.baseFoliageTriangles/(optimize/100))<15,'Triangle budget should be relative to union');
    assert.deepEqual(geometry.words.slice(0,data.wood.triangles*3*8),baseline.words.slice(0,data.wood.triangles*3*8));
    assert([...surface.materials].every(m=>m>=0&&m<4));
    const glb=exportGLB(geometry,data.materials),dv=new DataView(glb),doc=JSON.parse(new TextDecoder().decode(new Uint8Array(glb,20,dv.getUint32(12,true))));
    assert.equal(doc.extras.foliageMode,'boolean');assert.equal(doc.extras.foliageSettings.optimize,optimize);
    assert.deepEqual(doc.extras.foliageSettings,normalizeSettings({...settings,optimize}));
    assert.equal(doc.extras.model,model);assert.equal(doc.nodes[0].name,data.label??model);
    assert.equal(doc.meshes[0].primitives.reduce((n,p)=>n+doc.accessors[p.indices].count/3,0),geometry.triangles);
  }
  assert.equal(await simplifySurface(source,100),source,'100% must restore the immutable exact union');
  console.log('PASS',model,JSON.stringify(settings),`fragments ${source.originalFoliageTriangles} -> union ${source.baseFoliageTriangles} -> simplified ${count}`);
}
}
console.log('PASS: overlap removal, deterministic union, materials, closed surfaces, monotonic budgets, unchanged wood, exact reset and GLB mode.');
