# Seascape adaptation

Original: “Seascape” by Alexander Alekseev (TDM), 2014.
https://www.shadertoy.com/view/Ms2SD1
Author's source: https://github.com/tdmaav/shadertoy/blob/master/Seascape.shader
Source SHA-256: 54ef0258a8ee8ab8777d0d5bf5dfc77db04d382a1ea2ba4427046d78b97def46
Retrieved 2026-10-24. An unchanged source copy is included for attribution/reference.

License: Creative Commons Attribution-NonCommercial-ShareAlike 3.0 Unported.
https://creativecommons.org/licenses/by-nc-sa/3.0/
The adaptations in this directory retain that license. They are an experimental,
non-commercial option, not covered by the MIT license of Noniv/web-ocean.

Changes: GLSL/WGSL ports of octave waves, sky gradient and water shading; finite
city water footprints; pixel footprint filtering; controllable amplitude,
frequency, choppiness, speed and direction; existing shore foam and sun shadows.
The water/illumination selectors are independent. The original fixed sun is
replaced by the geographic heliodon. Seascape's sky/grade also illuminate city PBR
materials. The original flying camera and infinite-ocean raymarcher are not used.
Waves change shading normals and crest color, not the city mesh elevations.

The optional NURAY + Seascape mode mixes direct illumination, ambient light,
reflections and output grading without drawing the city twice. Its 0% and 100%
endpoints match the standalone modes at identical settings. Solar intensity is
independent of the blend and exposure; shadow strength affects the sun shadow
mask and shadowed fill, not contact AO. Controls work in both WebGPU and WebGL,
including when water animation is frozen. The heliodon still sets sun direction.
