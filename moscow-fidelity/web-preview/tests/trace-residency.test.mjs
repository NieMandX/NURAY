import test from 'node:test';
import assert from 'node:assert/strict';
import {TileRenderer} from '../prototype/tiles/tile-renderer.js';
import {planGpuPages} from '../prototype/tiles/gpu-pages.js';
function scene(){
 const f={state:{engine:'trace'},streamStats:{},pageLimit:200,camera:{target:[0,0,0]},tileset:{tiles:[],chunks:[]}};
 for(let i=0;i<9;i++){
  f.tileset.tiles.push({id:String(i),bounds:{min:[i*10,0,0],max:[i*10+5,10,5]},chunks:[String(i)],coarseChunks:[String(i)]});
  f.tileset.chunks.push({id:String(i),vertexBytes:100,indexBytes:20,nodeBytes:30});
 }return f;
}
test('Ray residency fits four GPU pages, keeps nearest tiles, follows moved camera',()=>{
 const f=scene(),m=new Map(f.tileset.tiles.map(t=>[t.id,'full']));
 const result=TileRenderer.prototype.fitTraceTiles.call(f,m);
 assert.deepEqual([...result.keys()],['0','1','2','3']);assert.ok(f.streamStats.budgetLimited);
 assert.ok(planGpuPages(f.tileset,f.pageLimit,4,result).every(p=>p.bytes<=f.pageLimit));
 f.camera.target=[90,0,0];assert.deepEqual([...TileRenderer.prototype.fitTraceTiles.call(f,m).keys()],['8','7','6','5']);
 f.state.engine='raster';assert.equal(TileRenderer.prototype.fitTraceTiles.call(f,m),m);assert.equal(f.streamStats.budgetLimited,false);
});
