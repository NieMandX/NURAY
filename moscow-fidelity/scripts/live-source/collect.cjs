/** Fresh public 2GIS snapshot. No fallback to an earlier source directory.
 * Endpoint/schema evidence: browser/rarity-3d.js and browser/map_style.json.
 * Keep all source records; physical-vs-information filtering belongs downstream.
 */
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const root=path.resolve(process.argv[2]);process.env.DGIS_LIVE_ROOT=root;
const c=require('./core_loader.cjs');
const plan=JSON.parse(fs.readFileSync(path.join(root,'plan.json')));
const cache=path.join(root,'source/cache'),out=path.join(root,'output',plan.output_subdir||'area_5000');
fs.mkdirSync(cache,{recursive:true});fs.mkdirSync(out,{recursive:true});
const manifestPath=path.join(root,'sources.json');
const previous=fs.existsSync(manifestPath)?JSON.parse(fs.readFileSync(manifestPath)):[];
const manifest=new Map(previous.map(x=>[x.url,x]));const inflight=new Map();
const hash=b=>crypto.createHash('sha256').update(b).digest('hex');
const safe=s=>s.replace(/[^a-zA-Z0-9._-]/g,'_');
const key=plan.publicSiteKey;
async function get(url,relative){
 if(inflight.has(url))return inflight.get(url);
 const promise=(async()=>{
  const file=path.join(root,relative),old=manifest.get(url);
  // Resume only verified bytes from this independently dated snapshot.
  if(old&&old.file===relative&&fs.existsSync(file)){
   const b=fs.readFileSync(file);if(hash(b)===old.sha256)return b;
  }
  for(let attempt=0;attempt<4;attempt++){
   try{
    const r=await fetch(url,{headers:{'Cache-Control':'no-cache'},signal:AbortSignal.timeout(120000)});
    if(!r.ok)throw Error(`HTTP ${r.status}`);
    const b=Buffer.from(await r.arrayBuffer());fs.mkdirSync(path.dirname(file),{recursive:true});
    fs.writeFileSync(file+'.part',b);fs.renameSync(file+'.part',file);
    manifest.set(url,{url,file:relative,bytes:b.length,sha256:hash(b),retrievedAt:new Date().toISOString(),status:r.status,etag:r.headers.get('etag'),lastModified:r.headers.get('last-modified')});
    fs.writeFileSync(manifestPath,JSON.stringify([...manifest.values()],null,2));return b;
   }catch(error){if(attempt===3)throw Error(`${url}: ${error.message}`);await new Promise(r=>setTimeout(r,700*(attempt+1)));}
  }
 })();inflight.set(url,promise);return promise;
}
function vint(n){const out=[];do{out.push((n&127)|(n>127?128:0));n>>>=7}while(n);return out;}
function request([x,y,z]){const m=[8,...vint(x),16,...vint(y),24,...vint(z)];return Buffer.from([10,m.length,...m]).toString('base64');}
async function pool(items,fn,n=3){let i=0;await Promise.all(Array.from({length:n},async()=>{while(i<items.length)await fn(items[i++]);}));}
const modelMap=new Map(),missing=[],tileStats=[];
function addModels(data,channel){for(const f of data.features||[]){const p=f.properties||{};if(!p.model_src&&!p.model_lod1_src)continue;
 const id=JSON.stringify([p.building_id||p.db_id,p.model_lod1_src||p.model_src,f.geometry.coordinates,p.angle,p.scale]);modelMap.set(id,{...f,sourceChannel:channel});}}
async function one(tile){
 const [x,y,z]=tile,stem=tile.slice(0,3).join('_');
 const b=await get(`https://tile${(x+y)%4}.maps.2gis.com/vt?r=${encodeURIComponent(request(tile))}&ts=vector_a&key=${key}&appId=empty&lang=ru&default_lang=ru&dt=static,immersive_roads`,`source/cache/${stem}.pbf`);
 const groups=c.__decodeTileGroups(new Uint8Array(b).buffer),features=[];
 const collector={addFeature:f=>features.push(f),getAccumulatedData:()=>({data:[],transferable:[]}),addFloorHidingMap(){}};
 const states=new Map();states.featureAttrs=new Set();
 const params={styleState:{},sourceId:'2gis',sourceAttrs:{},tileInfo:c.createTileInfo(tile),pixelRatio:1,selectedIds:[],floorsEnabled:false};
 for(const g of groups){
  const mh=c.__metaHash(g.metatileHash);
  const raw=JSON.parse(await get(`https://tile0.maps.2gis.com/metafiles/${mh}/metatile.json?ts=vector_a`,`source/cache/meta_${safe(mh)}.json`));
  c.renameZenithEnumerationValues(raw);raw.tileProps=raw.tileProps.map(c.zenithToJakartaPropKey);
  c.__generateGeo({}, {getLayers:()=>[]},states,collector,params,g,c.prepareMetatile(raw),[],false,undefined,true);
 }
 fs.writeFileSync(path.join(cache,stem+'.json'),JSON.stringify({tile,tile_info:{size:params.tileInfo.size,offset:Array.from(params.tileInfo.offset)},features}));
 const ab=await get(`https://tile${(x+y)%4}.maps.2gis.com/v2/ald?ts=vector_immersive&x=${x}&y=${y}&z=${z}`,`source/cache/${stem}.ald.json`);
 addModels(ab.length?JSON.parse(ab):{features:[]},'vector_immersive');
 const flip=2**z-1-y;
 const db=await get(`https://tile${(x+flip)%4}.maps.2gis.com/v2/ald?ts=dem&x=${x}&y=${flip}&z=${z}`,`source/cache/dem_${stem}.bin`);
 const d=c.__decodeDem(new Uint8Array(db).buffer);if(!d.positions.length)throw Error(`Empty DEM ${stem}`);
 fs.writeFileSync(path.join(cache,`dem_${stem}.json`),JSON.stringify({tile,tile_info:{offset:Array.from(params.tileInfo.offset),size:params.tileInfo.size},...Object.fromEntries(Object.entries(d).map(([k,v])=>[k,ArrayBuffer.isView(v)?Array.from(v):v]))}));
 tileStats.push({tile,features:features.length,demVertices:d.heights.length});console.log(`Fresh vector + DEM ${tileStats.length}/${plan.tiles.length}: ${stem}, ${features.length} records`);
}
async function main(){
 await pool(plan.tiles,one);
 const parents=[...new Map(plan.tiles.map(([x,y])=>{const p=[Math.floor(x/2),Math.floor(y/2),14];return[p.join('_'),p]})).values()];
 await pool(parents,async([x,y,z])=>{
  const b=await get(`https://tile${(x+y)%4}.maps.2gis.com/v2/ald?ts=com_poi_web&x=${x}&y=${y}&z=${z}&lang=ru`,`source/cache/com_${x}_${y}_${z}.json`);
  addModels(b.length?JSON.parse(b):{features:[]},'com_poi_web');
 });
 const models=[...modelMap.values()];
 await pool(models,async(f)=>{
  f.local_files={};const p=f.properties;
  for(const [lod,src] of Object.entries(p).filter(([k,v])=>/^model_(src|lod\d+_src)$/.test(k)&&v)){
   const url=/^https:\/\//.test(src)?src:`https://tile0.maps.2gis.com/metafiles/${src}?ts=vector_a`;
   const relative='source/cache/model_'+(/^https:/.test(src)?hash(Buffer.from(src)).slice(0,16)+'_'+path.basename(new URL(src).pathname):safe(src));
   try{await get(url,relative);f.local_files[lod]=path.join(root,relative);}catch(e){missing.push({building_id:p.building_id,src,error:e.message});}
  }
  f.local_file=f.local_files.model_lod1_src||f.local_files.model_src||f.local_files.model_lod0_src;
  console.log(`Model ${p.building_id||'unlinked'}: ${Object.keys(f.local_files).length} LODs, ${f.sourceChannel}`);
 });
 const result={...plan,output:out,publicSiteKey:undefined};
 fs.writeFileSync(path.join(out,'plan.json'),JSON.stringify(result,null,2));
 fs.writeFileSync(path.join(out,'models.json'),JSON.stringify(models.filter(m=>m.local_file)));
 fs.writeFileSync(path.join(out,'unavailable_models.json'),JSON.stringify(missing,null,2));
 const report={acquiredAt:new Date().toISOString(),boundsMSK:plan.extent_msk_east_north,sourcePolicy:'Fresh network retrieval; resume only this snapshot, never earlier caches',vectorTiles:tileStats,commercialTiles:parents.length,models:models.length,availableModels:models.filter(m=>m.local_file).length,commercialModels:models.filter(m=>m.sourceChannel==='com_poi_web').length,missing,networkResources:manifest.size};
 fs.writeFileSync(path.join(root,'acquisition-report.json'),JSON.stringify(report,null,2));
 console.log('ACQUIRED',JSON.stringify({tiles:tileStats.length,models:models.length,commercialModels:report.commercialModels,missing:missing.length}));
}
main().catch(e=>{console.error(e.stack);process.exitCode=1;});
