// Derived packing cache. A live-source receipt and the exact packer code
// isolate acquisitions and algorithm versions. Every cached payload is checked.
import fs from 'node:fs/promises';
import path from 'node:path';
import {createHash} from 'node:crypto';
import {gunzipSync} from 'node:zlib';
const sha=data=>createHash('sha256').update(data).digest('hex');

export function packingKey(context,chunk,bytes){
 return sha(JSON.stringify({context,chunk,sha256:sha(bytes)}));
}

export async function readPacked(folder,key){
 try{
  const rows=JSON.parse(await fs.readFile(path.join(folder,key+'.json'),'utf8'));
  const payloads=[];
  for(const row of rows){
   if(row.file!==`meshes/${row.sha256}.bin.gz`)return null;
   const bytes=await fs.readFile(path.join(folder,row.file));
   if(bytes.length!==row.downloadBytes||sha(gunzipSync(bytes))!==row.sha256)return null;
   payloads.push({row,bytes});
  }
  return payloads;
 }catch(error){if(error.code==='ENOENT'||error instanceof SyntaxError||error.code==='Z_DATA_ERROR')return null;throw error;}
}

export async function savePacked(folder,key,rows,root){
 await fs.mkdir(path.join(folder,'meshes'),{recursive:true});
 for(const row of rows)await fs.copyFile(path.join(root,row.file),path.join(folder,row.file));
 const temporary=path.join(folder,key+'.tmp');
 await fs.writeFile(temporary,JSON.stringify(rows));
 await fs.rename(temporary,path.join(folder,key+'.json'));
}
