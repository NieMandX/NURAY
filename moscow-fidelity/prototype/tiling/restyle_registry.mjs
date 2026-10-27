// Sparse appearance edits in huge compact registries. Untouched bytes pass
// through unchanged; no terrain/partition work and no city-sized JSON string.
import fs from 'node:fs';
import {createGunzip,createGzip} from 'node:zlib';
import {once} from 'node:events';
const [input,output,patchFile]=process.argv.slice(2);
const patch=JSON.parse(fs.readFileSync(patchFile,'utf8'));
const features=new Map(patch.features.map(f=>[f.id,f.semantics]));
const surfaces=new Map(patch.surfaces ? patch.surfaces.map(s=>[s.id,s]) :
  patch.surfaceIds.map(id=>[id,{material:patch.material,surfaceType:'cemetery-cover',styleId:null}]));
const counts={features:0,surfaces:0,buildings:0};
const source=input.endsWith('.gz')?fs.createReadStream(input).pipe(createGunzip({chunkSize:8*1024*1024})):fs.createReadStream(input);
const gzip=createGzip({level:1}),destination=fs.createWriteStream(output+'.tmp');gzip.pipe(destination);
let depth=0,quoted=false,escaped=false,key='',field='',readingKey=false,parts=null,partDepth=2;
let pending=[];
function write(bytes){if(bytes.length)pending.push(bytes);}
async function flush(){
  if(!pending.length)return;
  const bytes=Buffer.concat(pending);pending=[];
  if(!gzip.write(bytes))await once(gzip,'drain');
}
function replace(raw){
  if(field==='sourceChunks'&&patch.sourceChunks)return Buffer.from(JSON.stringify(patch.sourceChunks));
  if(field==='objectLayer'&&patch.objectLayerUpdate){
    const layer=JSON.parse(raw.toString('utf8')),updates=new Map((patch.objectLayerUpdate.buildings??[]).map(b=>[b.id,b]));
    for(const row of layer.buildings){const update=updates.get(row.id);if(update){Object.assign(row,update);counts.buildings++;}}
    Object.assign(layer.stats,patch.objectLayerUpdate.stats);
    for(const key of ['roofs','pitchedRoofs','facades'])if(key in patch.objectLayerUpdate)layer[key]=patch.objectLayerUpdate[key];
    return Buffer.from(JSON.stringify(layer));
  }
  if(field==='geometryRevision')return Buffer.from(JSON.stringify(patch.geometryRevision));
  const text=raw.toString('utf8');
  // IDs are pipeline-generated unescaped strings. Parse only selected records;
  // JSON.parse below remains the authority, not text substitution in JSON.
  const id=/"id"\s*:\s*"([^"\\]+)"/.exec(text)?.[1];
  if(field==='features'&&features.has(id)){
    const value=JSON.parse(text);value.semantics=features.get(value.id);counts.features++;
    return Buffer.from(JSON.stringify(value));
  }
  if(field==='surfaces'&&surfaces.has(id)){
    const value=JSON.parse(text),update=surfaces.get(value.id);
    // Sparse geometry-height edits must preserve material/semantic fields, just
    // as appearance edits preserve geometry and height planes.
    Object.assign(value,update);counts.surfaces++;
    return Buffer.from(JSON.stringify(value));
  }
  return raw;
}
for await(const buffer of source){
  let start=0;
  for(let i=0;i<buffer.length;i++){
    const c=buffer[i];
    if(quoted){
      if(readingKey)key+=String.fromCharCode(c);
      if(escaped)escaped=false;
      else if(c===92)escaped=true;
      else if(c===34){quoted=false;if(readingKey){field=JSON.parse(key);readingKey=false;}}
      continue;
    }
    if(c===34){quoted=true;if(depth===1){key='"';readingKey=true;}continue;}
    if(c===123||c===91){
      if(((c===123||c===91)&&depth===1&&((field==='objectLayer'&&patch.objectLayerUpdate)||(field==='sourceChunks'&&patch.sourceChunks)))||(c===123&&((depth===2&&(field==='features'||field==='surfaces'))||(depth===1&&field==='geometryRevision')))){
        write(buffer.subarray(start,i));start=i;parts=[];partDepth=depth;
      }
      depth++;
    }else if(c===125||c===93){
      if(c===93&&depth===2&&field==='surfaces'&&patch.newSurfaces?.length){
        write(buffer.subarray(start,i));write(Buffer.from(','+patch.newSurfaces.map(r=>JSON.stringify(r)).join(',')));start=i;
      }
      depth--;
      if(parts&&depth===partDepth){
        parts.push(buffer.subarray(start,i+1));write(replace(Buffer.concat(parts)));
        parts=null;start=i+1;
      }
    }
  }
  if(parts)parts.push(buffer.subarray(start));else write(buffer.subarray(start));
  await flush();
}
if(depth||quoted||parts)throw Error('Incomplete JSON registry');
if(counts.features!==features.size||counts.surfaces!==surfaces.size)throw Error('Missing or duplicated appearance records: '+JSON.stringify(counts));
if(patch.objectLayerUpdate&&counts.buildings!==(patch.objectLayerUpdate.buildings??[]).length)throw Error('Missing building updates');
gzip.end();await once(destination,'finish');fs.renameSync(output+'.tmp',output);
console.log('REGISTRY APPEARANCE',output,counts);
