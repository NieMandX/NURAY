// Adapter discovery can remain pending indefinitely on unavailable drivers.
// Late devices must be released after the fallback has taken over.
export function withDeadline(promise,milliseconds,message,onLate=()=>{}){
  return new Promise((resolve,reject)=>{
    let expired=false;
    const timer=setTimeout(()=>{expired=true;reject(new Error(message));},milliseconds);
    Promise.resolve(promise).then(value=>{clearTimeout(timer);if(expired)onLate(value);else resolve(value);},error=>{clearTimeout(timer);if(!expired)reject(error);});
  });
}
