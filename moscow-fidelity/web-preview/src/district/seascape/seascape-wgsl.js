// Adapted from “Seascape” © Alexander Alekseev (TDM), 2014.
// CC BY-NC-SA 3.0; see PROVENANCE.md and Seascape.original.glsl.
export const SEASCAPE_SKY_WGSL=`
fn seaSky(d:vec3f,sun:vec3f)->vec3f {
 let y=(max(d.y,0.0)*.8+.2)*.8;
 let sky=vec3f(pow(1.0-y,2.0),1.0-y,.6+(1.0-y)*.4)*1.1;
 return sky*mix(.025,1.0,smoothstep(-.08,.12,sun.y));
}
fn seaGrade(color:vec3f,exposure:f32)->vec3f {return clamp(pow(max(color*exposure,vec3f(0)),vec3f(.65)),vec3f(0),vec3f(1));}
`;
export const SEASCAPE_WGSL=SEASCAPE_SKY_WGSL+`
fn seaHash(p:vec2f)->f32 {return fract(sin(dot(p,vec2f(127.1,311.7)))*43758.5453123);}
fn seaNoise(p:vec2f)->f32 {
 let i=floor(p);let f=fract(p);let u=f*f*(3.0-2.0*f);
 return -1.0+2.0*mix(mix(seaHash(i),seaHash(i+vec2f(1,0)),u.x),mix(seaHash(i+vec2f(0,1)),seaHash(i+vec2f(1,1)),u.x),u.y);
}
fn seaOctave(p:vec2f,choppy:f32)->f32 {
 let uv=p+seaNoise(p);let w=1.0-abs(sin(uv));let sw=abs(cos(uv));let wave=mix(w,sw,w);
 return pow(max(0.0,1.0-pow(wave.x*wave.y,.65)),choppy);
}
// F.viewProj is unused by our finite city mesh. Its first column stores the
// Seascape height/frequency/choppiness/speed; the second stores exposure.
fn seaHeight(p:vec2f,footprint:f32)->f32 {
 let params=F.viewProj[0];let wd=F.windP[0].xy;
 var uv=vec2f(dot(p,wd)*.75,dot(p,vec2f(-wd.y,wd.x)));
 var freq=params.y;var amp=params.x;var choppy=params.z;var height=0.0;var wavelength=1.0;
 let time=1.0+F.camPos.w*params.w;
 for(var i=0;i<5;i++){
  let aa=1.0-smoothstep(.6,2.4,footprint*freq*wavelength);
  let d=seaOctave((uv+time)*freq,choppy)+seaOctave((uv-time)*freq,choppy);
  height+=d*amp*aa;
  uv=vec2f(uv.x*1.6+uv.y*1.2,-uv.x*1.2+uv.y*1.6);freq*=1.9;amp*=.22;wavelength*=2.0;choppy=mix(choppy,1.0,.2);
 }
 return height;
}
fn seascapeShade(world:vec3f,shore:f32,shadow:f32)->vec4f {
 let footprint=max(length(dpdx(world).xz),length(dpdy(world).xz));let eps=max(.025,footprint*.5);
 let h=seaHeight(world.xz,footprint);
 let n=normalize(vec3f(h-seaHeight(world.xz+vec2f(eps,0),footprint),eps,h-seaHeight(world.xz+vec2f(0,eps),footprint)));
 let eye=normalize(world-frame.camera.xyz);let dist=length(world-frame.camera.xyz);let sun=frame.sun.xyz;
 let fr=waterFresnel(dot(n,-eye));
 let reflected=oceanEnvironment(reflect(eye,n),.08);
 let waterColor=F.sssCol.rgb;
 let sunColor=waterSun()*.4;
 let diffuse=pow(max(dot(n,sun)*.4+.6,0.0),80.0);
 let base=waterBody(dot(n,-eye));
 let refracted=base*(oceanAmbient(n)*2.0)+diffuse*waterColor*.12*sunColor*shadow;
 var color=mix(refracted,reflected,fr);
 let atten=max(1.0-dist*dist*.00001,0.0);
 color+=waterColor*(h-F.viewProj[0].x)*.18*atten;
 let power=max(12.0,600.0/sqrt(max(dist,1.0)));
 color+=pow(max(dot(reflect(eye,n),sun),0.0),power)*(power+8.0)/(3.14159265*8.0)*sunColor*shadow*waterFresnel(dot(n,-eye));
 let coast=waterFoam(world.xz,shore,F.camPos.w,footprint)*F.windP[1].x;
 let crest=smoothstep(1.65,2.3,h/max(F.viewProj[0].x,.001))*F.foamP.z*.15;
 let foam=clamp(coast+crest,0.0,.75);
 let foamLight=vec3f(.65,.68,.66)*(oceanAmbient(n)+sunColor*max(dot(n,sun),0.0)*shadow*.3);
 color=mix(color,foamLight,foam);
 return vec4f(max(color,vec3f(0)),1);
}
`;
