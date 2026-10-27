// Byte ranges of root fields, without V8's single-string limit.
import fs from 'node:fs';
const file=process.argv[2],fd=fs.openSync(file,'r'),stat=fs.fstatSync(fd);
let depth=0,quoted=false,escaped=false,keyStart=0,valueStart=null,fields=[];
const buffer=Buffer.alloc(8*1024*1024);
for(let offset=0;offset<stat.size;){
 const size=fs.readSync(fd,buffer,0,buffer.length,offset);
 for(let i=0;i<size;i++){
  const ch=buffer[i],pos=offset+i;
  if(quoted){if(escaped)escaped=false;else if(ch===92)escaped=true;else if(ch===34)quoted=false;continue;}
  if(ch===34){quoted=true;continue;}
  if(ch===123||ch===91){depth++;if(depth===1)keyStart=pos+1;continue;}
  if(depth===1&&ch===58&&valueStart===null){valueStart=pos+1;continue;}
  if(depth===1&&(ch===44||ch===125)){
   if(valueStart!==null){
    const keyBuffer=Buffer.alloc(valueStart-keyStart-1);fs.readSync(fd,keyBuffer,0,keyBuffer.length,keyStart);
    fields.push({key:JSON.parse(keyBuffer.toString('utf8').trim()),start:valueStart,end:pos});
   }
   keyStart=pos+1;valueStart=null;
  }
  if(ch===125||ch===93)depth--;
 }
 offset+=size;
}
fs.closeSync(fd);
if(depth||quoted)throw Error('Incomplete JSON document');
fs.writeFileSync(process.argv[3],JSON.stringify({bytes:stat.size,mtimeMs:stat.mtimeMs,fields}));
