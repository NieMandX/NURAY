// Semantic coverage classes, never an RGB match or a particular city/object ID.
const STANDARD_GROUND=new Set(['Территория / покрытие','Пешеходное покрытие']);
export const isStandardGround=m=>m?.kind===1&&STANDARD_GROUND.has(m.family||m.name);
const DRY_GROUND=new Set([...STANDARD_GROUND,'Асфальт','Газон','green-cover',
 'Неопределённая территория','Кладбище · зелёное покрытие','parking-asphalt',
 'pedestrian-asphalt','pedestrian-stone','pedestrian-gravel','pedestrian-sand','pedestrian-wood',
 'Пешеходный переход · светлое покрытие','Транспортное полотно · светлое покрытие','Велодорожка']);
export const isDryGround=m=>m?.kind===1&&(m.metallic??0)===0&&
 (DRY_GROUND.has(m.family||m.name)||(m.family||m.name||'').startsWith('Площадка · '));
// Signed facade marker: +1 facade, -1 beige ground with optional reflective
// finish, -2 other dry coverage. Trace's > .5 facade test remains unchanged.
export const groundMaterialRole=m=>isDryGround(m)?(isStandardGround(m)?-1:-2):0;
export function upwardPackedNormal(word){
 let x=(word<<16>>16)/32767,y=(word>>16)/32767,z=1-Math.abs(x)-Math.abs(y);
 const t=Math.max(-z,0);x+=x>=0?-t:t;y+=y>=0?-t:t;
 return y/Math.hypot(x,y,z)>.96;
}
