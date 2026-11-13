const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
const source=fs.readFileSync(path.resolve(process.env.DGIS_LIVE_ROOT,'browser/rarity-3d.js'),'utf8');
const context={self:{webpackChunk:[]},console,TextDecoder,TextEncoder,performance,setTimeout,clearTimeout,URL};
vm.createContext(context);vm.runInContext(source,context);
const raw=context.self.webpackChunk[0][1][28549].toString();
const registry={};context._mapgl_d=(name,deps,fn)=>{registry[name]=fn};
let registers=raw.slice(raw.indexOf('_mapgl_d("shared"'),-1);
// Debug extraction must retain successive strips sharing unchanged attributes.
if(registers.includes('if(!x&&0===N_.length)')) {
 registers=registers.replace('if(!x&&0===N_.length)', 'if(!b&&!x&&0===N_.length)');
 registers=registers.replace('e.ZenithWorker=class','e.__decodeDem=dl,e.__decodeTileGroups=Dn,e.__generateGeo=R_,e.__tileUrl=Xn,e.__metaHash=Bi,e.ZenithWorker=class');
 registers=registers.replace('s.addFeature({type:"Feature",properties:t,geometry:e})','s.addFeature({type:"Feature",properties:t,geometry:e,_raw:Object.fromEntries(Object.entries(B_).map(([k,v])=>[k,Array.from(v)]))})');
} else if(require('node:crypto').createHash('sha256').update(source).digest('hex') === '1a99a832631239d06218f76f7d5ef6a842d26df56e5d78eef69e513d360bca18' &&
          registers.includes('function cg(e,t,i,n,r,o,s,a,l=!1,c,d,u,h)') &&
          registers.includes('if(!x&&0===hg.length)') &&
          registers.includes('function gl(e){if(0===e.byteLength)return{positions:new Uint16Array,heights:new Float32Array')) {
 // Public rarity-3d.cafdbdac90687d9e6160.js, inspected 2026-11-12.
 // Same debug-geometry branch and stream layout; minified symbol names changed.
 registers=registers.replace('if(!x&&0===hg.length)', 'if(!b&&!x&&0===hg.length)');
 registers=registers.replace('e.ZenithWorker=class','e.__decodeDem=gl,e.__decodeTileGroups=Nn,e.__generateGeo=cg,e.__tileUrl=Jn,e.__metaHash=Ni,e.ZenithWorker=class');
 registers=registers.replace('s.addFeature({type:"Feature",properties:t,geometry:e})','s.addFeature({type:"Feature",properties:t,geometry:e,_raw:Object.fromEntries(Object.entries(lg).map(([k,v])=>[k,Array.from(v)]))})');
} else throw Error('Current decoder signature changed');
vm.runInContext(registers,context);const core={};registry.shared(core);
module.exports=core;
