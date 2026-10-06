# NURAY

WebGPU viewer for Moscow City, 5 × 5 km. PBR rasterization, a progressive path tracer with instanced mesh BVHs, and a separate experimental radiance-cascade mode.

Choose **Каскады · эксперимент** in the renderer selector. Switching between the two ray modes reuses the loaded scene and GPU geometry. The reference path tracer remains the default.

The mesh cascade mode uses four spatial/angular levels (16×8×16 probes / 16 directions at the finest level), bounded ray intervals, six directional irradiance lobes, and a 16-update warm-up. Its roughly 1.1 MiB cache survives camera orbit, exposure and image-resolution changes. Changing the region, geometry, textures, materials or lighting rebuilds it. Cached queries use a bounded visibility ray; unsupported points fall back to path tracing. Direct sky/sun, metal reflections and glass paths still use actual rays. Both ray modes use adaptive batches of up to eight samples within the GPU time budget.

This is a biased approximation of the first diffuse bounce, not a converged full-light-transport solution: coarse probes may miss small features and leak light during interval interpolation. The speedup depends on the view, geometry and fallback rate; warm-up has an additional cost. No denoiser or temporal image reprojection is implemented. The UI reports GPU time per sample separately from cache-update time; footer GPU time includes all passes in the submitted frame.

- Viewer: https://niemandx.github.io/NURAY/
- Code: https://github.com/NieMandX/NURAY
- Scene: https://storage.yandexcloud.net/nuray-assets-niemandx/moscow-city-5km-v1/scene.json

## Architecture

GitHub Pages serves HTML, JavaScript, CSS and WGSL only. The browser loads the scene manifest, gzip geometry chunks and texture atlases directly from Yandex Cloud Object Storage over HTTPS. `model-config.js` sets the versioned model base URL for the main thread, material loader and worker. No keys, tokens, backend, build dependencies or model files are stored in this repository.

## Local preview

Run `python3 -m http.server 8765 --bind 127.0.0.1` and open http://127.0.0.1:8765/.
Use a browser/device supporting WebGPU. The model still loads from Yandex Cloud. The bucket CORS allows GET/HEAD from `https://niemandx.github.io`, `http://127.0.0.1:8765` and `http://localhost:8765`.

## Deployment

Pages source: **GitHub Actions**. Push to `main` to run **Deploy NURAY**, or run the workflow manually.
The workflow publishes only the viewer files. `.gitignore` excludes model assets, Blender files and local environment files.

## Updating the scene

1. Upload every chunk, texture and `scene.json` to a **new versioned prefix** in the existing `nuray-assets-niemandx` bucket.
2. Verify all referenced objects are readable, and preserve CORS GET/HEAD for the viewer origin.
3. Change `modelBaseUrl` in `model-config.js` to that prefix and push the code.
4. Keep the previous prefix available for older open tabs until the new deployment has been checked.

Geometry `.bin.gz` objects should have `Content-Type: application/gzip` or `application/octet-stream` and **no Content-Encoding: gzip**: the worker decompresses the file itself. Do not upload cloud credentials. Object contents are publicly readable; bucket listing and settings remain authenticated.

## Model

- Initial model download: 166.54 MB (geometry 144.79 MB, textures 9.91 MB, manifest 11.84 MB).
- 6,676,167 unique triangles, 28,410,874 including instances.
- 169 materials; 58,906 street-object placements.
- Geometry/BVH/materials occupy about 857 MiB on the GPU; frame buffers, staging and browser overhead are additional.
- Native resolution follows the canvas size × device pixel ratio, bounded by GPU texture/buffer limits. It converges more slowly than the default 180k pixel preset.

Original 2GIS geometry was exported through Blender without decimation. Atlas colors can include baked lighting; assigned PBR parameters are approximations. Towers use coated opaque facades because the source contains no separate interior glazing volumes. Static meshes are clipped to a 5 km square; tree origins are inside the square but crowns may cross the edge.
