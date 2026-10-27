import {surfaceFunctions} from './water-shaders.js?v=shore-water-1';
export const waterSkyVertex=`#version 300 es
precision highp float;
out vec2 ndc;
void main(){ndc=vec2(float((gl_VertexID<<1)&2),float(gl_VertexID&2))*2.-1.;gl_Position=vec4(ndc,1.,1.);}`;
export const waterSkyFragment=`#version 300 es
precision highp float;
precision highp int;
uniform vec3 sun,camForward,camRight,camUp;
uniform float sunPower,exposure;
in vec2 ndc;out vec4 result;
${surfaceFunctions}
void main(){vec3 dir=normalize(camForward+ndc.x*camRight+ndc.y*camUp);if(waterP[3].y>3.5){result=vec4(hwGrade(hwSky(dir,sun)+hwDisc(dir,sun,length(fwidth(dir)))*waterP[5].y),1);return;}vec3 c=waterSky(dir,0.);if(waterP[3].y>1.5){result=vec4(mix(vec3(.70,.735,.745),seaGrade(seaSky(dir,sun),waterP[5].x),seaLightWeight()),1);return;}c*=exposure;result=vec4(pow(c/(c+vec3(1)),vec3(1./2.2)),1.);}`;
