import assert from 'node:assert/strict';
import fs from 'node:fs';
import {gunzipSync} from 'node:zlib';
import {normalizeColor,colorToLinear,linearToColor,foliagePalette} from '../../web-preview/vegetation-study/foliage-color.js';
import {foliageCurvature,colorCurvature,workshopShader} from '../../web-preview/vegetation-study/foliage-curvature.js';
import {decodePackedGeometry,smoothFoliage} from '../../web-preview/vegetation-study/foliage-smoothing.js';
import {exportGLB} from '../../web-preview/vegetation-study/foliage-editor.js';
const assets=new URL('../../web-preview/vegetation-study/assets/',import.meta.url);
const readJSON=url=>JSON.parse(fs.readFileSync(url));
const palette=readJSON(new URL('catalog.json',assets)).materials,original=JSON.stringify(palette);
for(const hex of ['#000000','#ffffff','#65834c','#7c914d'])assert.equal(linearToColor(colorToLinear(hex)),hex);
assert.equal(normalizeColor('#FFFfff'),'#ffffff');assert.equal(normalizeColor('red'),null);
const tinted=foliagePalette(palette,'#587547');assert.equal(JSON.stringify(palette),original);
for(let i=4;i<7;i++)assert.deepEqual(tinted[i],palette[i]);
for(let k=0;k<3;k++)assert(Math.abs(tinted[1].color[k]/tinted[0].color[k]-palette[1].color[k]/palette[0].color[k])<1e-12);

function hinge(sign=1,scale=1){
  const p=[[[0,0,0],[1,0,0],[0,1,0]],[[1,0,0],[0,0,0],[0,0,sign]]];
  return {positions:Float32Array.from(p.flat(2),v=>v*scale),normals:new Float32Array(18),words:new Uint32Array(48),materials:[0,1],triangles:2,vertexCount:6};
}
const valley=hinge(1),ridge=hinge(-1),flat=hinge(0); // flat second triangle is degenerate, safely ignored.
for(const c of [0,1,3,4]){
  assert(foliageCurvature(valley)[c]<0,'Valley vertices must darken');assert(foliageCurvature(ridge)[c]>0,'Ridge vertices must lighten');
}
assert(foliageCurvature(flat).every(v=>Number.isFinite(v)));
assert.deepEqual(foliageCurvature(hinge(1,100)),foliageCurvature(valley),'Uniform scale must not change the color pattern');
for(const c of [2,5])assert.equal(foliageCurvature(valley)[c],0,'Boundary without a crease is neutral');
const coated=colorCurvature(valley,tinted,100),neutral=colorCurvature(valley,tinted,0);
assert(coated.colors[0]<neutral.colors[0]);assert.equal(coated.colors[6],neutral.colors[6]);
assert.equal(new Float32Array(neutral.words.buffer)[7],1);
const convex=colorCurvature(ridge,tinted,100);assert(convex.colors[0]>neutral.colors[0]);
const wood=hinge(1);wood.materials=[4,4];assert(foliageCurvature(wood).every(v=>v===0));assert(colorCurvature(wood,tinted,100).colors.every(v=>v===1));
const single=hinge(1);single.materials=[0,4];assert(foliageCurvature(single).every(v=>v===0),'Do not infer leaf curvature through wood');
const nonManifold={...hinge(1),positions:Float32Array.from([...hinge(1).positions,0,0,0,1,0,0,0,-1,0]),materials:[0,0,0],vertexCount:9,triangles:3};
assert(foliageCurvature(nonManifold).every(v=>v===0),'Non-manifold crease must be ignored');
const shader=fs.readFileSync(new URL('../../web-preview/src/district/district.wgsl',import.meta.url),'utf8');assert(workshopShader(shader).includes('m.color.rgb*v.tint'));

function parse(bytes){
  const buffer=bytes instanceof ArrayBuffer?bytes:Uint8Array.from(bytes).buffer,dv=new DataView(buffer),jl=dv.getUint32(12,true),doc=JSON.parse(new TextDecoder().decode(new Uint8Array(buffer,20,jl)));
  const attribute=name=>{const a=doc.accessors[doc.meshes[0].primitives[0].attributes[name]],v=doc.bufferViews[a.bufferView];return new Float32Array(buffer,28+jl+(v.byteOffset??0)+(a.byteOffset??0),a.count*3);};
  return {doc,attribute};
}
const choices=readJSON(new URL('choices.json',assets)),styles=readJSON(new URL('appearance.json',assets));
for(const [id,choice] of Object.entries(choices)){
  const folder=new URL((choice.folder??choice.variant)+'/',assets),scene=readJSON(new URL('scene.json',folder)),chunk=scene.chunks[0];
  const raw=Uint8Array.from(gunzipSync(fs.readFileSync(new URL(chunk.file,folder))));
  const base=decodePackedGeometry(raw.buffer,chunk),smoothed=smoothFoliage(base,choice.smoothingAngle),pal=foliagePalette(scene.materials,styles.models[id].foliageColor);
  const h=foliageCurvature(base),negative=Array.from(h).filter(v=>v<0).length,positive=Array.from(h).filter(v=>v>0).length;
  assert(negative>0&&positive>0,`${id}: real foliage needs both valleys and bulges`);
  assert.deepEqual(foliageCurvature(smoothed),h,'Curvature must not depend on smoothing angle');
  const result=colorCurvature(smoothed,pal,45);assert.deepEqual(result.positions,base.positions);assert.deepEqual(result.normals,smoothed.normals);assert.deepEqual(result.materials,base.materials);
  for(let c=0;c<result.vertexCount;c++){
    for(let w=0;w<7;w++)assert.equal(result.words[c*8+w],smoothed.words[c*8+w],'Only unused tint word may change');
    if(base.materials[Math.floor(c/3)]>=4)assert.deepEqual(Array.from(result.colors.slice(c*3,c*3+3)),[1,1,1]);
  }
  const exported=parse(exportGLB(result,pal));assert.deepEqual(exported.attribute('COLOR_0'),result.colors);
  assert.deepEqual(exported.attribute('NORMAL'),smoothed.normals);assert.equal(exported.doc.extras.foliageCurvatureStrength,45);
  assert(exported.attribute('COLOR_0').every(v=>v>=0&&v<=1));
  for(let i=4;i<7;i++)assert.deepEqual(exported.doc.materials[i].pbrMetallicRoughness.baseColorFactor,[...scene.materials[i].color,1]);
  const accepted=parse(fs.readFileSync(new URL(choice.library.source,assets))),library=parse(fs.readFileSync(new URL(choice.library.file,assets)));
  assert.deepEqual(library.attribute('POSITION'),accepted.attribute('POSITION'),'Library preserves exact accepted positions');
  assert.deepEqual(library.attribute('NORMAL'),accepted.attribute('NORMAL'),'Library preserves exact accepted smoothing');
  if(accepted.doc.meshes[0].primitives[0].attributes.COLOR_0!==undefined){
    assert.deepEqual(library.attribute('COLOR_0'),accepted.attribute('COLOR_0'),'Library preserves exact accepted vertex colors');
    assert.deepEqual(library.doc.materials,accepted.doc.materials,'Library preserves exact accepted PBR materials');
    assert.equal(library.doc.extras.foliageCurvatureStrength,accepted.doc.extras.foliageCurvatureStrength);
    assert.equal(library.doc.extras.foliageColor,accepted.doc.extras.foliageColor);
  }
  assert.deepEqual(accepted.attribute('NORMAL'),smoothed.normals,'Workshop defaults match the captured user normals');
  console.log(`${id}: ${negative} concave / ${positive} convex corners; selected normals exact, geometry and wood unchanged, GLB colors verified`);
}
console.log('PASS: color space, per-type palette, signed curvature, scale invariance, boundaries, wood isolation, GPU tint layout and library snapshots.');
