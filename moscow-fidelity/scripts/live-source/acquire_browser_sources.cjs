/** Download only decoder/style URLs observed in the current public 2GIS page. */
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const root=path.resolve(process.argv[2]);
const evidence=JSON.parse(fs.readFileSync(path.join(root,'browser/observed-resources.json')));
(async()=>{
 const receipts=[];
 for(const [name,url] of Object.entries(evidence.resources)){
  const r=await fetch(url,{headers:{'Cache-Control':'no-cache'},signal:AbortSignal.timeout(120000)});
  if(!r.ok)throw Error(`${name}: HTTP ${r.status}`);
  const b=Buffer.from(await r.arrayBuffer()),file='browser/'+name;
  fs.writeFileSync(path.join(root,file),b);
  receipts.push({url,file,bytes:b.length,sha256:crypto.createHash('sha256').update(b).digest('hex'),retrievedAt:new Date().toISOString(),status:r.status});
 }
 fs.writeFileSync(path.join(root,'browser-resources.json'),JSON.stringify(receipts,null,2));
 fs.mkdirSync(path.join(root,'source'),{recursive:true});
 const style=JSON.parse(fs.readFileSync(path.join(root,'browser/map_style.json')));
 const flat=[];function visit(layers){for(const l of layers){if(l.type)flat.push(l);if(l.layers)visit(l.layers);}}
 visit(style.result.layers);
 fs.writeFileSync(path.join(root,'source/map_style.json'),JSON.stringify(style));
 fs.writeFileSync(path.join(root,'source/style_flat.json'),JSON.stringify(flat));
 console.log('Fresh browser resources',receipts.length,'flat style layers',flat.length);
})().catch(e=>{console.error(e);process.exitCode=1;});
