// Capture approved live exports as immutable revisions; rebuild appearance without regenerating shapes.
import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {createHash} from 'node:crypto';
import assert from 'node:assert/strict';
import {packedNormal,exportGLB} from '../../web-preview/vegetation-study/foliage-editor.js';
import {foliagePalette} from '../../web-preview/vegetation-study/foliage-color.js';
import {colorCurvature} from '../../web-preview/vegetation-study/foliage-curvature.js';
const assets=fileURLToPath(new URL('../../web-preview/vegetation-study/assets/',import.meta.url));
const readJSON=async file=>JSON.parse(await fs.readFile(file,'utf8'));
const writeJSON=(file,value)=>fs.writeFile(file,JSON.stringify(value,null,2)+'\n');
const hash=data=>createHash('sha256').update(data).digest('hex');
const choices=await readJSON(path.join(assets,'choices.json')),appearance=await readJSON(path.join(assets,'appearance.json'));
const catalog=await readJSON(path.join(assets,'catalog.json'));
let snapshots;
if(process.argv[2]){
  snapshots=(await readJSON(process.argv[2])).map(s=>s.shading?{...s.shading,appearance:s.appearance,path:s.path,date:s.date,sourceVariant:s.sourceVariant}:s);
  for(const s of snapshots){
    const folder=path.join(assets,'library',s.model);await fs.mkdir(folder,{recursive:true});
    const bytes=await fs.readFile(s.path),doc=JSON.parse(bytes.subarray(20,20+bytes.readUInt32LE(12)).toString());
    assert.equal(doc.extras.model,s.model);assert.equal(doc.extras.foliageSmoothingAngle,s.angle);
    assert.equal(choices[s.model].variant,s.variant);
    if(s.appearance){
      assert.equal(s.appearance.model,s.model);
      assert.equal(doc.extras.foliageColor,s.appearance.foliageColor);
      assert.equal(doc.extras.foliageCurvatureStrength,s.appearance.curvatureStrength);
    }
    const filename=s.appearance?`approved-${hash(bytes).slice(0,12)}.glb`:'source-approved.glb',source=path.join(folder,filename);
    try{assert.equal(hash(await fs.readFile(source)),hash(bytes),'Existing approved snapshot differs');}catch(e){if(e.code!=='ENOENT')throw e;}
    await fs.writeFile(source,bytes);
    const date=s.date??new Intl.DateTimeFormat('en-CA',{timeZone:'Europe/Moscow',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
    const selection={...s,path:filename,sha256:hash(bytes),selectedBy:'user',date};
    await writeJSON(path.join(folder,'selection.json'),selection);
    await writeJSON(path.join(folder,filename.replace('.glb','.json')),selection);
    s.path=filename;
    if(s.appearance){
      const {foliageColor,curvatureStrength}=s.appearance;
      appearance.models[s.model]={...appearance.models[s.model],foliageColor,curvatureStrength,selectedBy:'user',date};
    }
  }
  await writeJSON(path.join(assets,'appearance.json'),appearance);
}
// A capture may contain just the newly approved tree; retain every library entry.
snapshots=await Promise.all(Object.keys(choices).map(id=>readJSON(path.join(assets,'library',id,'selection.json'))));
const library={version:1,integrated:Object.values(choices).every(c=>c.integrated),colorSpace:'linear-rgb-in-glb',models:[]};
for(const s of snapshots){
  const folder=path.join(assets,'library',s.model),source=await fs.readFile(path.join(folder,s.path));
  const jl=source.readUInt32LE(12),doc=JSON.parse(source.subarray(20,20+jl).toString()),bin=source.subarray(28+jl);
  assert.equal(doc.extras.model,s.model);assert.equal(doc.extras.foliageSmoothingAngle,s.angle);assert.equal(choices[s.model].variant,s.variant);
  const read=i=>{const a=doc.accessors[i],v=doc.bufferViews[a.bufferView];assert.ok(!v.byteStride);const n=a.count*(a.type==='VEC3'?3:1),Type=a.componentType===5126?Float32Array:Uint32Array;return new Type(Uint8Array.from(bin.subarray((v.byteOffset??0)+(a.byteOffset??0),(v.byteOffset??0)+(a.byteOffset??0)+n*4)).buffer);};
  const primitives=doc.meshes[0].primitives,positions=read(primitives[0].attributes.POSITION),normals=read(primitives[0].attributes.NORMAL),vertexCount=positions.length/3;
  const triangles=vertexCount/3,materials=new Uint16Array(triangles),seen=new Set();assert.equal(triangles,s.triangles);
  for(const p of primitives){
    assert.equal(p.attributes.POSITION,primitives[0].attributes.POSITION);assert.equal(p.attributes.NORMAL,primitives[0].attributes.NORMAL);
    const indices=read(p.indices);
    for(let i=0;i<indices.length;i+=3){const c=indices[i];assert.equal(c%3,0);assert.equal(indices[i+1],c+1);assert.equal(indices[i+2],c+2);assert.ok(!seen.has(c));seen.add(c);materials[c/3]=p.material;}
  }
  assert.equal(seen.size,triangles);
  const words=new Uint32Array(vertexCount*8),floats=new Float32Array(words.buffer),min=[Infinity,Infinity,Infinity],max=[-Infinity,-Infinity,-Infinity];
  for(let c=0;c<vertexCount;c++){
    floats.set(positions.subarray(c*3,c*3+3),c*8);words[c*8+3]=packedNormal(normals.subarray(c*3,c*3+3));words[c*8+6]=(0x80000000|materials[Math.floor(c/3)])>>>0;
    for(let k=0;k<3;k++){min[k]=Math.min(min[k],positions[c*3+k]);max[k]=Math.max(max[k],positions[c*3+k]);}
  }
  const style=appearance.models[s.model],palette=foliagePalette(catalog.materials,style.foliageColor);
  const geometry={positions,normals,words,materials,triangles,vertexCount,bounds:{min,max},model:s.model,label:catalog.models.find(m=>m.id===s.model).label,
    settings:doc.extras.foliageSettings,mode:doc.extras.foliageMode,smoothingAngle:s.angle,extras:{...doc.extras,foliageColor:style.foliageColor,colorSpace:'srgb'}};
  const result=Buffer.from(exportGLB(colorCurvature(geometry,palette,style.curvatureStrength??45),palette));
  await fs.writeFile(path.join(folder,'model.glb'),result);
  choices[s.model].smoothingAngle=s.angle;choices[s.model].library={file:`library/${s.model}/model.glb`,source:`library/${s.model}/${s.path}`,sourceSha256:hash(source),glbSha256:hash(result)};
  library.models.push({id:s.model,label:geometry.label,variant:s.variant,triangles,smoothingAngle:s.angle,foliageColor:style.foliageColor,curvatureStrength:style.curvatureStrength??45,bounds:geometry.bounds,...choices[s.model].library});
}
await writeJSON(path.join(assets,'choices.json'),choices);await writeJSON(path.join(assets,'library','index.json'),library);
console.log(library.models.map(m=>`${m.id}: ${m.triangles} triangles, ${m.smoothingAngle}°, ${m.foliageColor}`).join('\n'));
