# NURAY project context

Read `docs/knowledge/README.md`, `HANDOFF.md`, and `DECISIONS.md` before making scene changes.

- Current source of truth: `moscow-fidelity/`. Root `src/` is a legacy prototype.
- Preserve the user's live water/light settings before reloading the viewer.
- Moscow and Saint Petersburg defaults are independent. Moscow starts in WebGPU raster mode, Ocean water and Hosek–Wilkie sky. Do not restore retired lighting modes.
- Geometry fixes belong in algorithms, not object-ID patches. Preserve source identity, levels, terrain, instancing, and already-approved models/materials.
- Heavy files belong in versioned Cloud.ru releases, not Git. Do not overwrite public immutable releases or widen bucket access to private backups.
- Viewing assets does not require rebuilding the city. Change only affected layers; regenerate matching derived artifacts when geometry changes.
- Do not claim survey accuracy, a successful deployment, or a complete archive without verification.
- Run checks appropriate to the change. Keep LICENSE and PROVENANCE files.
