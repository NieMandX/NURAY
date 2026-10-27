export const SCENE_LAYERS=Object.freeze({vegetation:'Деревья и кустарники',fences:'Заборы',playgrounds:'Оборудование детских площадок',lights:'Фонари'});
export const layerDefaults=()=>Object.fromEntries(Object.keys(SCENE_LAYERS).map(k=>[k,true]));
export function sceneLayer(mesh){
  if(mesh.layer)return mesh.layer;
  const name=mesh.name||'';
  if(mesh.category==='vegetation'||name.startsWith('nuray-approved-'))return 'vegetation';
  if(name==='street-fences')return 'fences';
  if(name.startsWith('street-lamppost'))return 'lights';
  if(/^street-(swing|slide|trampoline)/.test(name))return 'playgrounds';
  return null;
}
export function layerVisible(mesh,state){return state?.[sceneLayer(mesh)]!==false;}
export function normalizeLayers(value){const result=layerDefaults();for(const key of Object.keys(result))if(typeof value?.[key]==='boolean')result[key]=value[key];return result;}
export function installSceneLayers(renderer,catalog,apply=value=>renderer.setSceneLayers(value)){
  const panel=document.getElementById('scene-layers'),storageKey='nuray-scene-layers-v1:'+catalog;
  let state=layerDefaults();try{state=normalizeLayers(JSON.parse(localStorage.getItem(storageKey)));}catch{}
  const controls=[];
  for(const [key,label] of Object.entries(SCENE_LAYERS)){
    const row=document.createElement('label'),input=document.createElement('input');row.style.display='flex';input.type='checkbox';input.checked=state[key];input.dataset.sceneLayer=key;row.append(input,document.createTextNode(label));panel.append(row);controls.push(input);
    if(key==='fences'&&renderer.merged&&!renderer.visibilityMetadata){input.disabled=true;input.title='Для этого GLB ещё не подготовлена карта категорий';state[key]=true;input.checked=true;}
    input.onchange=async()=>{
      const previous={...state};state[key]=input.checked;panel.disabled=true;
      try{await apply(state);try{localStorage.setItem(storageKey,JSON.stringify(state));}catch{}}
      catch(error){state=previous;controls.forEach(c=>c.checked=state[c.dataset.sceneLayer]);renderer.onError(error.message);}
      finally{panel.disabled=false;}
    };
  }
  panel.disabled=false;return apply(state);
}
