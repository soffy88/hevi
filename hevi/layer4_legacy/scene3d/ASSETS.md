# Assets used by hevi/layer4_legacy/scene3d

All scene geometry, materials and lighting are **procedurally generated in
JavaScript at render time** in `hevi/layer4_legacy/scene3d/template.py`. The
templates describe the meshes directly in the `THREE.*` calls — there are no
loaded textures, glTF files or model binaries.

The only vendored asset is **Three.js r169** (postprocessing passes plus
shaders) under `vendor/three/`, kept offline so rendering does not require
network access.

## Procedural assets

| Kind | Source | Description |
|---|---|---|
| `planet` | clean-room (`template.py::makePlanet`) | icosahedron + per-vertex noise + optional ring |
| `wheat` | clean-room (`template.py::makeField`) | `THREE.InstancedMesh` of tall tapered plane quads |
| `grass` | clean-room (`template.py::makeField`) | `THREE.InstancedMesh` of short tapered plane quads |
| `fox` | clean-room (`template.py::makeFox`) | capsules + cones + spheres (no external geometry) |
| `starfield` | clean-room (`template.py`, inlined shader) | `THREE.Points` on a large sphere, twinkling |
| `ground` | clean-room (`template.py::makeGround`) | `THREE.CircleGeometry` + toon material |
| `rock` | clean-room (`template.py::makeRock`) | dodecahedron + per-vertex jitter |
| `tree` | clean-room (`template.py::makeTree`) | cylinder trunk + cone leaves |

Wind motion for `wheat` and `grass` is baked into the per-frame matrix update
in `template.py::updateFields`, deterministically driven by `window.__setTime`.

## Three.js (vendored)

- **Source**: https://github.com/mrdoob/three.js/tree/r169
- **License**: MIT (https://github.com/mrdoob/three.js/blob/dev/LICENSE)
- **Files kept** (transitive closure of `EffectComposer → RenderPass +
  UnrealBloomPass + OutputPass`):
  - `three.module.js`
  - `postprocessing/EffectComposer.js`
  - `postprocessing/RenderPass.js`
  - `postprocessing/UnrealBloomPass.js`
  - `postprocessing/OutputPass.js`
  - `postprocessing/MaskPass.js`
  - `postprocessing/Pass.js`
  - `postprocessing/ShaderPass.js`
  - `shaders/CopyShader.js`
  - `shaders/LuminosityHighPassShader.js`
  - `shaders/OutputShader.js`
- **How obtained**: `npm install three@0.169.0` then copied the
  `examples/jsm/postprocessing/*` and `examples/jsm/shaders/*` references
  used by our template.
- **Why vendored**: the SCENE3D line must render offline on CPU
  (SwiftShader); we cannot reach `unpkg.com` / `cdn.jsdelivr.net` from this
  host. Vendoring also keeps the renderer deterministic — no network jitter
  between runs.

No CC0 models are pulled at runtime. The Kenney "Nature Kit" (CC0) is the
back-up option reserved for future direct asset use, but is not currently
imported by the renderer.
