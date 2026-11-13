export async function installGaussianPanel(renderer,manifestURL=new URL('./assets-kursk-splats-20261113-r1/vegetation.json',import.meta.url)){
  const panel=document.createElement('fieldset'),legend=document.createElement('legend'),label=document.createElement('label'),toggle=document.createElement('input'),status=document.createElement('p');
  legend.textContent='Растения · пробный 3DGS';toggle.type='checkbox';toggle.disabled=true;
  label.append(toggle,document.createTextNode(' Сплаты растений · центральный участок'));panel.append(legend,label,status);
  status.textContent='Загружаем лёгкие шаблоны…';document.getElementById('settings').append(panel);
  if(!renderer.merged||!renderer.device){
    status.textContent='Показаны полигональные растения. Сплаты доступны в полной сцене WebGPU.';
    return;
  }
  const {GaussianVegetation}=await import('../../src/district/gaussian/renderer.js?v=gs-11');
  const gs=new GaussianVegetation(renderer);renderer.gaussianVegetation=gs;
  try{
    await gs.open(manifestURL);
    if(gs.manifest.sourceHeaderSha256!==renderer.mergedHeaderSha256)throw Error('Сплаты подготовлены для другой версии сцены');
    toggle.disabled=false;toggle.checked=true;gs.setEnabled(true);
    gs.onStatus=()=>{status.textContent=gs.error?gs.error:renderer.sceneLayers?.vegetation===false?'Растения скрыты переключателем «Деревья и кустарники».':!gs.enabled?'Показаны исходные полигональные растения.':renderer.state.engine!=='raster'?'В рейтрейсе показаны исходные модели.':`${gs.active.size} растений · ${gs.count.toLocaleString('ru-RU')} сплатов · ${(gs.bytes/1048576).toFixed(1)} МиБ. Видимые деревья — сплаты; тени и отражения — прежние модели.`;};
    toggle.onchange=()=>gs.setEnabled(toggle.checked);gs.onStatus();
  }catch(error){gs.dispose();renderer.gaussianVegetation=null;status.textContent='Сплаты не подключены: '+error.message;console.warn(status.textContent);}
}
