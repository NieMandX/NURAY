/** Acquire current style assets into the same dated snapshot. */
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const root=path.resolve(process.argv[2]);
const plan=JSON.parse(fs.readFileSync(path.join(root,'plan.json')));
const out=path.join(root,'output',plan.output_subdir||'area_5000');
const assets=JSON.parse(fs.readFileSync(path.join(out,'resources.json')));
const receipt=path.join(root,'style-resources.json');
const rows=fs.existsSync(receipt)?JSON.parse(fs.readFileSync(receipt)):[];
const sha=b=>crypto.createHash('sha256').update(b).digest('hex');
let next=0;
async function worker(){while(next<assets.length){
 const a=assets[next++],prior=rows.find(r=>r.url===a.url);
 if(prior&&fs.existsSync(a.file)&&sha(fs.readFileSync(a.file))===prior.sha256)continue;
 for(let attempt=0;attempt<4;attempt++)try{
  const response=await fetch(a.url,{headers:{'Cache-Control':'no-cache'},signal:AbortSignal.timeout(120000)});
  if(!response.ok)throw Error('HTTP '+response.status);
  const b=Buffer.from(await response.arrayBuffer());fs.writeFileSync(a.file,b);
  rows.push({...a,bytes:b.length,sha256:sha(b),retrievedAt:new Date().toISOString()});
  fs.writeFileSync(receipt,JSON.stringify(rows,null,2));console.log('Style asset',rows.length,'/',assets.length,path.basename(a.file));break;
 }catch(e){if(attempt===3)throw Error(a.url+': '+e.message);}
}}
Promise.all([worker(),worker(),worker()]).then(()=>console.log('STYLE COMPLETE',rows.length)).catch(e=>{console.error(e);process.exitCode=1;});
