// UI colors are sRGB; renderer and glTF baseColorFactor use linear RGB.
export function normalizeColor(value){return /^#[0-9a-f]{6}$/i.test(value??'')?value.toLowerCase():null;}
export function colorToLinear(hex){
  if(!normalizeColor(hex))throw Error('Цвет должен быть в формате #RRGGBB');
  return [1,3,5].map(i=>{const c=parseInt(hex.slice(i,i+2),16)/255;return c<=.04045?c/12.92:((c+.055)/1.055)**2.4;});
}
export function linearToColor(rgb){return '#'+rgb.map(v=>{const c=Math.max(0,Math.min(1,v));return Math.round(255*(c<=.0031308?12.92*c:1.055*c**(1/2.4)-.055)).toString(16).padStart(2,'0');}).join('');}
export function foliagePalette(palette,hex){
  const target=colorToLinear(hex),reference=palette[0].color;
  // Retain the source light/deep foliage variations and all wood/PBR properties.
  return palette.map((m,i)=>i<4?{...m,color:m.color.map((c,k)=>Math.min(1,c*target[k]/reference[k]))}:m);
}
