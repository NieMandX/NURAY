# NURAY

WebGPU viewer for Moscow City, 5 × 5 km. PBR rasterization, a progressive path tracer with instanced mesh BVHs, and a separate experimental radiance-cascade mode.

Choose **Каскады · эксперимент** in the renderer selector. Switching between the two ray modes reuses the loaded scene and GPU geometry. The reference path tracer remains the default.

The mesh cascade mode uses four spatial/angular levels (16×8×16 probes / 16 directions at the finest level), bounded ray intervals, six directional irradiance lobes, and a 16-update warm-up. Its roughly 1.1 MiB cache survives camera orbit, exposure and image-resolution changes. Changing the region, geometry, textures, materials or lighting rebuilds it. Cached queries use a bounded visibility ray; unsupported points fall back to path tracing. Direct sky/sun, metal reflections and glass paths still use actual rays. Both ray modes use adaptive batches of up to eight samples within the GPU time budget.

This is a biased approximation of the first diffuse bounce, not a converged full-light-transport solution: coarse probes may miss small features and leak light during interval interpolation. The speedup depends on the view, geometry and fallback rate; warm-up has an additional cost. Optional temporal reprojection and edge-aware denoising are enabled by default in both ray modes; turn off **Стабилизация и шумоподавление** to inspect the original progressive estimator. The UI reports GPU time per sample separately from cache-update time; footer GPU time includes all passes in the submitted frame.

- Viewer: https://niemandx.github.io/NURAY/
- Code: https://github.com/NieMandX/NURAY
- Scene: https://storage.yandexcloud.net/nuray-assets-niemandx/moscow-city-5km-v1/scene.json

## Acceleration structures

Ray modes default to a 16-bin surface-area-heuristic (SAH) builder for both mesh BVHs and the top-level instance hierarchy. It retains the existing 32-byte stackless binary node format, a maximum of eight triangles per mesh leaf, the full geometry and material data, and the same ray/intersection shaders. The **Поиск пересечений** selector keeps the original midpoint builder available for comparison. Changing it rebuilds the scene acceleration structures while retaining the camera.

SAH trades longer preparation for faster traversal. On the tested device, preparing the complete city BVH took about 18.5 seconds versus 4.8–6.1 seconds for midpoint; the UI reports this CPU work separately from total loading. The serialized GPU BVH data decreased from 83.8 to 79.8 MiB. Actual timings depend on the device and view. Different triangle orders can select a different material when source surfaces overlap at exactly the same depth; no triangles are removed or approximated.

Measured on the full Moscow scene in the WebGPU browser, at 537 × 334 pixels and eight bounces, with cascades and reconstruction disabled:

| Camera | Midpoint GPU/sample | SAH GPU/sample | GPU time reduction |
| --- | ---: | ---: | ---: |
| Overview | 37.72 ms | 29.92 ms | 20.7% |
| City towers | 77.40 ms | 59.87 ms | 22.7% |
| Embankment | 68.16 ms | 56.39 ms | 17.3% |

The comparison used midpoint/SAH/SAH/midpoint build order, eight warm-up samples and 32 timed samples per view and build; each table entry is the mean of two run medians. GPU timestamps measured the unmodified path shader. Separate diagnostic runs found 13.8–16.7% fewer node tests and 9.8–13.8% fewer triangle tests per complete path. Primary hit/miss masks and depths matched at every pixel; only 0–2 of 179,358 pixels per view selected a different albedo at coincident source surfaces. These are traversal measurements, not end-to-end frame-rate guarantees.

## Image reconstruction

Reconstruction carries unfiltered, scene-linear radiance between nearby camera poses using deterministic primary-hit guides. A bilinear gather rejects incompatible depth/plane, normal, material and albedo samples. Reprojected diffuse history is neighbourhood-clamped and capped at 16 prior samples. Camera cuts, scene/material/light changes, resizing, restarts and cascade warm-up invalidate history. Exposure changes preserve scene-linear history. Static frames accumulate fresh samples only; the original raw Monte Carlo buffer remains separate.

A three-pass edge-aware à-trous filter uses surface planes, normals and albedo to preserve silhouettes and facade detail. Filtering fades out as the history reaches 128 samples. Glass and sharp/metallic reflections bypass the spatial filter and reject temporal reuse during camera movement because primary-surface guides cannot track reflected/refracted objects. Expect remaining noise on those paths and on newly revealed surfaces. This is a conservative first reconstruction stage, not ReSTIR, full SVGF, or a guarantee of artifact-free output.

The reconstruction buffers use 160 bytes per pixel (about 27.5 MiB at 180k pixels), in addition to 32 bytes per pixel for raw/fresh path samples. Buffers are released when reconstruction is disabled; native resolution is bounded by the largest storage buffer. UI timings separate reconstruction, primary-surface updates on camera changes, path samples and lighting-cache work; footer GPU time includes every pass. The benefit is time to usable image quality, not cheaper individual ray traversal.

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
