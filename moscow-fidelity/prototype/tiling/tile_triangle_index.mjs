// Compact candidate references only. Actual clipping, ownership, vertex
// encoding and BVH construction remain in pack_tiles, unchanged.
export function tileTriangleIndex(f,ix,tiles,{columns,rows,tileSize,x0,y0,ox,oy}){
 const counts=new Uint32Array(tiles.length);
 function visit(emit){
  for(let i=0;i<ix.length;i+=3){
   const a=ix[i]*8,b=ix[i+1]*8,c=ix[i+2]*8;
   const lx=Math.min(f[a],f[b],f[c]),hx=Math.max(f[a],f[b],f[c]);
   const lz=Math.min(f[a+2],f[b+2],f[c+2]),hz=Math.max(f[a+2],f[b+2],f[c+2]);
   const e0=Math.max(0,Math.floor((lx+ox-x0)/tileSize)-1),e1=Math.min(columns-1,Math.floor((hx+ox-x0)/tileSize));
   const n0=Math.max(0,Math.floor((oy-hz-y0)/tileSize)-1),n1=Math.min(rows-1,Math.floor((oy-lz-y0)/tileSize));
   for(let north=n0;north<=n1;north++)for(let east=e0;east<=e1;east++){
    const j=north*columns+east,tile=tiles[j],bounds=tile.bounds;
    if(hx<bounds.min[0]||lx>bounds.max[0]||hz<bounds.min[2]||lz>bounds.max[2])continue;
    if(lx===hx&&lx===bounds.max[0]&&tile.east<columns-1)continue;
    if(lz===hz&&lz===bounds.min[2]&&tile.north<rows-1)continue;
    emit(j,i/3);
   }
  }
 }
 visit(j=>{if(counts[j]===0xffffffff)throw Error('Tile candidate count exceeds uint32');counts[j]++;});
 const offsets=new Uint32Array(tiles.length+1);let total=0;
 for(let j=0;j<tiles.length;j++){offsets[j]=total;total+=counts[j];if(total>0xffffffff)throw Error('Tile candidate index exceeds uint32');}
 offsets[tiles.length]=total;
 const triangles=new Uint32Array(total),cursor=offsets.slice(0,-1);
 visit((j,primitive)=>{triangles[cursor[j]++]=primitive;});
 return {offsets,triangles};
}
