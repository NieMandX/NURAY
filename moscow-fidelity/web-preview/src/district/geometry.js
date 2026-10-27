const add=(a,b)=>a.map((x,i)=>x+b[i]);
const cross=(a,b)=>[a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]];
const length=a=>Math.hypot(...a);
const unit=a=>{const l=length(a);return a.map(x=>x/l);};
const fract=x=>x-Math.floor(x);

export function makeDistrict(targetTriangles) {
  const groups=[];let group;const sequence=new Uint32Array(11);
  const quad=(p,u,v,kind,weight=1)=>group.patches.push({p,u,v,kind,seed:sequence[kind]++,weight});
  const triangle=(p,u,v,kind)=>group.patches.push({p,u,v,kind,seed:sequence[kind]++,triangle:true});
  function box(x,y,z,w,h,d,kind,weight=1) {
    quad([x-w/2,y,z+d/2],[w,0,0],[0,h,0],kind,weight);
    quad([x+w/2,y,z-d/2],[-w,0,0],[0,h,0],kind,weight);
    quad([x+w/2,y,z+d/2],[0,0,-d],[0,h,0],kind,weight);
    quad([x-w/2,y,z-d/2],[0,0,d],[0,h,0],kind,weight);
    quad([x-w/2,y+h,z+d/2],[w,0,0],[0,0,-d],kind,weight);
    if(kind===4)quad([x-w/2,y,z-d/2],[w,0,0],[0,0,d],kind,weight);
  }
  // Subdivide the wall around actual openings, so transmitted rays enter the room.
  function wallWithWindows(p,u,v,holes,kind){
    const faceSeed=sequence[kind];
    const xs=[0,1,...holes.flatMap(h=>[h[0],h[1]])].sort((a,b)=>a-b);
    const ys=[0,1,...holes.flatMap(h=>[h[2],h[3]])].sort((a,b)=>a-b);
    for(let y=0;y<ys.length-1;y++)for(let x=0;x<xs.length-1;x++){
      const a=xs[x],b=xs[x+1],c=ys[y],d=ys[y+1];if(b-a<1e-7||d-c<1e-7)continue;
      if(holes.some(h=>(a+b)/2>h[0]&&(a+b)/2<h[1]&&(c+d)/2>h[2]&&(c+d)/2<h[3]))continue;
      quad(p.map((n,i)=>n+u[i]*a+v[i]*c),u.map(n=>n*(b-a)),v.map(n=>n*(d-c)),kind);
      group.patches.at(-1).uvOffset=[a*length(u),c*length(v)];
      group.patches.at(-1).seed=faceSeed;
    }
    sequence[kind]=faceSeed+1;
  }
  function windowFront(x,y,z,w,h,seed) {
    box(x,y,z,w,h,.08,4,.15);
    box(x-w/2-.05,y-.08,z+.03,.12,h+.16,.16,5,.2);
    box(x+w/2+.05,y-.08,z+.03,.12,h+.16,.16,5,.2);
    box(x,y+h,z+.03,w+.22,.12,.16,5,.2);
    box(x,y-.10,z+.06,w+.3,.15,.25,5,.2);
    box(x,y,z+.09,.045,h,.045,3,.1);
    if(seed%2===0)box(x,y+h*.52,z+.09,w,.045,.045,3,.1);
  }
  for(let row=0;row<8;row++)for(let col=0;col<6;col++){
    const id=row*6+col;const x=(col-2.5)*10.5,z=(row-3.5)*11.5;
    group={id,name:`Дом ${id+1}`,patches:[]};groups.push(group);
    const w=5.7+(id%3)*.3,d=7.1+(id%2)*.4,floors=2+(id%7===0?1:0),h=floors*2.65+.45,rise=2.05+(id%4)*.17;
    box(x,-.03,z,w+2.3,.20,d+2.2,5,.12);
    box(x,.14,z,w+.18,.26,d+.18,5,.35);
    const wallKind=id%3===0?0:id%3===1?1:10;
    const frontHoles=[],sideHoles=[];
    for(let f=0;f<floors;f++)for(const sign of [-1,1]){
      frontHoles.push([.5+sign*.27-.55/w,.5+sign*.27+.55/w,(.95+f*2.65-.4)/(h-.4),(2.38+f*2.65-.4)/(h-.4)]);
      sideHoles.push([.5+sign*.27-.525/d,.5+sign*.27+.525/d,(1+f*2.65-.4)/(h-.4),(2.4+f*2.65-.4)/(h-.4)]);
    }
    wallWithWindows([x-w/2,.4,z+d/2],[w,0,0],[0,h-.4,0],frontHoles,wallKind);
    wallWithWindows([x+w/2,.4,z+d/2],[0,0,-d],[0,h-.4,0],sideHoles,wallKind);
    quad([x+w/2,.4,z-d/2],[-w,0,0],[0,h-.4,0],wallKind);
    quad([x-w/2,.4,z-d/2],[0,0,d],[0,h-.4,0],wallKind);
    quad([x-w/2,h,z+d/2],[w,0,0],[0,0,-d],1);
    for(let f=0;f<floors;f++)quad([x-w/2,.4+f*2.65,z+d/2],[w,0,0],[0,0,-d],6,.1);
    box(x,h-.15,z,w+.22,.22,d+.22,5,.4);
    const roof=id%9===0?8:id%9===1?3:id%9===2?9:2;
    quad([x-w/2-.28,h,z-d/2-.3],[0,0,d+.6],[w/2+.28,rise,0],roof,1.2);
    quad([x,h+rise,z-d/2-.3],[0,0,d+.6],[w/2+.28,-rise,0],roof,1.2);
    triangle([x-w/2,h,z+d/2],[w,0,0],[w/2,rise,0],1);
    triangle([x+w/2,h,z-d/2],[-w,0,0],[-w/2,rise,0],1);
    for(const sign of [-1,1]){
      box(x+sign*(w/2+.24),h-.12,z,.13,.16,d+.65,id%2===0?9:8,.3);
      box(x+sign*(w/2-.2),.3,z+d/2+.15,.10,h-.3,.10,id%2===0?9:8,.2);
    }
    box(x-.85,h+rise-.6,z-1.2,.64,1.48,.73,0,.65);
    box(x-.85,h+rise+.84,z-1.2,.83,.12,.92,5,.25);
    for(let f=0;f<floors;f++)for(const sign of [-1,1]){
      windowFront(x+sign*w*.27,.95+f*2.65,z+d/2+.09,1.10,1.43,id+f);
      // Side windows have real raised lintels and recessed dark panes.
      const wz=z+sign*d*.27,wy=1.0+f*2.65;
      box(x+w/2+.035,wy,wz,.10,1.4,1.05,4,.15);
      box(x+w/2+.09,wy-.10,wz,.24,.13,1.26,5,.2);
      box(x+w/2+.06,wy+1.4,wz,.14,.13,1.20,5,.2);
      box(x+w/2+.10,wy,wz,.05,1.4,.04,3,.1);
    }
    box(x,.42,z+d/2+.06,1.10,2.02,.12,6,.3);
    box(x,.3,z+d/2+.48,1.5,.18,.9,5,.3);
    box(x,2.48,z+d/2+.35,1.42,.1,.8,3,.3);
    for(const sign of [-1,1])box(x+sign*2.3,.22,z+d/2+1.02,1.0,.42,.55,0,.5);
  }
  group={id:48,name:'Улицы',patches:[]};groups.push(group);
  quad([-45,-.04,53],[90,0,0],[0,0,-106],5,.005);
  for(let col=0;col<5;col++){
    const x=(col-2)*10.5;
    for(let part=0;part<2;part++)quad([x-1.65,-.02,51-part*51],[3.3,0,0],[0,0,-51],7,.01);
    for(let z=-46;z<48;z+=5)quad([x-.035,-.009,z+1],[.07,0,0],[0,0,-2],5,.01);
  }
  for(let row=0;row<7;row++){
    const z=(row-3)*11.5;
    for(let part=0;part<2;part++)quad([-42+part*42,-.01,z+1.45],[42,0,0],[0,0,-2.9],7,.01);
  }
  const patches=groups.flatMap(g=>g.patches);
  const fixed=patches.filter(p=>p.triangle).length;
  const quads=patches.filter(p=>!p.triangle);
  const cells=(targetTriangles-fixed)/2;
  if(!Number.isInteger(cells)||cells<quads.length)throw new Error('Triangle budget is too small or not even.');
  let area=0;for(const p of quads){p.area=length(cross(p.u,p.v))*p.weight;area+=p.area;}
  let assigned=0;
  for(const p of quads){p.cells=1+Math.floor((cells-quads.length)*p.area/area);assigned+=p.cells;}
  for(let i=0;i<cells-assigned;i++)quads[i%quads.length].cells++;
  let totalVertices=0;
  for(const g of groups){
    g.vertexCount=0;g.triangleCount=0;g.bounds={min:[Infinity,Infinity,Infinity],max:[-Infinity,-Infinity,-Infinity]};
    for(const p of g.patches){
      p.normal=unit(cross(p.u,p.v));p.lu=length(p.u);p.lv=length(p.v);
      if(p.triangle){p.vertices=3;p.triangles=1;}
      else{
        p.nx=Math.min(p.cells,Math.max(1,Math.floor(Math.sqrt(p.cells*p.lu/p.lv))));
        p.ny=Math.max(1,Math.floor(p.cells/p.nx));p.extra=p.cells-p.nx*p.ny;
        p.vertices=(p.nx+1)*(p.ny+1)+p.extra;p.triangles=p.cells*2;
      }
      g.vertexCount+=p.vertices;g.triangleCount+=p.triangles;
      const corners=[p.p,add(p.p,p.u),add(p.p,p.v)];if(!p.triangle)corners.push(add(add(p.p,p.u),p.v));
      for(const c of corners)for(let axis=0;axis<3;axis++){
        g.bounds.min[axis]=Math.min(g.bounds.min[axis],c[axis]-.09);
        g.bounds.max[axis]=Math.max(g.bounds.max[axis],c[axis]+.09);
      }
    }
    totalVertices+=g.vertexCount;
  }
  return {groups,triangles:groups.reduce((n,g)=>n+g.triangleCount,0),vertices:totalVertices,
    bytes:totalVertices*32+targetTriangles*3*4};
}

function relief(u,v,kind){
  if(kind===0){
    const x=fract(u/.47+Math.floor(v/.22)*.5),y=fract(v/.22);
    return .027*Math.min(1,Math.min(x,1-x)*.47/.016)*Math.min(1,Math.min(y,1-y)*.22/.012);
  }
  if(kind===2)return .022*(1-Math.cos(u*18.48))+.013*(1-fract(v/.34));
  if(kind===8||kind===9||kind===3)return .023*Math.pow(Math.max(0,Math.cos(u*12.56)),24);
  return 0;
}
function octahedral(n){
  const s=Math.abs(n[0])+Math.abs(n[1])+Math.abs(n[2]);let x=n[0]/s,y=n[1]/s;
  if(n[2]<0){const old=x;x=(1-Math.abs(y))*(old>=0?1:-1);y=(1-Math.abs(old))*(y>=0?1:-1);}
  return [Math.round(x*32767),Math.round(y*32767)];
}
export function tessellateGroup(group){
  const vertices=new ArrayBuffer(group.vertexCount*32);const floats=new Float32Array(vertices),ints=new Uint32Array(vertices),shorts=new Int16Array(vertices);
  const indices=new Uint32Array(group.triangleCount*3);let vertex=0,index=0;
  function point(p,s,t){
    const uvx=s*p.lu+(p.uvOffset?.[0]??0),uvy=t*p.lv+(p.uvOffset?.[1]??0),h=relief(uvx,uvy,p.kind);
    const du=(relief(uvx+.002,uvy,p.kind)-h)/.002,dv=(relief(uvx,uvy+.002,p.kind)-h)/.002;
    const n=unit(p.normal.map((v,i)=>v-p.u[i]/p.lu*du-p.v[i]/p.lv*dv));
    const packed=octahedral(n);const offset=vertex*8;
    for(let i=0;i<3;i++)floats[offset+i]=p.p[i]+p.u[i]*s+p.v[i]*t+p.normal[i]*h;
    shorts[vertex*16+6]=packed[0];shorts[vertex*16+7]=packed[1];
    floats[offset+4]=uvx;floats[offset+5]=uvy;ints[offset+6]=(p.seed<<4)|p.kind;
    return vertex++;
  }
  function tri(a,b,c){indices[index++]=a;indices[index++]=b;indices[index++]=c;}
  for(const p of group.patches){
    const base=vertex;
    if(p.triangle){point(p,0,0);point(p,1,0);point(p,0,1);tri(base,base+1,base+2);continue;}
    for(let y=0;y<=p.ny;y++)for(let x=0;x<=p.nx;x++)point(p,x/p.nx,y/p.ny);
    for(let y=0;y<p.ny;y++)for(let x=0;x<p.nx;x++){
      const a=base+y*(p.nx+1)+x,b=a+1,c=a+p.nx+1,d=c+1;
      if(y*p.nx+x<p.extra){const middle=point(p,(x+.5)/p.nx,(y+.5)/p.ny);tri(a,b,middle);tri(b,d,middle);tri(d,c,middle);tri(c,a,middle);}
      else{tri(a,b,c);tri(b,d,c);}
    }
  }
  if(vertex!==group.vertexCount||index!==indices.length)throw new Error('Mesh allocation mismatch.');
  return {vertices,indices:indices.buffer};
}
