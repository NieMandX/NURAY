import {mapConcurrent,readAssetJSON} from '../../src/district/asset-fetch.js?v=asset-delivery-1';

export function areaTileIds(index, extra=[]){
  const ids=new Set(index.initial.tileIds),requested=new Set(extra);
  for(const s of index.shards)if(requested.has(s.id))for(const id of s.tileIds)ids.add(id);
  return ids;
}

// Only selected metadata is decoded. Geometry keeps its original content URLs,
// hashes and shared template IDs; adding overlapping areas cannot duplicate it.
export async function hydrateAreas(renderer,ids,read=readAssetJSON){
  const index=renderer.tileset.manualAreas;
  renderer.areaShards??=new Set();
  const missing=index.shards.filter(s=>!renderer.areaShards.has(s.id)&&s.tileIds.some(id=>ids.has(id)));
  const loaded=await mapConcurrent(missing,async s=>{
    let previous=0;renderer.streamStats.requests++;
    const data=await read(s.asset,renderer.base,(bytes)=>{renderer.streamStats.downloadBytes+=bytes-previous;previous=bytes;});
    if(data.tiles.length!==s.tileIds.length||data.tiles.some(t=>!s.tileIds.includes(t.id)))throw Error('Неверный каталог участка '+s.id);
    return {s,data};
  },4);
  // Commit metadata only after every requested shard has passed its hash check.
  const tiles=new Map(renderer.tileset.tiles.map(t=>[t.id,t]));
  for(const {s,data} of loaded){
    for(const t of data.tiles)tiles.set(t.id,t);
    for(const c of data.chunks)if(!renderer.assets.has(c.id)){renderer.tileset.chunks.push(c);renderer.assets.set(c.id,c);}
    renderer.areaShards.add(s.id);
  }
  renderer.tileset.tiles=[...tiles.values()];
}

export function installAreaPicker(renderer,onChange){
  const index=renderer.tileset.manualAreas,host=document.getElementById('area-picker');
  host.hidden=false;
  const selected=new Set(),grid=document.getElementById('area-grid');
  const initial=new Set(index.initial.tileIds),buttons=new Map();
  grid.style.gridTemplateColumns=`repeat(${Math.max(...index.shards.map(s=>s.east))+1},1fr)`;
  for(const s of [...index.shards].sort((a,b)=>b.north-a.north||a.east-b.east)){
    const b=document.createElement('button');b.type='button';b.dataset.area=s.id;
    b.textContent=`${s.east+1}·${s.north+1}`;
    b.setAttribute('aria-label',`Участок ${s.east+1}, ${s.north+1}`);
    const fullInitial=s.tileIds.every(id=>initial.has(id));
    b.disabled=fullInitial;
    b.title=fullInitial?'Входит в начальный участок':`Добавить участок ${s.east+1}, ${s.north+1}`;
    b.onclick=()=>change(()=>selected.has(s.id)?selected.delete(s.id):selected.add(s.id));
    grid.append(b);buttons.set(s.id,b);
  }
  const reset=document.getElementById('areas-reset'),status=document.getElementById('areas-status');
  const update=()=>{
    const ids=areaTileIds(index,selected);
    for(const s of index.shards){const b=buttons.get(s.id);b.setAttribute('aria-pressed',String(selected.has(s.id)||s.tileIds.every(id=>initial.has(id))));}
    status.textContent=`Выбрано ${ids.size} из ${renderer.tileset.tiles.length} тайлов · с запасом ${(ids.size*renderer.tileset.tileSizeM**2/1e6).toLocaleString('ru-RU',{maximumFractionDigits:2})} км²`;
    reset.disabled=!selected.size;
    return ids;
  };
  async function change(mutate){
    const before=new Set(selected);mutate();host.disabled=true;status.textContent='Загружаем выбранный участок…';
    try{await onChange(areaTileIds(index,selected));}
    catch(e){selected.clear();for(const id of before)selected.add(id);renderer.onError(e.message);}
    finally{host.disabled=false;update();}
  }
  reset.onclick=()=>change(()=>selected.clear());update();
}
