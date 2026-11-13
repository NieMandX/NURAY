import test from 'node:test';
import assert from 'node:assert/strict';
import {survivesFloat32} from './float32_triangle.mjs';

test('quantized sliver at a tile edge cannot become an inverted vertical face',()=>{
  const a=[-735.4677734375,-8.15336799621582,2714.5400390625];
  const b=[-750.0116577148438,-7.732982158660889,2723.282470703125];
  const c=[-735.4910888671875,-8.15336799621582,2714.50146484375];
  const cut=(p,q)=>p.map((v,i)=>i===0?-750:v+(q[i]-v)*(-750-p[0])/(q[0]-p[0]));
  assert.equal(survivesFloat32([cut(a,b),b,cut(b,c)],[a,b,c]),false);
});
test('real centimetre-wide geometry and vertical walls survive at kilometre offsets',()=>{
  assert.equal(survivesFloat32([[3000,1,0],[3020,1,0],[3000,1,.01]]),true);
  assert.equal(survivesFloat32([[3000,1,0],[3020,1,0],[3000,3,0]]),true);
  assert.equal(survivesFloat32([[0,0,0],[1,0,0],[1,0,0]]),false);
});
test('a real winding error is rejected loudly instead of hidden',()=>{
  const t=[[0,0,0],[1,0,0],[0,1,0]];
  assert.throws(()=>survivesFloat32([t[0],t[2],t[1]],t),/reversed/);
});
