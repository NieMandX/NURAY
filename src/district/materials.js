export const MATERIAL_KINDS=['Кирпич','Бетон','Черепица','Сталь','Стекло','Камень','Дерево','Асфальт','Медь','Алюминий','Штукатурка'];
export const TEXTURE_SIZE=128;
const linear=c=>c<=.04045?c/12.92:((c+.055)/1.055)**2.4;
const rgb=hex=>[1,3,5].map(i=>linear(parseInt(hex.slice(i,i+2),16)/255));
const specifications=[
  [rgb('#a45d44'),.78,0,1.5,1/1.88,1/.88],
  [rgb('#b5b5ad'),.88,0,1.5,1,1],
  [rgb('#924a32'),.61,0,1.5,1,1],
  [[.56,.57,.58],.29,1,1,1,1],
  [rgb('#e1f0ed'),.035,0,1.5,1,1],
  [rgb('#bbb2a0'),.70,0,1.5,1,1],
  [rgb('#614533'),.68,0,1.5,1,1],
  [rgb('#4c5254'),.94,0,1.5,1,1],
  [[.952,.620,.511],.26,1,1,1,1],
  [[.913,.922,.924],.22,1,1,1,1],
  [rgb('#cfbda0'),.83,0,1.5,1,1],
];
export function makeMaterials(count){
  const data=new Float32Array(count*12);
  for(let i=0;i<count;i++){
    const kind=count===1?1:i%11;const [color,roughness,metal,ior,su,sv]=specifications[kind];
    const variant=Math.floor(i/11);const variation=count===1?1:1+(Math.sin(variant*2.17+kind)*.12);
    let tint=color.map(c=>Math.min(.99,c*variation));
    if(kind===10&&variant%3===1)tint=rgb('#aebcbb');
    if(kind===10&&variant%3===2)tint=rgb('#cdb7a6');
    data.set([...tint,roughness,metal,ior,kind,0,su,sv,0,0],i*12);
  }
  return data;
}
export function textureBytes(count){let size=TEXTURE_SIZE,total=0;while(size>=1){total+=size*size*count*4*3;size=Math.floor(size/2);}return total;}
export function materialIndex(kind,seed,count){return count===1?0:kind+11*(seed%Math.floor((count+10-kind)/11));}
