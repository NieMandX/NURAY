# Moscow appearance transfer · 2026-10-24

Source: `assets-5km-live-20261019-r6` (5 × 5 km, 400 tiles).
Appearance reference: `assets-spb-10km-live-20261024-r13`.
Result: `assets-moscow-style-20261024-r14`, including `merged/model.glb` and `merged/trace/manifest.json`.

The original Moscow and Saint Petersburg assets are preserved. Intermediate assets use copy-on-write clones. Terrain is not regenerated. The optional per-stage canonical GLB exports are deferred until the final merged export.

## Build stages

The original recorded pipeline ran cemetery, pedestrian material, flat roof, pitched roof, facade, parking and waterfront processors in `prototype/tiling`. The finalization stage added the Moscow stone parapet, checks material equality with Saint Petersburg, builds the surface-effects lookup and exports the merged GLB with its ray acceleration cache. Logs are numbered in execution order. These recorded scripts contain local runtime paths; set `NODE`, `PYTHON` and `PYTHONPATH` for another machine.

The complete 5,134-building inventory is retained when applying partial roof/facade updates. Do not substitute a patch's updated-building list for the full source inventory.

Water connectivity is resolved before surface ownership cuts and tile clipping. All source water polygons open at the acquisition boundary are included, along with explicitly connected water channels. This handles the Moscow River leaving and re-entering the scene. Interior closed water remains unchanged. Bridge polygons provide evidence for water continuation; proximity alone does not connect ponds.

Selected water is lowered by 2 m. Existing ground determines the bank lip. Granite and the cornice use the approved Saint Petersburg texture and continuous shoreline UVs. The Moscow parapet is 1 m high, 0.4 m thick, with 2 m slabs and recessed vertical joints. Its top uses a dry stone region of the same bitmap. Acquisition boundaries do not generate cross-water walls.

## Evidence

- `appearance-audit.json`: exact comparison of 11 material families, preserved unrelated source chunks, unchanged terrain.
- Result catalog `water-selection-proof.json`: selected river and preserved inland water areas; no unselected water touches the scene boundary.
- Result catalog `waterfront-proof.json`: bridge coverage, lowering, tile conservation, BVH and shoreline UV checks.
- Result catalog `waterfront-parapet-proof.json`: original bank attributes retained exactly, unrelated geometry retained, tile conservation and UV checks.
- Result catalog `merged/validation.json`: retained vertex attributes, shared instances, geometry counts and GLB size.
- `completed.json`: final catalog and merged export.

Regression suite: `python -m unittest discover -s prototype/tiling -p 'test_waterfront*.py' -v` (17 tests at this revision).

Viewer lighting choices are Classic NURAY and Hosek–Wilkie only; water is Ocean. The approved water/light preset is retained, with 64 samples by default. Moscow heliodon coordinates are derived from the existing scene projection and stored with the result catalog; this is not a survey calibration.

The original pipeline launch scripts remain in the local diagnostics; use current prepare_*.py CLI tools for new work. This directory records the verified output, not a portable one-command reproduction of every historical intermediate.
