"""M3 OSM 实景街区 (locscout) — Three.js template.

Renders 3D city buildings, roads, white lines, trees, and utility poles
(电线杆) with human-eye camera (1.55m) in comic line-art + halftone style.
CPU-only SwiftShader.
"""

from __future__ import annotations

import json


_PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<style>html,body{margin:0;padding:0;background:#fff;overflow:hidden;}#c{display:block;}</style>
<script type="importmap">
{ "imports": { "three": "./vendor/three/three.module.js" } }
</script>
</head>
<body>
<canvas id="c"></canvas>
<script type="module">
import * as THREE from 'three';

const SPEC = /*__LOC_SPEC__*/;
const S = SPEC.spec || SPEC;
const W = SPEC.width, H = SPEC.height;
const FPS = SPEC.fps, DUR = SPEC.duration_s || 0;
const LIG = SPEC.lighting;

const canvas = document.getElementById('c');
canvas.width = W; canvas.height = H;
const renderer = new THREE.WebGLRenderer({canvas, antialias:false, preserveDrawingBuffer:true});
renderer.setPixelRatio(1); renderer.setSize(W,H,false);
renderer.shadowMap.enabled = true; renderer.shadowMap.type = THREE.PCFSoftShadowMap;
renderer.outputColorSpace = THREE.SRGBColorSpace;

const scene = new THREE.Scene();
scene.background = new THREE.Color(LIG.sky_bottom[0], LIG.sky_bottom[1], LIG.sky_bottom[2]);
scene.fog = new THREE.FogExp2(
  new THREE.Color(LIG.sky_bottom[0], LIG.sky_bottom[1], LIG.sky_bottom[2]).getHex(),
  0.007
);

const camera = new THREE.PerspectiveCamera(45, W/H, 0.2, 500);

// ---- lighting ----
const az = LIG.sun_azimuth * Math.PI / 180, el = LIG.sun_elevation * Math.PI / 180;
const sx = Math.cos(el)*Math.cos(az)*120, sy = Math.sin(el)*120, sz = Math.cos(el)*Math.sin(az)*120;
const sun = new THREE.DirectionalLight(
  new THREE.Color(LIG.sun_color[0], LIG.sun_color[1], LIG.sun_color[2]),
  LIG.sun_intensity
);
sun.position.set(sx, sy, sz);
sun.castShadow = true;
sun.shadow.mapSize.set(1024, 1024);
const d = 100;
sun.shadow.camera.left = -d; sun.shadow.camera.right = d;
sun.shadow.camera.top = d; sun.shadow.camera.bottom = -d;
sun.shadow.camera.near = 10; sun.shadow.camera.far = 300;
scene.add(sun);

scene.add(new THREE.HemisphereLight(
  new THREE.Color(LIG.sky_top[0], LIG.sky_top[1], LIG.sky_top[2]),
  new THREE.Color(LIG.ambient_color[0], LIG.ambient_color[1], LIG.ambient_color[2]),
  LIG.ambient_intensity
));

const inked = [];

function toon(col) {
  return new THREE.MeshToonMaterial({ color: new THREE.Color(col[0], col[1], col[2]) });
}

// ---- Ground ----
const ground = new THREE.Mesh(
  new THREE.CircleGeometry(SPEC.spec.radius_m * 1.5, 64),
  toon([0.88, 0.86, 0.84])
);
ground.rotation.x = -Math.PI / 2;
ground.position.y = -0.05;
ground.receiveShadow = true;
scene.add(ground);

// ---- Buildings ----
for (const b of SPEC.buildings) {
  // Use bounding box of footprint for robust, deterministic CPU rendering
  const poly = b.polygon;
  let minX = Infinity, maxX = -Infinity, minZ = Infinity, maxZ = -Infinity;
  for (const pt of poly) {
    if (pt[0] < minX) minX = pt[0];
    if (pt[0] > maxX) maxX = pt[0];
    if (pt[1] < minZ) minZ = pt[1];
    if (pt[1] > maxZ) maxZ = pt[1];
  }
  const bw = Math.max(2.0, maxX - minX);
  const bd = Math.max(2.0, maxZ - minZ);
  const cx = (minX + maxX) * 0.5;
  const cz = (minZ + maxZ) * 0.5;
  const bh = b.height;
  const by = b.base_y + bh * 0.5;

  const g = new THREE.BoxGeometry(bw, bh, bd);
  const m = toon(b.color);
  const mesh = new THREE.Mesh(g, m);
  mesh.position.set(cx, by, cz);
  mesh.castShadow = true;
  mesh.receiveShadow = true;
  scene.add(mesh);
  inked.push(mesh);
}

// ---- Roads & White Lines ----
for (const rd of SPEC.roads) {
  const pts = rd.points;
  if (pts.length < 2) continue;
  const rWidth = rd.width;

  // Build quad strip
  const geom = new THREE.BufferGeometry();
  const vPos = [];
  const linePos = [];

  for (let i = 0; i < pts.length - 1; i++) {
    const p1 = pts[i], p2 = pts[i+1];
    const dx = p2[0] - p1[0], dz = p2[2] - p1[2];
    const len = Math.hypot(dx, dz);
    if (len < 0.1) continue;
    const nx = -dz / len * (rWidth * 0.5);
    const nz = dx / len * (rWidth * 0.5);

    // 2 triangles = 1 quad
    vPos.push(
      p1[0] - nx, p1[1] + 0.02, p1[2] - nz,
      p1[0] + nx, p1[1] + 0.02, p1[2] + nz,
      p2[0] - nx, p2[1] + 0.02, p2[2] - nz,

      p1[0] + nx, p1[1] + 0.02, p1[2] + nz,
      p2[0] + nx, p2[1] + 0.02, p2[2] + nz,
      p2[0] - nx, p2[1] + 0.02, p2[2] - nz
    );

    // Center white line
    linePos.push(p1[0], p1[1] + 0.04, p1[2], p2[0], p2[1] + 0.04, p2[2]);
  }

  if (vPos.length > 0) {
    geom.setAttribute('position', new THREE.Float32BufferAttribute(vPos, 3));
    geom.computeVertexNormals();
    const rdMesh = new THREE.Mesh(geom, toon([0.72, 0.72, 0.74]));
    rdMesh.receiveShadow = true;
    scene.add(rdMesh);
  }

  if (linePos.length > 0) {
    const lGeom = new THREE.BufferGeometry();
    lGeom.setAttribute('position', new THREE.Float32BufferAttribute(linePos, 3));
    const whiteLine = new THREE.LineSegments(
      lGeom,
      new THREE.LineBasicMaterial({ color: 0xffffff, linewidth: 2 })
    );
    scene.add(whiteLine);
  }
}

// ---- Utility Poles (电线杆) ----
for (const p of SPEC.poles) {
  const poleGroup = new THREE.Group();
  // Main vertical pole
  const pg = new THREE.CylinderGeometry(0.12, 0.15, p.height, 8);
  const pm = toon([0.5, 0.5, 0.52]);
  const pMesh = new THREE.Mesh(pg, pm);
  pMesh.position.y = p.height * 0.5;
  pMesh.castShadow = true;
  poleGroup.add(pMesh);
  inked.push(pMesh);

  // Crossbar 1 (top)
  const cb1 = new THREE.Mesh(new THREE.BoxGeometry(1.6, 0.08, 0.08), toon([0.4, 0.4, 0.4]));
  cb1.position.set(0, p.height - 0.4, 0);
  cb1.castShadow = true;
  poleGroup.add(cb1);

  // Crossbar 2
  const cb2 = new THREE.Mesh(new THREE.BoxGeometry(1.2, 0.08, 0.08), toon([0.4, 0.4, 0.4]));
  cb2.position.set(0, p.height - 1.2, 0);
  cb2.castShadow = true;
  poleGroup.add(cb2);

  // Transformer box
  const tb = new THREE.Mesh(new THREE.CylinderGeometry(0.22, 0.22, 0.6, 8), toon([0.45, 0.45, 0.48]));
  tb.position.set(0.3, p.height - 1.8, 0);
  tb.castShadow = true;
  poleGroup.add(tb);

  poleGroup.position.set(p.pos[0], p.pos[1], p.pos[2]);
  poleGroup.rotation.y = p.rotY || 0;
  scene.add(poleGroup);
}

// ---- Trees ----
for (const t of SPEC.trees) {
  const tg = new THREE.Group();
  const trunk = new THREE.Mesh(new THREE.CylinderGeometry(0.12, 0.18, 1.4, 6), toon([0.45, 0.35, 0.25]));
  trunk.position.y = 0.7;
  trunk.castShadow = true;
  tg.add(trunk);

  const foliage = new THREE.Mesh(new THREE.ConeGeometry(1.1, 2.4, 7), toon([0.35, 0.55, 0.35]));
  foliage.position.y = 2.4;
  foliage.castShadow = true;
  tg.add(foliage);

  tg.scale.setScalar(t.scale || 1.0);
  tg.position.set(t.pos[0], t.pos[1], t.pos[2]);
  scene.add(tg);
  inked.push(trunk);
  inked.push(foliage);
}

// ---- Comic Outlines ----
const outlineGroup = new THREE.Group();
for (const mesh of inked) {
  const eg = new THREE.EdgesGeometry(mesh.geometry, 28);
  const line = new THREE.LineSegments(eg, new THREE.LineBasicMaterial({ color: 0x111111 }));
  line.position.copy(mesh.position);
  line.rotation.copy(mesh.rotation);
  line.scale.copy(mesh.scale);
  outlineGroup.add(line);
}
scene.add(outlineGroup);

// ---- Halftone Overlay (Screen-space dots) ----
const halftone = (function() {
  const c = document.createElement('canvas'); c.width = W; c.height = H;
  const g = c.getContext('2d');
  g.fillStyle = 'rgba(255,255,255,1)'; g.fillRect(0, 0, W, H);
  g.fillStyle = 'rgba(30,30,30,0.25)';
  const step = 6;
  for (let y = 0; y < H; y += step) {
    for (let x = 0; x < W; x += step) {
      g.beginPath(); g.arc(x, y, 1.0, 0, 7); g.fill();
    }
  }
  const tex = new THREE.CanvasTexture(c);
  const mat = new THREE.MeshBasicMaterial({ map: tex, transparent: true, opacity: 0.45, depthTest: false });
  const plane = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), mat);
  plane.position.set(0, 0, -1); plane.frustumCulled = false;
  return { plane };
})();

const ovScene = new THREE.Scene();
ovScene.add(halftone.plane);
const ovCam = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1);

function placeCamera(t) {
  // Eye height = 1.55m
  const eyeH = S.camera_height || 1.55;
  const yaw = S.camera_yaw || 0.0;
  const pitch = S.camera_pitch || 0.05;

  // Dolly forward or pan for video if DUR > 0
  const progress = DUR > 0 ? (t / DUR) : 0.0;
  const moveZ = progress * (S.orbit_speed || 0.1) * 20.0;
  const camX = 0.0;
  const camY = eyeH;
  const camZ = -moveZ;

  camera.position.set(camX, camY, camZ);
  // Look down the street
  const lookDist = 50.0;
  const lx = camX + Math.sin(yaw + progress * 0.15) * lookDist;
  const ly = camY + Math.tan(pitch) * lookDist;
  const lz = camZ - Math.cos(yaw + progress * 0.15) * lookDist;
  camera.lookAt(lx, ly, lz);
}

function render() {
  renderer.autoClear = true;
  renderer.render(scene, camera);
  renderer.autoClear = false;
  renderer.render(ovScene, ovCam);
  renderer.autoClear = true;
}

let curT = 0;
function setTime(t) {
  curT = t;
  placeCamera(t);
  render();
}

window.__setTime = function(t) { setTime(t); return true; };
window.__framePixels = function() { return canvas.toDataURL('image/png'); };
window.__SCENE3D_DONE = true;
</script>
</body>
</html>
"""


def build_html(loc_scene_json: dict, width: int, height: int, fps: int = 24, duration_s: float = 0.0) -> str:
    payload = dict(loc_scene_json)
    payload["width"] = width
    payload["height"] = height
    payload["fps"] = fps
    payload["duration_s"] = duration_s
    js = json.dumps(payload, ensure_ascii=False)
    return _PAGE.replace("/*__LOC_SPEC__*/", js)
