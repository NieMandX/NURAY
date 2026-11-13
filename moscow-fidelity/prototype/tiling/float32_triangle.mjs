// Tile clipping can leave a needle narrower than the stored position grid.
// Discard only collapsed/inverted numerical remnants, never a real face.
const cross=(a,b)=>[a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]];
const sub=(a,b)=>a.map((v,i)=>v-b[i]);
const normal=t=>cross(sub(t[1],t[0]),sub(t[2],t[0]));
export function survivesFloat32(triangle,source=triangle){
  const p=triangle.map(v=>v.slice(0,3).map(Math.fround)),n=normal(p),area2=Math.hypot(...n);
  if(area2<1e-9)return false;
  const reference=normal(source.map(v=>v.slice(0,3)));
  if(n.reduce((s,v,i)=>s+v*reference[i],0)>0)return true;
  const longest=Math.max(...p.map((v,i)=>Math.hypot(...sub(v,p[(i+1)%3]))));
  const grid=Math.max(2**-149,...p.flat().map(v=>Math.abs(v)*2**-23));
  if(area2/longest<=grid*4)return false;
  throw Error('Tile clipping reversed a non-numeric triangle');
}
