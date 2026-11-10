import test from 'node:test';
import assert from 'node:assert/strict';
import {areaTileIds,hydrateAreas} from '../prototype/tiles/manual-areas.js';
import {TileRenderer} from '../prototype/tiles/tile-renderer.js';
import {activeChunkIds,sceneInstances} from '../prototype/tiles/tile-scene.js';

const index={initial:{tileIds:['a']},shards:[{id:'left',tileIds:['a','b'],asset:{url:'left'}},{id:'right',tileIds:['c'],asset:{url:'right'}}]};
function fixture(){
  const tree={id:'tree',instanced:true};
  return {base:new URL('https://example.test/scene/'),assets:new Map([['tree',tree]]),streamStats:{requests:0,downloadBytes:0},
    state:{engine:'raster'},camera:{target:[0,0,0]},tileset:{manualAreas:index,chunks:[tree],tiles:['a','b','c'].map(id=>({id,chunks:[],coarseChunks:[]}))},
    fitTraceTiles:TileRenderer.prototype.fitTraceTiles};
}
const read=async spec=>({chunks:(spec.url==='left'?['a','b']:['c']).map(id=>({id:'mesh-'+id})),
  tiles:(spec.url==='left'?['a','b']:['c']).map(id=>({id,chunks:['mesh-'+id],coarseChunks:[],instances:[{mesh:'tree',sourceId:id}]}))});

test('manual residency stays inside explicit selection when camera moves; shard neighbours are not loaded',async()=>{
  const r=fixture();r.manualTiles=areaTileIds(index);await hydrateAreas(r,r.manualTiles,read);
  const choose=()=>TileRenderer.prototype.chooseTiles.call(r,{full:true});
  assert.deepEqual([...choose().keys()],['a']);
  assert.deepEqual([...activeChunkIds(r.tileset,choose())],['mesh-a','tree']);
  r.camera={target:[10000,0,10000],distance:20000};
  assert.deepEqual([...choose().keys()],['a']);
  assert.equal(r.streamStats.requests,1);
  assert.equal(r.assets.has('mesh-c'),false);
});

test('adding overlapping areas and resetting retains shared models once and never duplicates instances',async()=>{
  const r=fixture();let ids=areaTileIds(index,['left']);await hydrateAreas(r,ids,read);
  assert.deepEqual([...ids],['a','b']);
  ids=areaTileIds(index,['left','right']);await hydrateAreas(r,ids,read);await hydrateAreas(r,ids,read);
  assert.equal(r.streamStats.requests,2);assert.equal(r.tileset.chunks.length,4);
  assert.equal(sceneInstances(r.tileset,new Map([...ids].map(id=>[id,'full']))).filter(i=>i.mesh==='tree').length,3);
  const reset=new Map([...areaTileIds(index)].map(id=>[id,'full']));
  assert.deepEqual([...activeChunkIds(r.tileset,reset)],['mesh-a','tree']);
});

test('a failed metadata transfer does not mark a shard loaded or partially commit selection',async()=>{
  const r=fixture();await assert.rejects(hydrateAreas(r,areaTileIds(index,['right']),async s=>{if(s.url==='right')throw Error('network');return read(s);}),/network/);
  assert.equal(r.areaShards.size,0);assert.equal(r.assets.size,1);
  await hydrateAreas(r,areaTileIds(index),read);assert.equal(r.areaShards.size,1);
});
