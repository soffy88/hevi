"""SCENE3D HTML template.

Builds a self-contained Three.js (r169, vendored) scene from a ``SceneSpec``
injected as ``window.__SCENE3D_SPEC``. The page exposes a deterministic,
real-time-free API:

    window.__ready()            -> bool, true once first frame rendered
    window.__setTime(t)         -> advance the simulation to absolute time t (s)
    window.__render()           -> draw one frame at the current time
    window.__framePixels()      -> data:image/png;base64 of the current frame
    window.__collisionReport()  -> bbox/sphere intersection report (no穿模)
    window.__instancePositions()-> placed field instance positions (for tests)

The renderer uses an ``EffectComposer`` with ``UnrealBloomPass``. Time is driven
explicitly by ``__setTime`` so byte-identical determinism is achievable:
nothing in the per-frame update depends on wall-clock or ``requestAnimationFrame``.

All geometry is generated procedurally in-browser: toon/Lambert planets,
InstancedMesh wind-shaken wheat & grass whose **wind lives in the vertex
shader** (root fixed, tip bends), a layered Points starfield, a gradient sky
sphere + exponential fog, and a low-poly fox with eyes/nose/blush. No external
textures or network assets are required.
"""

from __future__ import annotations

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
renderer.toneMappingExposure = SPEC.name === 'through_star_sea' ? 0.62 : 0.92;
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
  sun.shadow.mapSize.set(512,512);
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
// Layered, size-attenuated stars so they read at 1080p instead of being 2px
// specks.  A fraction are large soft "hero" stars; the rest are small and dim.
let starField = null;
let starPositions = null;
const starCorridor = SPEC.name === 'through_star_sea';
if (WEA.starfield){
  const N = Math.max(0, WEA.star_count|0);
  const pos = new Float32Array(N*3);
  starPositions = pos;
  const pha = new Float32Array(N);
  const siz = new Float32Array(N);
  const bri = new Float32Array(N);
  const rad = Math.min(CAM.far*0.8, (WEA.star_radius ?? 900));
  const sizeScale = WEA.star_size ?? 1.0;
  for (let i=0;i<N;i++){
    const hero = rnd() < (starCorridor ? 0.025 : 0.12);
    if (starCorridor){
      // A volume along the camera's forward route, not a distant spherical shell.
      // The star is placed at a random 2.5–7.5 world-unit lead in front of the
      // camera path; its x/y spread matches the real frustum at that lead.
      const lead = rrange(2.5, 7.5);
      const z = rrange(0.5, 47.0);
      const halfW = lead * Math.tan(THREE.MathUtils.degToRad(CAM.fov)/2) * ASPECT * 0.82;
      const halfH = lead * Math.tan(THREE.MathUtils.degToRad(CAM.fov)/2) * 0.82;
      const centerY = 0.8 + 1.2 * Math.max(0, Math.min(1, (48.0-z)/37.0));
      pos[i*3] = rrange(-halfW, halfW);
      pos[i*3+1] = centerY + rrange(-halfH, halfH);
      pos[i*3+2] = z;
      // Nearby stars are substantial enough to read as foreground depth cues.
      siz[i] = (hero ? rrange(0.45, 0.90) : rrange(0.035, 0.13)) * sizeScale;
      bri[i] = hero ? rrange(0.88, 1.0) : rrange(0.42, 0.82);
    } else {
      const u = rnd()*2-1, th = rnd()*Math.PI*2, r = rad*(0.35+0.65*rnd());
      const sphereS = Math.sqrt(1-u*u);
      pos[i*3]=Math.cos(th)*sphereS*r;
      pos[i*3+1]=u*r*0.85+rad*0.06;
      pos[i*3+2]=Math.sin(th)*sphereS*r;
      siz[i] = (hero ? rrange(26, 54) : rrange(7, 17)) * sizeScale;
      bri[i] = hero ? rrange(0.75, 1.0) : rrange(0.35, 0.8);
    }
    pha[i]=rnd()*6.283;
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.BufferAttribute(pos,3));
  g.setAttribute('aPha', new THREE.BufferAttribute(pha,1));
  g.setAttribute('aSize', new THREE.BufferAttribute(siz,1));
  g.setAttribute('aBri', new THREE.BufferAttribute(bri,1));
  const m = new THREE.ShaderMaterial({
    transparent:true, depthWrite:false, fog:false,
    uniforms:{ t:{value:0} },
    vertexShader:`attribute float aPha; attribute float aSize; attribute float aBri;
      varying float vPha; varying float vBri; uniform float t;
      void main(){ vPha=aPha; vBri=aBri;
        vec4 mv=modelViewMatrix*vec4(position,1.0);
        gl_PointSize = clamp(aSize * (${H * 0.5} / max(1.0, -mv.z)), 1.0, 72.0);
        gl_Position=projectionMatrix*mv; }`,
    fragmentShader:`varying float vPha; varying float vBri; uniform float t;
      void main(){
        // Slow twinkle (~1.2 Hz) stays well under the 3 Hz photosensitivity cap.
        float tw=0.72+0.28*sin(t*2.4 + vPha*6.283);
        vec2 d=gl_PointCoord-vec2(0.5);
        float r2=dot(d,d);
        if(r2>0.25) discard;
        float core=smoothstep(0.25,0.0,r2);
        float glow=smoothstep(0.25,0.02,r2);
        float a=(0.35*core+0.65*glow)*tw*vBri;
        vec3 col=mix(vec3(0.72,0.82,1.0), vec3(1.0,0.96,0.82), vBri);
        gl_FragColor=vec4(col*a, a);
      }`
  });
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
const rings = [];        // ring descriptors for collision checks
function makePlanet(params){
  const pr = params.radius ?? 2.0;
  const col = params.color ?? [0.9,0.6,0.4];
  const g = new THREE.Group();
  const spinGroup = new THREE.Group();   // only the body spins; the ring stays put
  g.add(spinGroup);
  const geo = new THREE.IcosahedronGeometry(pr, 4);
  const p = geo.attributes.position;
  const v = new THREE.Vector3();
  for (let i=0;i<p.count;i++){
    v.fromBufferAttribute(p,i);
    const n = 0.06*Math.sin(v.x*3.1+1.0)*Math.sin(v.y*2.7)*Math.cos(v.z*2.3);
    v.multiplyScalar(1.0 + n);
    p.setXYZ(i, v.x, v.y, v.z);
  }
  geo.computeVertexNormals();
  const mesh = new THREE.Mesh(geo, toonMat(col));
  mesh.castShadow = true; mesh.receiveShadow = true;
  spinGroup.add(mesh);
  const px = params.pos?params.pos[0]:0, py = params.pos?params.pos[1]:0, pz = params.pos?params.pos[2]:0;
  g.position.set(px, py, pz);
  // a little ring — geometry is parameterised so a scene can shrink/tilt it
  // away from trees instead of slicing through their canopies.
  if (params.ring !== false){
    const rIn = pr * (params.ring_inner ?? 1.4);
    const rOut = pr * (params.ring_outer ?? 1.9);
    const tilt = params.ring_tilt ?? (Math.PI*0.5);
    const ring = new THREE.Mesh(
      new THREE.RingGeometry(rIn, rOut, 64),
      new THREE.MeshBasicMaterial({color:new THREE.Color(col[0],col[1],col[2]).multiplyScalar(1.15),
        side:THREE.DoubleSide, transparent:true, opacity:0.4}));
    ring.rotation.x = tilt;
    ring.rotation.z = params.ring_roll ?? 0.0;
    g.add(ring);
    rings.push({center:[px,py,pz], inner:rIn, outer:rOut, tilt:tilt,
                roll:params.ring_roll ?? 0.0, radius:pr});
  }
  g.userData.spin = params.spin ?? 0.25;
  g.userData.spinGroup = spinGroup;
  g.userData.radius = pr;
  g.userData.planetPos = [px,py,pz];
  return g;
}

// ---- Instanced grass / wheat -------------------------------------------
// Blade geometry: a narrow tapered strip with an optional diamond "head" at
// the tip (wheat ear).  Vertex colours darken the base and brighten the tip.
function makeBladeGeometry(height, kind){
  const head = (kind === 'wheat');
  const N = 6;
  const positions = [];
  const colors = [];
  const indices = [];
  const baseCol = kind === 'wheat' ? [0.55,0.40,0.13] : [0.13,0.26,0.10];
  const tipCol  = kind === 'wheat' ? [1.00,0.86,0.34] : [0.42,0.72,0.26];
  const headCol = [1.00,0.90,0.42];
  function widthAt(f){
    if (!head) return 0.055 * (1.0 - f*0.92);
    if (f < 0.78) return 0.05 * (1.0 - f*0.9);
    const u = (f-0.78)/0.22;              // 0..1 across the ear
    return 0.012 + 0.10*Math.sin(Math.PI*u);
  }
  for (let i=0;i<=N;i++){
    const f = i/N;
    const y = height*f;
    const w = widthAt(f);
    positions.push(-w/2, y, 0,  w/2, y, 0);
    let c = baseCol;
    if (head && f > 0.78) c = headCol;
    else { const t = f; c = [baseCol[0]+(tipCol[0]-baseCol[0])*t,
                             baseCol[1]+(tipCol[1]-baseCol[1])*t,
                             baseCol[2]+(tipCol[2]-baseCol[2])*t]; }
    colors.push(c[0],c[1],c[2], c[0],c[1],c[2]);
  }
  for (let i=0;i<N;i++){
    const a=i*2, b=i*2+1, c2=(i+1)*2, d=(i+1)*2+1;
    indices.push(a,c2,b, b,c2,d);
  }
  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.Float32BufferAttribute(positions,3));
  geo.setAttribute('color', new THREE.Float32BufferAttribute(colors,3));
  geo.setIndex(indices);
  geo.computeVertexNormals();
  return geo;
}

// Obstacles that fields must not grow through (fox/rock/tree/planet footprints).
const obstacles = [];

function makeField(params){
  const kind = params.kind || 'grass';
  const count = params.count ?? 1200;
  const area = params.area ?? 30;
  const baseColor = params.color ?? (kind==='wheat'?[0.83,0.66,0.28]:[0.30,0.55,0.22]);
  const height = params.height ?? (kind==='wheat'?1.4:0.7);
  const exclude = (params.exclude || []).concat(obstacles);
  const blade = makeBladeGeometry(height, kind);
  // vertex colours already carry the gradient; tint them by the requested base.
  const mat = new THREE.MeshLambertMaterial({ vertexColors:true, side:THREE.DoubleSide });
  const mesh = new THREE.InstancedMesh(blade, mat, count);
  mesh.castShadow = false; mesh.receiveShadow = true;
  const dummy = new THREE.Object3D();
  const phases = new Float32Array(count);
  const sway = new Float32Array(count);
  const dummyPos = new Float32Array(count*3);
  let placed = 0, guard = 0;
  while (placed < count && guard < count*40){
    guard++;
    const x = rrange(-area/2, area/2);
    const z = rrange(-area/2, area/2);
    let blocked = false;
    for (const e of exclude){
      const dx = x-(e.x||0), dz = z-(e.z||0);
      if (dx*dx + dz*dz < (e.r||0)*(e.r||0)){ blocked = true; break; }
    }
    if (blocked) continue;
    const s = rrange(0.7,1.3);
    dummy.position.set(x, 0, z);
    dummy.rotation.set(0, rrange(0,6.28), 0);
    dummy.scale.set(rrange(0.8,1.2), s, rrange(0.8,1.2));
    dummy.updateMatrix();
    mesh.setMatrixAt(placed, dummy.matrix);
    phases[placed] = rrange(0,6.28);
    sway[placed] = rrange(0.5,1.0);
    dummyPos[placed*3]=x; dummyPos[placed*3+1]=0; dummyPos[placed*3+2]=z;
    placed++;
  }
  mesh.count = placed;
  mesh.instanceMatrix.needsUpdate = true;
  blade.setAttribute('aPhase', new THREE.InstancedBufferAttribute(phases,1));
  blade.setAttribute('aSway', new THREE.InstancedBufferAttribute(sway,1));
  mesh.userData = { kind, area, height, dummyPos, placed };

  // Wind in the vertex shader: the base stays planted, the tip bends.  The
  // bend is a pure function of the uniform time and per-instance phase, so
  // wind_strength=0 freezes the field exactly (deterministic).
  mat.onBeforeCompile = (shader) => {
    shader.uniforms.uTime = { value: 0 };
    shader.uniforms.uWind = { value: WEA.wind_strength ?? 1.0 };
    shader.uniforms.uWindSpeed = { value: WEA.wind_speed ?? 1.4 };
    shader.uniforms.uHeight = { value: height };
    shader.vertexShader = `attribute float aPhase; attribute float aSway;
      uniform float uTime; uniform float uWind; uniform float uWindSpeed; uniform float uHeight;
    ` + shader.vertexShader;
    shader.vertexShader = shader.vertexShader.replace(
      '#include <begin_vertex>',
      `#include <begin_vertex>
       float hf = clamp(transformed.y / max(0.0001, uHeight), 0.0, 1.0);
       float bendX = sin(uTime*uWindSpeed*0.9 + aPhase) * uWind * 0.42 * hf*hf;
       float bendZ = cos(uTime*uWindSpeed*0.7 + aPhase*1.3) * uWind * 0.16 * hf*hf;
       transformed.x += bendX * aSway;
       transformed.z += bendZ * aSway;
       transformed.y -= 0.45*(bendX*bendX + bendZ*bendZ) * hf;`
    );
    mat.userData.shader = shader;
  };
  mat.customProgramCacheKey = () => 'scene3d-wind-v1';
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
const treeSpheres = [];  // canopy bounding spheres for collision checks
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
  const tx = params.pos?params.pos[0]:0, tz = params.pos?params.pos[2]:0;
  g.position.set(tx,0,tz);
  treeSpheres.push({center:[tx, 1.7*s, tz], r: 0.9*s});
  return g;
}

// ---- Fox (round low-poly character with a face) ------------------------
function makeFox(params){
  const s = params.scale ?? 1.0;
  const col = params.color ?? [1.0,0.55,0.16];
  const cream = [1.0,0.93,0.82];
  const g = new THREE.Group();
  const faceFeatures = [];
  const eyeTargets = [];
  // Rounded body and oversized head preserve a soft preschool character silhouette.
  const body = new THREE.Mesh(new THREE.SphereGeometry(0.43,20,14), toonMat(col));
  body.scale.set(1.24,0.98,0.96);
  body.position.set(-0.06,0.49,0);
  body.castShadow = true;
  g.add(body);
  const head = new THREE.Mesh(new THREE.SphereGeometry(0.39,20,16), toonMat(col));
  head.position.set(0.60,0.73,0);
  head.castShadow = true;
  g.add(head);
  g.userData.faceHead = head;
  const muzzle = new THREE.Mesh(new THREE.SphereGeometry(0.19,14,12), toonMat(cream));
  muzzle.scale.set(1.18,0.9,0.92);
  muzzle.position.set(0.91,0.625,0);
  g.add(muzzle);
  faceFeatures.push(muzzle);
  // The local +X axis is the fox's nose/face direction. Every eye is forward
  // mounted on that plane; pupil and catchlight protrude slightly past the sclera.
  for (const z of [-0.145,0.145]){
    const eye = new THREE.Group();
    eye.position.set(0.925,0.805,z);
    const white = new THREE.Mesh(new THREE.SphereGeometry(0.105,14,12), toonMat([1,1,1]));
    white.userData.faceFeature = 'eye';
    eye.add(white);
    const pupil = new THREE.Mesh(new THREE.SphereGeometry(0.056,12,10), toonMat([0.08,0.055,0.05]));
    pupil.position.set(0.073,0,0);
    pupil.userData.faceFeature = 'eye';
    eye.add(pupil);
    const glint = new THREE.Mesh(new THREE.SphereGeometry(0.022,8,8), toonMat([1,1,1]));
    glint.position.set(0.094,0.035,0.022);
    glint.userData.faceFeature = 'eye';
    eye.add(glint);
    g.add(eye);
    eyeTargets.push(eye);
    const blush = new THREE.Mesh(new THREE.CircleGeometry(0.067,14), toonMat([1.0,0.48,0.53]));
    blush.position.set(0.91,0.65,z*1.56);
    blush.rotation.y = Math.PI/2;
    blush.userData.faceFeature = 'face';
    g.add(blush);
    faceFeatures.push(blush);
  }
  const nose = new THREE.Mesh(new THREE.SphereGeometry(0.055,10,8), toonMat([0.18,0.09,0.07]));
  nose.position.set(1.105,0.625,0);
  nose.userData.faceFeature = 'face';
  g.add(nose);
  faceFeatures.push(nose);
  // Soft, triangular ears with pink inner surfaces.
  for (const z of [-0.19,0.19]){
    const ear = new THREE.Mesh(new THREE.ConeGeometry(0.125,0.31,10), toonMat(col));
    ear.position.set(0.54,1.065,z);
    g.add(ear);
    const inner = new THREE.Mesh(new THREE.ConeGeometry(0.062,0.17,8), toonMat([1.0,0.68,0.72]));
    inner.position.set(0.565,1.055,z*1.02);
    g.add(inner);
  }
  const tail = new THREE.Mesh(new THREE.ConeGeometry(0.25,0.78,12), toonMat(col));
  tail.position.set(-0.63,0.59,0);
  tail.rotation.z = Math.PI/2.5;
  g.add(tail);
  const tailTip = new THREE.Mesh(new THREE.SphereGeometry(0.16,12,10), toonMat(cream));
  tailTip.position.set(-0.96,0.80,0);
  g.add(tailTip);
  // Short rounded orange-brown paws replace the long dark wooden-looking pillars.
  for (const x of [0.29,-0.34]) for (const z of [-0.19,0.19]){
    const leg = new THREE.Mesh(new THREE.CapsuleGeometry(0.085,0.15,4,10), toonMat([0.74,0.30,0.075]));
    leg.position.set(x,0.18,z);
    leg.castShadow = true;
    g.add(leg);
  }
  g.scale.setScalar(s);
  const fx = params.pos ? params.pos[0] : 0;
  const fz = params.pos ? params.pos[2] : 0;
  g.position.set(fx, params.pos ? params.pos[1] : 0, fz);
  g.rotation.y = params.rotY ?? -Math.PI/2;
  g.userData.eyeTargets = eyeTargets;
  g.userData.faceFeatures = faceFeatures;
  g.userData.sit = params.sit ?? false;
  obstacles.push({x:fx, z:fz, r:1.15*s});
  return g;
}

// ---- Collect field-exclusion footprints before building fields ---------
for (const a of AST){
  const p = a.params || {};
  const px = p.pos?p.pos[0]:0, pz = p.pos?p.pos[2]:0;
  if (a.kind === 'fox')   obstacles.push({x:px, z:pz, r: 1.15*(p.scale??1)});
  else if (a.kind === 'rock') obstacles.push({x:px, z:pz, r: 0.95*(p.scale??1)});
  else if (a.kind === 'tree') obstacles.push({x:px, z:pz, r: 1.15*(p.scale??1)});
  else if (a.kind === 'planet') obstacles.push({x:px, z:pz, r: (p.radius??2.0)*1.15});
}

// ---- Build assets ------------------------------------------------------
const dynamic = []; // objects that need per-frame updates
const fields = [];  // instanced fields for wind
const planetObjs = [];
const foxObjs = [];
for (const a of AST){
  const p = a.params || {};
  if (a.kind === 'planet'){ const o = makePlanet(p); scene.add(o); dynamic.push({obj:o, type:'planet'}); planetObjs.push(o); }
  else if (a.kind === 'wheat'){ const o = makeField(Object.assign({kind:'wheat'},p)); scene.add(o); fields.push(o); }
  else if (a.kind === 'grass'){ const o = makeField(Object.assign({kind:'grass'},p)); scene.add(o); fields.push(o); }
  else if (a.kind === 'ground'){ scene.add(makeGround(p)); }
  else if (a.kind === 'rock'){ scene.add(makeRock(p)); }
  else if (a.kind === 'tree'){ scene.add(makeTree(p)); }
  else if (a.kind === 'fox'){ const o = makeFox(p); scene.add(o); dynamic.push({obj:o, type:'fox'}); foxObjs.push(o); }
  else { console.warn('unknown asset kind', a.kind); }
}
// Primary subjects for safe-area framing: the largest planet body (the hero
// world — decorative rings are translucent and deliberately excluded) and any
// fox.  Background planets are excluded so a distant speck cannot drag the
// framing bbox off-screen.
const subjects = [];
if (planetObjs.length){
  let hero = planetObjs[0];
  for (const o of planetObjs) if (o.userData.radius > hero.userData.radius) hero = o;
  subjects.push({sphere:{center:hero.userData.planetPos, radius:hero.userData.radius*1.12}});
}
for (const o of foxObjs) subjects.push({box:o});

// ---- Composer (bloom) --------------------------------------------------
const composer = new EffectComposer(renderer);
composer.setSize(W, H);
composer.addPass(new RenderPass(scene, camera));
const bloom = new UnrealBloomPass(new THREE.Vector2(W,H), WEA.bloom_strength, WEA.bloom_radius, WEA.bloom_threshold);
composer.addPass(bloom);
composer.addPass(new OutputPass());

// ---- Camera path interpolation -----------------------------------------
function activePath(){
  // A per-aspect override lets a portrait shot reframe (pull back) instead of
  // reusing the landscape flight, which crops the subject off the top.
  if (CAM.paths && CAM.paths[CAM.aspect] && CAM.paths[CAM.aspect].length){
    return CAM.paths[CAM.aspect];
  }
  return CAM.path || [];
}
function sampleCam(t){
  const path = activePath();
  if (!path.length){ return; }
  let i0=0;
  for (let i=0;i<path.length;i++){
    if (path[i].t <= t+1e-6){ i0=i; }
  }
  const i1 = Math.min(i0+1, path.length-1);
  const a = path[i0], b = path[i1];
  let u = 0;
  if (b.t > a.t){ u = Math.min(1, Math.max(0,(t-a.t)/(b.t-a.t))); }
  const pos = [a.pos[0]+(b.pos[0]-a.pos[0])*u, a.pos[1]+(b.pos[1]-a.pos[1])*u, a.pos[2]+(b.pos[2]-a.pos[2])*u];
  const look= [a.look[0]+(b.look[0]-a.look[0])*u, a.look[1]+(b.look[1]-a.look[1])*u, a.look[2]+(b.look[2]-a.look[2])*u];
  camera.position.set(pos[0],pos[1],pos[2]);
  camera.lookAt(look[0],look[1],look[2]);
}

// ---- Time stepping -----------------------------------------------------
let curT = 0;
function setTime(t){
  curT = t;
  sampleCam(t);
  for (const d of dynamic){
    if (d.type === 'planet'){ d.obj.userData.spinGroup.rotation.y = curT * d.obj.userData.spin; }
    else if (d.type === 'fox'){
      if (WEA.fox_face_camera || SPEC.name === 'fox_in_wheat'){
        const toCamera = camera.position.clone().sub(d.obj.position);
        d.obj.rotation.y = Math.atan2(-toCamera.z, toCamera.x);
      }
      d.obj.rotation.z = (WEA.fox_sway !== false) ? Math.sin(curT*1.5)*0.025 : 0;
    }
  }
  if (starField){ starField.material.uniforms.t.value = t; }
  for (const f of fields){
    const sh = f.material.userData.shader;
    if (sh){ sh.uniforms.uTime.value = t; }
  }
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
window.__framePixels = function(){ return canvas.toDataURL('image/png'); };

// Ground-truth placed field instances (for Python-side collision tests).
window.__instancePositions = function(){
  const out = [];
  for (const f of fields){
    const dp = f.userData.dummyPos;
    for (let i=0;i<f.count;i++){
      out.push({kind:f.userData.kind, x:dp[i*3], y:dp[i*3+1], z:dp[i*3+2],
                tip_y:f.userData.height});
    }
  }
  return out;
};

// Screen-space bounding box of all *subjects* (hero planet body + fox),
// normalised to [0,1] with y measured downward.  Used by safe-area framing
// tests.  Planet rings are excluded (decorative, translucent).
window.__subjectScreenBBox = function(){
  camera.updateMatrixWorld();
  let x0=Infinity, y0=Infinity, x1=-Infinity, y1=-Infinity;
  const v = new THREE.Vector3();
  const tanH = Math.tan(THREE.MathUtils.degToRad(camera.fov)/2) * camera.aspect;
  const tanV = Math.tan(THREE.MathUtils.degToRad(camera.fov)/2);
  function addNdc(px, py){
    const sx = px*0.5+0.5, sy = 1.0-(py*0.5+0.5);
    x0=Math.min(x0,sx); x1=Math.max(x1,sx); y0=Math.min(y0,sy); y1=Math.max(y1,sy);
  }
  for (const s of subjects){
    if (s.sphere){
      // Accurate silhouette of a sphere: project the centre, then expand by the
      // angular radius r/|c| converted to NDC using the camera's tangents.
      v.set(s.sphere.center[0], s.sphere.center[1], s.sphere.center[2]);
      const cam = v.clone().applyMatrix4(camera.matrixWorldInverse);
      const dist = Math.max(1e-3, -cam.z);
      const ndc = v.clone().project(camera);
      const rx = (s.sphere.radius/dist)/tanH;
      const ry = (s.sphere.radius/dist)/tanV;
      addNdc(ndc.x-rx, ndc.y-ry); addNdc(ndc.x+rx, ndc.y+ry);
    } else if (s.box){
      const bb = new THREE.Box3().setFromObject(s.box, true);
      for (const x of [bb.min.x, bb.max.x])
        for (const y of [bb.min.y, bb.max.y])
          for (const z of [bb.min.z, bb.max.z]){
            const p = new THREE.Vector3(x,y,z).project(camera);
            addNdc(p.x, p.y);
          }
    }
  }
  if (!isFinite(x0)) return null;
  return {x0, y0, x1, y1, width:x1-x0, height:y1-y0};
};

// Scene-grounded visual diagnostics for the R2 independent acceptance tests.
window.__foxFaceStats = function(times){
  const rows = [];
  const projectBox = (obj) => {
    const bb = new THREE.Box3().setFromObject(obj, true);
    let x0=Infinity,y0=Infinity,x1=-Infinity,y1=-Infinity;
    for (const x of [bb.min.x,bb.max.x]) for (const y of [bb.min.y,bb.max.y]) for (const z of [bb.min.z,bb.max.z]){
      const p = new THREE.Vector3(x,y,z).project(camera);
      const sx=p.x*0.5+0.5, sy=1-(p.y*0.5+0.5);
      x0=Math.min(x0,sx); x1=Math.max(x1,sx); y0=Math.min(y0,sy); y1=Math.max(y1,sy);
    }
    return {x0,y0,x1,y1,width:x1-x0,height:y1-y0};
  };
  for (const t of times){
    setTime(t);
    scene.updateMatrixWorld(true); camera.updateMatrixWorld(true);
    for (const fox of foxObjs){
      const forward = new THREE.Vector3(1,0,0).applyQuaternion(fox.quaternion).normalize();
      const toCam = camera.position.clone().sub(fox.position).normalize();
      const eyes = fox.userData.eyeTargets.map((eye) => {
        const center = eye.getWorldPosition(new THREE.Vector3());
        const ndc = center.clone().project(camera);
        const rayDir = center.clone().sub(camera.position).normalize();
        const ray = new THREE.Raycaster(camera.position.clone(), rayDir, camera.near, camera.far);
        const hits = ray.intersectObjects(scene.children, true);
        const first = hits.length ? hits[0].object : null;
        return {
          x:ndc.x*0.5+0.5, y:1-(ndc.y*0.5+0.5), z:ndc.z,
          inFrame:ndc.z>=-1 && ndc.z<=1 && Math.abs(ndc.x)<=0.98 && Math.abs(ndc.y)<=0.98,
          notOccluded:!!first && first.userData.faceFeature==='eye',
          firstHit:first ? (first.userData.faceFeature || first.type || first.name || 'mesh') : 'none'
        };
      });
      rows.push({time:t, dot:forward.dot(toCam), headBBox:projectBox(fox.userData.faceHead), eyes});
    }
  }
  return rows;
};

window.__starProximityStats = function(times){
  const rows=[];
  const path=activePath();
  const travel=(path.length>1) ? new THREE.Vector3(...path[path.length-1].pos).distanceTo(new THREE.Vector3(...path[0].pos)) : 0;
  for (const t of times){
    setTime(t); scene.updateMatrixWorld(true); camera.updateMatrixWorld(true);
    let nearVisible=0, nearestVisible=Infinity, visible=0;
    if (starPositions){
      for (let i=0;i<starPositions.length/3;i++){
        const v=new THREE.Vector3(starPositions[i*3],starPositions[i*3+1],starPositions[i*3+2]);
        const dist=camera.position.distanceTo(v);
        const ndc=v.clone().project(camera);
        if (ndc.z>=-1 && ndc.z<=1 && Math.abs(ndc.x)<=1 && Math.abs(ndc.y)<=1){
          visible++;
          if (dist<8){ nearVisible++; nearestVisible=Math.min(nearestVisible,dist); }
        }
      }
    }
    rows.push({time:t, visible, nearVisible, nearestVisible:nearVisible ? nearestVisible : null});
  }
  return {rows, maxVisibleNear:Math.max(0,...rows.map(r=>r.nearVisible)), pathTravel:travel,
    groundAssets:AST.filter(a=>a.kind==='ground').length, grassAssets:AST.filter(a=>a.kind==='grass').length};
};

// ---- Collision report (no穿模) -----------------------------------------
// Ring (annulus in its own plane) vs tree canopy spheres, and field instances
// vs solid obstacle footprints (fox/rock/tree/planet).  Any hit is a failure.
window.__collisionReport = function(){
  const violations = [];
  // 1) ring annulus vs tree canopy spheres
  for (const r of rings){
    const normal = new THREE.Vector3(0,0,1);
    const e = new THREE.Euler(r.tilt, 0, r.roll, 'XYZ');
    normal.applyEuler(e).normalize();
    for (const t of treeSpheres){
      const c = new THREE.Vector3(t.center[0]-r.center[0], t.center[1]-r.center[1], t.center[2]-r.center[2]);
      const perp = Math.abs(c.dot(normal));
      if (perp > t.r) continue;
      const planar = c.clone().addScaledVector(normal, -c.dot(normal));
      const d = planar.length();
      const radialHit = (d + t.r >= r.inner) && (d - t.r <= r.outer);
      if (radialHit) violations.push({type:'ring_tree', ring_radius:r.radius, dist:d, tree_r:t.r});
    }
  }
  // 2) field instances vs obstacle footprints
  for (const f of fields){
    const dp = f.userData.dummyPos;
    for (let i=0;i<f.count;i++){
      const x=dp[i*3], z=dp[i*3+2];
      for (const o of obstacles){
        const dx=x-o.x, dz=z-o.z;
        if (dx*dx+dz*dz < o.r*o.r) violations.push({type:'field_obstacle', field:f.userData.kind, i});
      }
    }
  }
  return {violations, counts:{fields:fields.length, obstacles:obstacles.length, rings:rings.length, trees:treeSpheres.length}};
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
