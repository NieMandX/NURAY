import {mapConcurrent,readAssetJSON} from '../../src/district/asset-fetch.js?v=asset-delivery-1';
import {lookAt,perspective,multiply} from '../../src/district/math.js?v=moscow-defaults-1';

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
    b.dataset.initial=s.tileIds.some(id=>initial.has(id))?'true':'false';
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

// Review overlay only: no extra geometry, boundary walls or modification of
// the terrain. The circle is the centre registered from the user's screenshot.
export function drawAreaOutline(renderer){
  if(!renderer.tileset?.manualAreas)return;
  const ns='http://www.w3.org/2000/svg';
  let svg=document.getElementById('area-outline');
  if(!svg){
    svg=document.createElementNS(ns,'svg');svg.id='area-outline';svg.setAttribute('aria-hidden','true');
    Object.assign(svg.style,{position:'absolute',inset:'0',width:'100%',height:'100%',pointerEvents:'none'});
    for(const tag of ['path','circle']){const el=document.createElementNS(ns,tag);el.setAttribute('fill','none');el.setAttribute('stroke','#ff6759');el.setAttribute('stroke-width','2');svg.append(el);}
    renderer.canvas.after(svg);
  }
  svg.style.display=document.getElementById('area-boundary').checked?'':'none';
  const w=renderer.canvas.clientWidth,h=renderer.canvas.clientHeight,c=renderer.camera,aspect=w/h;
  svg.setAttribute('viewBox',`0 0 ${w} ${h}`);
  const eye=[Math.sin(c.yaw)*Math.cos(c.pitch)*c.distance+c.target[0],Math.sin(c.pitch)*c.distance+c.target[1],Math.cos(c.yaw)*Math.cos(c.pitch)*c.distance+c.target[2]];
  const m=multiply(perspective(2*Math.atan(Math.tan(44*Math.PI/360)*Math.max(1,1.1/aspect)),aspect,1,60000),lookAt(eye,c.target));
  const origin=renderer.tileset.origin,initial=renderer.tileset.manualAreas.initial,b=initial.boundsMSK;
  const project=([east,north])=>{
    const x=east-origin[0],z=origin[1]-north;
    const p=[0,1,2,3].map(i=>m[i]*x+m[i+8]*z+m[i+12]);
    return p[3]>1?[(p[0]/p[3]+1)*w/2,(1-p[1]/p[3])*h/2]:null;
  };
  const points=[[b[0],b[1]],[b[2],b[1]],[b[2],b[3]],[b[0],b[3]]].map(project);
  svg.children[0].setAttribute('d',points.every(Boolean)?'M'+points.map(p=>p.join(',')).join('L')+'Z':'');
  const center=project(initial.centerMSK),circle=svg.children[1];circle.setAttribute('r',center?'7':'0');
  if(center){circle.setAttribute('cx',center[0]);circle.setAttribute('cy',center[1]);}
}
