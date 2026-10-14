"""SCENE3D HTML template.

Builds a self-contained Three.js (r169, vendored) scene from a ``SceneSpec``
injected as ``window.__SCENE3D_SPEC``. The page exposes a deterministic,
real-time-free API:

    window.__ready()            -> bool, true once first frame rendered
    window.__setTime(t)         -> advance the simulation to absolute time t (s)
    window.__render()           -> draw one frame at the current time
    window.__framePixels()      -> data:image/png;base64 of the current frame

The renderer uses an ``EffectComposer`` with ``UnrealBloomPass``. Time is driven
explicitly by ``__setTime`` so byte-identical determinism is achievable:
nothing in the per-frame update depends on wall-clock or ``requestAnimationFrame``.

All geometry is generated procedurally in-browser: toon/Lambert planets,
InstancedMesh wind-shaken wheat & grass, a Points starfield, a gradient sky
sphere + exponential fog, and a low-poly fox built from primitives. No external
textures or network assets are required.
"""

from __future__ import annotations

import json

from .schema import SceneSpec, scene_to_dict


def build_html(spec: SceneSpec) -> str:
    """Return the full page HTML for a scene spec."""
    spec_json = __import__("json").dumps(scene_to_dict(spec), ensure_ascii=False)
    # NOTE: do NOT html.escape the JSON — it is injected into a <script> block
    # as a JS object literal, so quotes must remain literal.
    return _PAGE.replace("/*__SCENE3D_SPEC__*/", f"window.__SCENE3D_SPEC = {spec_json};")


# Three.js is loaded as an ES module via an import map pointing at the vendored
# copy (MIT, github.com/mrdoob/three.js). The import map lets the jsm postprocessing
# passes resolve their bare ``three`` import offline.
_PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>SCENE3D</title>
<style>
  html,body{margin:0;padding:0;background:#000;overflow:hidden;}
  #c{display:block;width:100vw;height:100vh;}
</style>
<script type="importmap">
{
  "imports": {
    "three": "./vendor/three/three.module.js"
  }
}
</script>
</head>
<body>
<canvas id="c"></canvas>
<script type="module">
import * as THREE from 'three';
import { EffectComposer } from './vendor/three/postprocessing/EffectComposer.js';
import { RenderPass } from './vendor/three/postprocessing/RenderPass.js';
import { UnrealBloomPass } from './vendor/three/postprocessing/UnrealBloomPass.js';
import { OutputPass } from './vendor/three/postprocessing/OutputPass.js';

/*__SCENE3D_SPEC__*/

const SPEC = window.__SCENE3D_SPEC;
const CAM = SPEC.camera, LIG = SPEC.lights, WEA = SPEC.weather, AST = SPEC.assets;
// Derive pixel dimensions from resolution + aspect (the JSON stores `resolution`,
// not width/height, so we compute them here to keep the on-disk spec compact).
const _RES = SPEC.resolution || 1080;
const _ASP = (CAM.aspect === '9:16') ? 9/16 : (CAM.aspect === '1:1') ? 1 : (CAM.aspect === '21:9') ? 21/9 : 16/9;
const W = Math.round(_RES * (_ASP > 1 ? _ASP : 1));
const H = Math.round(_RES * (_ASP > 1 ? 1 : 1/_ASP));
const FPS = SPEC.fps;
const ASPECT = W / H;

// Seeded PRNG (mulberry32) -> deterministic geometry placement.
function mulberry32(a){
  return function(){
    a |= 0; a = a + 0x6D2B79F5 | 0;
    let t = Math.imul(a ^ a >>> 15, 1 | a);
    t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t;
    return ((t ^ t >>> 14) >>> 0) / 4294967296;
  };
}
const rnd = mulberry32(SPEC.seed >>> 0);
function rrange(min,max){ return min + (max-min)*rnd(); }

const canvas = document.getElementById('c');
canvas.width = W; canvas.height = H;
const renderer = new THREE.WebGLRenderer({ canvas, antialias:false, preserveDrawingBuffer:true });
renderer.setPixelRatio(1);
renderer.setSize(W, H, false);
renderer.shadowMap.enabled = !!WEA.shadows;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 1.05;
renderer.outputColorSpace = THREE.SRGBColorSpace;

const scene = new THREE.Scene();
const fogColor = new THREE.Color(WEA.fog_color[0], WEA.fog_color[1], WEA.fog_color[2]);
scene.fog = new THREE.FogExp2(fogColor.getHex(), WEA.fog_density);

const camera = new THREE.PerspectiveCamera(CAM.fov, ASPECT, CAM.near, CAM.far);
camera.position.set(CAM.pos[0], CAM.pos[1], CAM.pos[2]);
camera.lookAt(CAM.look[0], CAM.look[1], CAM.look[2]);

// ---- Gradient sky dome -------------------------------------------------
{
  const top = new THREE.Color(WEA.background_top[0], WEA.background_top[1], WEA.background_top[2]);
  const bot = new THREE.Color(WEA.background_bottom[0], WEA.background_bottom[1], WEA.background_bottom[2]);
  const geo = new THREE.SphereGeometry(CAM.far * 0.9, 32, 16);
  const mat = new THREE.ShaderMaterial({
    side: THREE.BackSide, depthWrite:false, fog:false,
    uniforms:{ top:{value:top}, bottom:{value:bot}, offset:{value:33}, exponent:{value:0.8} },
    vertexShader:`varying vec3 vP; void main(){ vP=position; gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.0);} `,
    fragmentShader:`varying vec3 vP; uniform vec3 top; uniform vec3 bottom; uniform float offset; uniform float exponent;
      void main(){ float h=normalize(vP+vec3(0.0,offset,0.0)).y; float t=max(pow(max(h,0.0),exponent),0.0);
        gl_FragColor=vec4(mix(bottom,top,t),1.0);} `
  });
  const sky = new THREE.Mesh(geo, mat);
  sky.frustumCulled = false;
  scene.add(sky);
}

// ---- Lights ------------------------------------------------------------
const sun = new THREE.DirectionalLight(new THREE.Color(LIG.sun_color[0],LIG.sun_color[1],LIG.sun_color[2]), LIG.sun_intensity);
sun.position.set(LIG.sun_pos[0], LIG.sun_pos[1], LIG.sun_pos[2]);
if (WEA.shadows){
  sun.castShadow = true;
  sun.shadow.mapSize.set(1024,1024);
  const d = 40;
  sun.shadow.camera.left=-d; sun.shadow.camera.right=d; sun.shadow.camera.top=d; sun.shadow.camera.bottom=-d;
  sun.shadow.camera.near=1; sun.shadow.camera.far=200;
  sun.shadow.bias = -0.0008;
}
scene.add(sun);
scene.add(new THREE.HemisphereLight(
  new THREE.Color(LIG.ambient_color[0],LIG.ambient_color[1],LIG.ambient_color[2]),
  new THREE.Color(WEA.fog_color[0],WEA.fog_color[1],WEA.fog_color[2]), LIG.ambient_intensity));
const rim = new THREE.DirectionalLight(new THREE.Color(LIG.rim_color[0],LIG.rim_color[1],LIG.rim_color[2]), LIG.rim_intensity);
rim.position.set(-LIG.sun_pos[0], LIG.sun_pos[1]*0.5, -LIG.sun_pos[2]);
scene.add(rim);

// ---- Starfield ---------------------------------------------------------
let starField = null;
if (WEA.starfield){
  const N = WEA.star_count;
  const pos = new Float32Array(N*3);
  const pha = new Float32Array(N);
  const rad = Math.min(CAM.far*0.8, 900);
  for (let i=0;i<N;i++){
    // distribute on a large shell
    const u = rnd()*2-1, th = rnd()*Math.PI*2, r = rad*(0.7+0.3*rnd());
    const s = Math.sqrt(1-u*u);
    pos[i*3]=Math.cos(th)*s*r; pos[i*3+1]=u*r; pos[i*3+2]=Math.sin(th)*s*r;
    pha[i]=rnd()*6.283;
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.BufferAttribute(pos,3));
  const m = new THREE.ShaderMaterial({
    transparent:true, depthWrite:false, fog:false,
    uniforms:{ t:{value:0}, phase:{value:pha} },
    vertexShader:`attribute float aPha; varying float vPha; uniform float t;
      void main(){ vPha=aPha; vec4 mv=modelViewMatrix*vec4(position,1.0);
        gl_PointSize = 2.0; gl_Position=projectionMatrix*mv; }`,
    fragmentShader:`varying float vPha; uniform float t;
      void main(){ float tw=0.6+0.4*sin(t*2.0 + vPha*6.283);
        vec2 d=gl_PointCoord-vec2(0.5); if(dot(d,d)>0.25) discard;
        gl_FragColor=vec4(vec3(1.0,0.95,0.85)*tw, tw); }`
  });
  m.uniforms.phase.value = pha;
  g.setAttribute('aPha', new THREE.BufferAttribute(pha,1));
  starField = new THREE.Points(g, m);
  starField.frustumCulled = false;
  scene.add(starField);
}

// ---- Toon helpers ------------------------------------------------------
function toonMat(color, opts){
  opts = opts || {};
  return new THREE.MeshToonMaterial({ color:new THREE.Color(color[0],color[1],color[2]) });
}

// ---- Planet ------------------------------------------------------------
function makePlanet(params){
  const pr = params.radius ?? 2.0;
  const col = params.color ?? [0.9,0.6,0.4];
  const g = new THREE.Group();
  const geo = new THREE.IcosahedronGeometry(pr, 4);
  // gentle vertex displacement for a hand-painted planet look (deterministic)
  const p = geo.attributes.position;
  const v = new THREE.Vector3();
  for (let i=0;i<p.count;i++){
    v.fromBufferAttribute(p,i);
    const n = 0.06*Math.sin(v.x*3.1+1.0)*Math.sin(v.y*2.7)*Math.cos(v.z*2.3);
    v.multiplyScalar(1.0 + n);
    p.setXYZ(i, v.x, v.y, v.z);
  }
  geo.computeVertexNormals();
  const mat = toonMat(col);
  const mesh = new THREE.Mesh(geo, mat);
  mesh.castShadow = true; mesh.receiveShadow = true;
  g.add(mesh);
  // a little ring
  if (params.ring !== false){
    const ring = new THREE.Mesh(
      new THREE.RingGeometry(pr*1.4, pr*1.9, 48),
      new THREE.MeshBasicMaterial({color:new THREE.Color(col[0],col[1],col[2]).multiplyScalar(1.1),
        side:THREE.DoubleSide, transparent:true, opacity:0.35}));
    ring.rotation.x = Math.PI*0.5;
    ring.rotation.z = 0.3;
    g.add(ring);
  }
  g.position.set(params.pos?params.pos[0]:0, params.pos?params.pos[1]:0, params.pos?params.pos[2]:0);
  g.userData.spin = params.spin ?? 0.25;
  return g;
}

// ---- Instanced grass / wheat -------------------------------------------
function makeField(params){
  const kind = params.kind || 'grass';
  const count = params.count ?? 1200;
  const area = params.area ?? 30;
  const baseColor = params.color ?? (kind==='wheat'?[0.83,0.66,0.28]:[0.30,0.55,0.22]);
  const height = params.height ?? (kind==='wheat'?1.4:0.7);
  // blade geometry: a thin tapered quad strip
  const blade = new THREE.PlaneGeometry(0.12, height, 1, 4);
  blade.translate(0, height/2, 0);
  const mat = new THREE.MeshToonMaterial({ color:new THREE.Color(baseColor[0],baseColor[1],baseColor[2]), side:THREE.DoubleSide });
  const mesh = new THREE.InstancedMesh(blade, mat, count);
  mesh.castShadow = true; mesh.receiveShadow = true;
  const dummy = new THREE.Object3D();
  const phases = new Float32Array(count);
  const speeds = new Float32Array(count);
  const h0 = new Float32Array(count);
  for (let i=0;i<count;i++){
    const x = rrange(-area/2, area/2);
    const z = rrange(-area/2, area/2);
    const s = rrange(0.7,1.3);
    dummy.position.set(x, 0, z);
    dummy.rotation.set(0, rrange(0,6.28), 0);
    dummy.scale.set(rrange(0.8,1.2), s, rrange(0.8,1.2));
    dummy.updateMatrix();
    mesh.setMatrixAt(i, dummy.matrix);
    phases[i] = rrange(0,6.28);
    speeds[i] = rrange(0.6,1.4);
    h0[i] = height*s;
  }
  mesh.instanceMatrix.needsUpdate = true;
  mesh.userData = { phases, speeds, height, area, kind };
  return mesh;
}

// ---- Ground ------------------------------------------------------------
function makeGround(params){
  const col = params.color ?? [0.18,0.22,0.12];
  const r = params.radius ?? 60;
  const geo = new THREE.CircleGeometry(r, 64);
  geo.rotateX(-Math.PI/2);
  const mat = new THREE.MeshToonMaterial({ color:new THREE.Color(col[0],col[1],col[2]) });
  const m = new THREE.Mesh(geo, mat);
  m.receiveShadow = true;
  return m;
}

// ---- Rock (low-poly) ---------------------------------------------------
function makeRock(params){
  const s = params.scale ?? 1.0;
  const col = params.color ?? [0.5,0.5,0.55];
  const geo = new THREE.DodecahedronGeometry(0.6, 0);
  const p = geo.attributes.position; const v=new THREE.Vector3();
  for (let i=0;i<p.count;i++){ v.fromBufferAttribute(p,i); v.multiplyScalar(1+0.18*rnd()); p.setXYZ(i,v.x,v.y,v.z);}
  geo.computeVertexNormals();
  const m = new THREE.Mesh(geo, toonMat(col));
  m.castShadow=true; m.receiveShadow=true;
  m.scale.setScalar(s);
  m.position.set(params.pos?params.pos[0]:0,params.pos?params.pos[1]:s*0.3,params.pos?params.pos[2]:0);
  return m;
}

// ---- Tree (stylized cone + trunk) --------------------------------------
function makeTree(params){
  const s = params.scale ?? 1.0;
  const g = new THREE.Group();
  const trunk = new THREE.Mesh(new THREE.CylinderGeometry(0.12,0.18,1.0,6), toonMat([0.42,0.28,0.18]));
  trunk.position.y = 0.5; trunk.castShadow=true; trunk.receiveShadow=true;
  g.add(trunk);
  const leaf = new THREE.Mesh(new THREE.ConeGeometry(0.9,1.8,8), toonMat(params.color ?? [0.26,0.5,0.26]));
  leaf.position.y = 1.7; leaf.castShadow=true; leaf.receiveShadow=true;
  g.add(leaf);
  g.scale.setScalar(s);
  g.position.set(params.pos?params.pos[0]:0,0,params.pos?params.pos[2]:0);
  return g;
}

// ---- Fox (low-poly built from primitives) ------------------------------
function makeFox(params){
  const s = params.scale ?? 1.0;
  const col = params.color ?? [0.95,0.55,0.22];
  const g = new THREE.Group();
  const body = new THREE.Mesh(new THREE.CapsuleGeometry(0.32,0.7,4,8), toonMat(col));
  body.rotation.z = Math.PI/2; body.position.set(0,0.5,0); body.castShadow=true;
  g.add(body);
  const head = new THREE.Mesh(new THREE.SphereGeometry(0.32,12,10), toonMat(col));
  head.position.set(0.62,0.66,0); head.castShadow=true; g.add(head);
  // ears
  for (const z of [-0.16,0.16]){
    const ear = new THREE.Mesh(new THREE.ConeGeometry(0.1,0.26,6), toonMat(col));
    ear.position.set(0.6,0.95,z); g.add(ear);
  }
  // snout
  const snout = new THREE.Mesh(new THREE.ConeGeometry(0.14,0.34,8), toonMat([0.98,0.85,0.7]));
  snout.rotation.z = -Math.PI/2; snout.position.set(0.92,0.6,0); g.add(snout);
  // tail (big bushy)
  const tail = new THREE.Mesh(new THREE.ConeGeometry(0.22,0.7,8), toonMat(col));
  tail.position.set(-0.6,0.6,0); tail.rotation.z = Math.PI/2.6; g.add(tail);
  const tailTip = new THREE.Mesh(new THREE.SphereGeometry(0.14,8,8), toonMat([0.98,0.98,0.98]));
  tailTip.position.set(-0.9,0.78,0); g.add(tailTip);
  // legs
  for (const x of [0.35,-0.35]) for (const z of [-0.18,0.18]){
    const leg = new THREE.Mesh(new THREE.CylinderGeometry(0.07,0.07,0.4,6), toonMat([0.3,0.18,0.1]));
    leg.position.set(x,0.2,z); leg.castShadow=true; g.add(leg);
  }
  g.scale.setScalar(s);
  g.position.set(params.pos?params.pos[0]:0, params.pos?params.pos[1]:0, params.pos?params.pos[2]:0);
  g.rotation.y = params.rotY ?? 0.4;
  g.userData.sit = params.sit ?? false;
  return g;
}

// ---- Build assets ------------------------------------------------------
const dynamic = []; // objects that need per-frame updates
const fields = [];  // instanced fields for wind
for (const a of AST){
  const p = a.params || {};
  if (a.kind === 'planet'){ const o = makePlanet(p); scene.add(o); dynamic.push({obj:o, type:'planet'}); }
  else if (a.kind === 'wheat'){ const o = makeField(Object.assign({kind:'wheat'},p)); scene.add(o); fields.push(o); }
  else if (a.kind === 'grass'){ const o = makeField(Object.assign({kind:'grass'},p)); scene.add(o); fields.push(o); }
  else if (a.kind === 'ground'){ scene.add(makeGround(p)); }
  else if (a.kind === 'rock'){ scene.add(makeRock(p)); }
  else if (a.kind === 'tree'){ scene.add(makeTree(p)); }
  else if (a.kind === 'fox'){ const o = makeFox(p); scene.add(o); dynamic.push({obj:o, type:'fox'}); }
  else { console.warn('unknown asset kind', a.kind); }
}

// ---- Composer (bloom) --------------------------------------------------
const composer = new EffectComposer(renderer);
composer.setSize(W, H);
composer.addPass(new RenderPass(scene, camera));
const bloom = new UnrealBloomPass(new THREE.Vector2(W,H), WEA.bloom_strength, WEA.bloom_radius, WEA.bloom_threshold);
composer.addPass(bloom);
composer.addPass(new OutputPass());

// ---- Camera path interpolation -----------------------------------------
function sampleCam(t){
  const path = CAM.path || [];
  if (!path.length){ return; }
  const dur = SPEC.duration_s;
  // find segment
  let i0=0, i1=0;
  for (let i=0;i<path.length;i++){
    if (path[i].t <= t+1e-6){ i0=i; }
  }
  i1 = Math.min(i0+1, path.length-1);
  const a = path[i0], b = path[i1];
  let u = 0;
  if (b.t > a.t){ u = Math.min(1, Math.max(0,(t-a.t)/(b.t-a.t))); }
  const pos = [a.pos[0]+(b.pos[0]-a.pos[0])*u, a.pos[1]+(b.pos[1]-a.pos[1])*u, a.pos[2]+(b.pos[2]-a.pos[2])*u];
  const look= [a.look[0]+(b.look[0]-a.look[0])*u, a.look[1]+(b.look[1]-a.look[1])*u, a.look[2]+(b.look[2]-a.look[2])*u];
  camera.position.set(pos[0],pos[1],pos[2]);
  camera.lookAt(look[0],look[1],look[2]);
}

// ---- Wind on fields ----------------------------------------------------
function updateFields(t){
  const wind = WEA.wind_strength, ws = WEA.wind_speed;
  const dummy = new THREE.Object3D();
  for (const f of fields){
    const ud = f.userData;
    // We stored only phase/speed; recompute base transform deterministically
    // from a seeded layout (same seed order as the build loop). Store once.
    if (!ud.base){ buildBase(f); }
    const base = ud.base;
    for (let i=0;i<f.count;i++){
      const ph = ud.phases[i], sp = ud.speeds[i];
      const ang = Math.sin(t*ws*sp + ph) * 0.35 * wind;
      const sway = Math.sin(t*ws*sp + ph) * 0.12 * wind;
      dummy.position.set(base.pos[i*3], base.pos[i*3+1], base.pos[i*3+2]);
      dummy.rotation.set(sway, base.rot[i], 0);
      dummy.scale.set(base.scl[i*3], base.scl[i*3+1], base.scl[i*3+2]);
      // bend forward around base
      dummy.updateMatrix();
      // apply a shear-like bend by rotating the top: approximate with rotation about base
      const mtx = dummy.matrix.clone();
      const bend = new THREE.Matrix4().makeRotationZ(ang);
      mtx.multiply(bend);
      f.setMatrixAt(i, mtx);
    }
    f.instanceMatrix.needsUpdate = true;
  }
}
function buildBase(f){
  const ud = f.userData;
  const area = ud.area, count = f.count;
  const pos = new Float32Array(count*3), rot = new Float32Array(count), scl = new Float32Array(count*3);
  for (let i=0;i<count;i++){
    pos[i*3]=rrange(-area/2, area/2); pos[i*3+1]=0; pos[i*3+2]=rrange(-area/2, area/2);
    rot[i]=rrange(0,6.28);
    scl[i*3]=rrange(0.8,1.2); scl[i*3+1]=rrange(0.7,1.3); scl[i*3+2]=rrange(0.8,1.2);
  }
  ud.base = { pos, rot, scl };
}

// ---- Time stepping -----------------------------------------------------
let curT = 0;
function setTime(t){
  curT = t;
  sampleCam(t);
  for (const d of dynamic){
    if (d.type === 'planet'){ d.obj.rotation.y = curT * d.obj.userData.spin; }
    else if (d.type === 'fox'){
      // gentle breathing / tail sway
      d.obj.rotation.z = Math.sin(curT*1.5)*0.03;
    }
  }
  if (starField){ starField.material.uniforms.t.value = t; }
  updateFields(t);
  render();
}
function render(){
  composer.render();
}

// ---- Determinism / capture API -----------------------------------------
let _ready = false;
function ensureReady(){ if(!_ready){ render(); _ready = true; } }

window.__ready = function(){ return _ready; };
window.__setTime = function(t){ ensureReady(); setTime(t); return true; };
window.__render = function(){ ensureReady(); render(); return true; };
window.__framePixels = function(){
  if (typeof window.__SETTIME_TEST__ === 'undefined'){ /* noop */ }
  return canvas.toDataURL('image/png');
};
window.__composer = composer;
window.__scene = scene;

// Render one frame immediately so __ready() can return true.
render();
_ready = true;
window.__SCENE3D_DONE = true;
</script>
</body>
</html>
"""
