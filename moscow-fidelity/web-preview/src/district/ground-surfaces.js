// Semantic coverage classes, never an RGB match or a particular city/object ID.
const STANDARD_GROUND=new Set(['Территория / покрытие','Пешеходное покрытие']);
export const isStandardGround=m=>m?.kind===1&&STANDARD_GROUND.has(m.family||m.name);
// The shared material record's facade marker is signed: +1 facade, -1 ground.
// Existing facade and trace paths test > .5 and therefore keep their behavior.
export function upwardPackedNormal(word){
 let x=(word<<16>>16)/32767,y=(word>>16)/32767,z=1-Math.abs(x)-Math.abs(y);
 const t=Math.max(-z,0);x+=x>=0?-t:t;y+=y>=0?-t:t;
 return y/Math.hypot(x,y,z)>.96;
}
