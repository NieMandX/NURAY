Source: https://github.com/Noniv/web-ocean
Commit: a07c7fd522ef0a897601c114f927a49d93d95520
Copyright (c) 2026 Maksymilian Dendura. MIT; see LICENSE.

Only WGSL shader modules are vendored. The original application's camera,
telemetry, input handlers and capture/upload code are not included.
City integration is in ../gpu-ocean.js and ../city-shader.js.
The ocean CDLOD mesh is not used: shading follows existing city water footprints
and elevations. FFT displacement is sampled for shading, not applied to coarse
city vertices. Heliodon supplies the solar direction. Shore foam uses our global
coastline index. Simulation/atmosphere are cached while paused.

The city lighting selector defaults to the previous NURAY sun, environment and
ACES/sRGB output. Ocean atmosphere/AgX remain optional. Wave simulation and water
controls are shared; classic mode skips atmosphere updates, sky and bloom passes.
