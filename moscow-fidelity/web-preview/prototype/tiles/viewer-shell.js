// A single open panel, independent of render loading and without changing camera/settings.
const panels = [
  {panel:document.getElementById('sun-panel'),button:document.getElementById('sun-toggle')},
  {panel:document.getElementById('general-panel'),button:document.getElementById('settings-toggle')},
];
let active=null;
function close({restoreFocus=true}={}){
  if(!active)return;
  const previous=active;active=null;
  previous.panel.dataset.open='false';previous.panel.inert=true;
  previous.panel.setAttribute('aria-hidden','true');previous.button.setAttribute('aria-expanded','false');
  if(restoreFocus)previous.button.focus({preventScroll:true});
}
function open(entry){
  if(active===entry){close();return;}
  close({restoreFocus:false});active=entry;
  entry.panel.inert=false;entry.panel.removeAttribute('aria-hidden');entry.panel.dataset.open='true';
  entry.button.setAttribute('aria-expanded','true');
  entry.panel.querySelector('[data-close-panel]').focus({preventScroll:true});
}
for(const entry of panels){
  entry.button.addEventListener('click',()=>open(entry));
  entry.panel.querySelector('[data-close-panel]').addEventListener('click',()=>close());
}
document.addEventListener('keydown',event=>{
  if(event.key==='Escape'&&active){event.preventDefault();close();}
});
document.addEventListener('pointerdown',event=>{
  if(active&&!active.panel.contains(event.target)&&!panels.some(entry=>entry.button.contains(event.target)))close({restoreFocus:false});
});
// Do not leave keyboard focus in an offscreen panel. The canvas remains usable.
document.addEventListener('focusin',event=>{
  if(active&&!active.panel.contains(event.target)&&!panels.some(entry=>entry.button.contains(event.target)))close({restoreFocus:false});
});
const stats=document.getElementById('show-performance');
// Only scene parameters persist. Every new visit starts with all UI panels closed.
stats.checked=false;
function updateStats(){document.body.dataset.showPerformance=String(stats.checked);}
updateStats();stats.addEventListener('change',updateStats);
document.getElementById('retry').addEventListener('click',()=>location.reload());

const fullscreen=document.getElementById('fullscreen-toggle'),notice=document.getElementById('fullscreen-status');
const fullscreenElement=()=>document.fullscreenElement||document.webkitFullscreenElement;
function syncFullscreen(){
  const enabled=Boolean(fullscreenElement());
  fullscreen.setAttribute('aria-pressed',String(enabled));
  const label=enabled?'Выйти из полноэкранного режима':'На весь экран';
  fullscreen.title=label;fullscreen.setAttribute('aria-label',label);notice.hidden=true;
}
document.addEventListener('fullscreenchange',syncFullscreen);
document.addEventListener('webkitfullscreenchange',syncFullscreen);
fullscreen.addEventListener('click',async()=>{
  try{
    if(fullscreenElement()){
      const exit=document.exitFullscreen||document.webkitExitFullscreen;
      await exit.call(document);
    }else{
      const root=document.documentElement,request=root.requestFullscreen||root.webkitRequestFullscreen;
      if(!request)throw new Error('unsupported');
      await request.call(root,{navigationUI:'hide'});
    }
    syncFullscreen();
  }catch{
    notice.textContent='Браузер не разрешил полный экран. Откройте страницу в отдельной вкладке браузера и повторите нажатие.';
    notice.hidden=false;
  }
});
