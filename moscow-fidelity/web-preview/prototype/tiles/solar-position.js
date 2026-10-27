// NOAA solar equations, east-positive longitude; output uses X east, Y up, Z south.
// https://gml.noaa.gov/grad/solcalc/solareqns.PDF
const RAD=Math.PI/180,clamp=(x,a,b)=>Math.max(a,Math.min(b,x));
export function calendarDate(now=new Date(),timeZone='Europe/Moscow'){
 const p=Object.fromEntries(new Intl.DateTimeFormat('en-GB',{timeZone,year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(now).map(p=>[p.type,p.value]));return `${p.year}-${p.month}-${p.day}`;
}
export function localClock(now=new Date(),timeZone='Europe/Moscow'){
 const p=Object.fromEntries(new Intl.DateTimeFormat('en-GB',{timeZone,hourCycle:'h23',hour:'2-digit',minute:'2-digit'}).formatToParts(now).map(p=>[p.type,p.value]));return Number(p.hour)*60+Number(p.minute);
}
function terms(date,minute,offset){
 const day=new Date(`${date}T00:00:00Z`),year=day.getUTCFullYear(),yearStart=Date.UTC(year,0,1),days=(Date.UTC(year+1,0,1)-yearStart)/86400000;
 const gamma=2*Math.PI/days*((+day-yearStart)/86400000+(minute/60-offset-12)/24);
 return {equation:229.18*(.000075+.001868*Math.cos(gamma)-.032077*Math.sin(gamma)-.014615*Math.cos(2*gamma)-.040849*Math.sin(2*gamma)),declination:.006918-.399912*Math.cos(gamma)+.070257*Math.sin(gamma)-.006758*Math.cos(2*gamma)+.000907*Math.sin(2*gamma)-.002697*Math.cos(3*gamma)+.00148*Math.sin(3*gamma)};
}
export function solarPosition(date,minute,geo){
 const {equation,declination:d}=terms(date,minute,geo.utcOffset),lat=geo.latitude*RAD,h=(minute+equation+4*geo.longitude-60*geo.utcOffset)/4*RAD-Math.PI;
 const east=-Math.cos(d)*Math.sin(h),north=Math.cos(lat)*Math.sin(d)-Math.sin(lat)*Math.cos(d)*Math.cos(h),up=Math.sin(lat)*Math.sin(d)+Math.cos(lat)*Math.cos(d)*Math.cos(h);
 const altitude=Math.asin(clamp(up,-1,1))/RAD,azimuth=(Math.atan2(east,north)/RAD+360)%360;
 return {direction:[east,up,-north],altitude,azimuth};
}
export function daylight(date,geo){
 // Find the two horizon crossings numerically, including high latitudes and leap days.
 const altitude=m=>solarPosition(date,m,geo).altitude+.833;
 const roots=[];let before=altitude(0);
 for(let t=5;t<=1440;t+=5){const after=altitude(t);if(before*after<0){let a=t-5,b=t;for(let j=0;j<25;j++){const m=(a+b)/2;if(altitude(a)*altitude(m)<=0)b=m;else a=m;}roots.push({minute:(a+b)/2,rising:after>before});}before=after;}
 const rise=roots.find(r=>r.rising)?.minute,set=roots.find(r=>!r.rising)?.minute;
 if(rise===undefined&&set===undefined)return {rise:0,set:1440,polar:altitude(720)>0?'day':'night'};
 return {rise:rise??0,set:set??1440,polar:null};
}
export const clockLabel=minute=>`${String(Math.floor(minute/60)%24).padStart(2,'0')}:${String(Math.floor(minute)%60).padStart(2,'0')}`;
