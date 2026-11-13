#!/usr/bin/env node
// Diagnostic adapter for the exact public Maps decoder observed on 2026-11-12.
// The vendor bundle is supplied locally, never copied into this repository.
// Running it in a VM without browser/network access avoids starting its worker.
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const crypto = require('node:crypto');
const zlib = require('node:zlib');

const [root, workerPath] = process.argv.slice(2);
if (!root || !workerPath) throw new Error('Usage: decode_region.cjs CAPTURE_DIR OBSERVED_WORKER_JS');
let code = fs.readFileSync(workerPath, 'utf8');
const decoderHash = crypto.createHash('sha256').update(code).digest('hex');
if (decoderHash !== 'd7c3781a99412f9202d37d2ab09f2fb15ae80f3b8950b53dcb69d9ecef00a44a') {
  throw new Error('Unreviewed decoder version; inspect the new vendor format first');
}
const initializer = 'Zce=new Hp(new Ds(self).run())';
if (!code.includes(initializer)) throw new Error('Worker initializer changed');
code = code.replace(initializer, 'Zce=null;globalThis.codec=TM;globalThis.extractTile=bM');
const sandbox = {self: {}, TextDecoder, TextEncoder, atob, btoa, performance, URL,
  ArrayBuffer, Uint8Array, Float32Array, DataView};
vm.createContext(sandbox);
vm.runInContext(code, sandbox, {timeout: 20000});

const manifest = JSON.parse(fs.readFileSync(path.join(root, 'manifest.json'), 'utf8'));
const plan = JSON.parse(fs.readFileSync(path.join(root, 'plan.json'), 'utf8'));
if (!manifest.complete || manifest.files.length !== plan.tiles.length) throw new Error('Incomplete capture');
const retained = new Set(['land', 'landcover', 'landuse_a', 'vegetation', 'vegetation_planned',
  'hydro_a', 'hydro_l', 'hydro_overlay', 'building', 'model_a', 'model_p', 'fence_a',
  'road', 'roadnet_a', 'transport_way', 'hd_road_surface', 'hd_road_surface_border',
  'hd_road_surface_overlay', 'hd_road_marking_l', 'hd_road_marking_a', 'hd_road_vegetation',
  'hd_road_interchange', 'hd_road_tunnel_hole', 'road_underpass', 'terrain', 'bathymetry']);
const summary = {displayZoom: 21, decoderHash, containers: manifest.files.length,
  sourceBytes: manifest.bytes, layers: {}, types: {}, buildingHeight: {known: 0, missing: 0},
  data3dBytes: 0, unsafeIds: 0, richModels: {}, meshIds: [], geometryValidated: true};
const meshIds = new Set();
fs.mkdirSync(path.join(root, 'decoded'), {recursive: true});
const count = (table, key) => table[key] = (table[key] || 0) + 1;
for (const item of manifest.files) {
  const data = fs.readFileSync(path.join(root, item.path));
  if (crypto.createHash('sha256').update(data).digest('hex') !== item.sha256) throw new Error(`Bad SHA: ${item.path}`);
  const tile = sandbox.codec.decode(new Uint8Array(data));
  // The extractor checks every feature's geometry cursor against the complete
  // shared geometry buffer, including discarded labels and lower-zoom features.
  const extracted = sandbox.extractTile(tile, {x:item.x, y:item.y, zoom:item.z}, 0, null, {}, false);
  summary.data3dBytes += tile.data3d?.length || 0;
  if (tile.data3d?.length) {
    fs.writeFileSync(path.join(root,'decoded',`${item.z}-${item.x}-${item.y}.data3d`), tile.data3d);
  }
  const features = [];
  for (const [name, layer] of extracted.layers) {
    for (const feature of layer) {
      const range = feature.getZoomRange();
      if (range && !(range.zMin <= 21 && 21 <= range.zMax)) continue;
      count(summary.layers, name);
      if (!retained.has(name)) continue;
      const attributes = feature.getAttributes() || {};
      count(summary.types, `${name}/${attributes.ft_type_name || attributes.type || '(untyped)'}`);
      if (name === 'building') {
        summary.buildingHeight[Number.isFinite(attributes.height) ? 'known' : 'missing']++;
      }
      if (feature.id && !Number.isSafeInteger(feature.id)) summary.unsafeIds++;
      const raw = feature._feature;
      const metadata = raw.metadata || {};
      for (const [key, value] of Object.entries(metadata)) {
        if (key.endsWith('.MODEL_METADATA')) {
          for (const mode of ['light', 'dark']) {
            const model = value[mode];
            if (model) for (const lod of model.lods || [{id:model.id}]) {
              if (lod.id) summary.richModels[lod.id] = {mode, layer:name};
            }
          }
        }
        if (key.endsWith('.MESH_METADATA') && value.meshId) meshIds.add(value.meshId);
      }
      // These are normalized ellipsoidal Mercator coordinates: multiply x/y
      // by PI*6378137 to obtain EPSG:3395 metres. They are not terrain heights.
      features.push({id:feature.id || null, layer:name, geometry:feature.getGeometry(),
        attributes, zoomRange:range, metadata});
    }
  }
  const output = {sourceTile:{x:item.x,y:item.y,z:item.z}, displayZoom:21,
    coordinateSystem:'normalized EPSG:3395, world extent [-1,1]', features};
  fs.writeFileSync(path.join(root,'decoded',`${item.z}-${item.x}-${item.y}.json.gz`),
    zlib.gzipSync(JSON.stringify(output)));
}
summary.meshIds = [...meshIds].sort();
fs.writeFileSync(path.join(root,'audit.json'), JSON.stringify(summary,null,2)+'\n');
console.log(JSON.stringify({...summary, richModels:Object.keys(summary.richModels).length,
  meshIds:summary.meshIds.length},null,2));
