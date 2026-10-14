"""M2 房间背景抽卡 — Three.js template.

Renders a procedural room (floor grid, walls with windows/doors, furniture from
box/cylinder primitives) as manga line art + halftone shading on CPU via
SwiftShader.  The page exposes the standard deterministic API:

    window.__setTime(t)        -> place camera + (optional) animate
    window.__framePixels()     -> PNG data URL
    window.__SCENE3D_DONE      -> ready flag

Style:
  - MeshToon material -> flat comic bands.
  - EdgesGeometry outlines -> ink lines (render an inverted-hull / line pass).
  - A screen-space halftone dot overlay -> 网点阴影.
  - Optional solid color mode toggles toon bands off.

No external textures.  Deterministic from the injected JSON.
"""

from __future__ import annotations

import json
from pathlib import Path

import importlib.resources as _ir

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

const SPEC = /*__ROOM_SPEC__*/;
const S = SPEC.spec || SPEC;
const W = SPEC.width, H = SPEC.height;
const FPS = SPEC.fps, DUR = SPEC.duration_s;
const SOLID = !!S.solid_color;
const AZ = (S.light_azimuth != null ? S.light_azimuth : 45) * Math.PI/180, EL = (S.light_elevation != null ? S.light_elevation : 45) * Math.PI/180;
const lx = Math.cos(EL)*Math.cos(AZ), ly = Math.sin(EL), lz = Math.cos(EL)*Math.sin(AZ);

const canvas = document.getElementById('c');
canvas.width = W; canvas.height = H;
const renderer = new THREE.WebGLRenderer({canvas, antialias:false, preserveDrawingBuffer:true});
renderer.setPixelRatio(1); renderer.setSize(W,H,false);
renderer.shadowMap.enabled = true; renderer.shadowMap.type = THREE.PCFSoftShadowMap;
renderer.outputColorSpace = THREE.SRGBColorSpace;

const scene = new THREE.Scene();
scene.background = new THREE.Color(0xffffff);
const camera = new THREE.PerspectiveCamera(35, W/H, 0.1, 200);
const camR = SPEC.camera ? SPEC.camera.radius : 9.0;
const camH = SPEC.camera ? SPEC.camera.height : 3.2;
const camA = SPEC.camera ? SPEC.camera.azimuth : 0.7;

function toon(color){
  const c = new THREE.Color(color[0],color[1],color[2]);
  if (SOLID) return new THREE.MeshBasicMaterial({color:c});
  const m = new THREE.MeshToonMaterial({color:c});
  return m;
}
// toon gradient map: 3 bands
(function(){
  const colors = new Uint8Array([90,140,210]);
  const tex = new THREE.DataTexture(colors, colors.length, 1, THREE.RedFormat);
  tex.needsUpdate = true;
  THREE.ColorManagement.enabled = false;
})();

// ---- lights ----
const sun = new THREE.DirectionalLight(0xffffff, 1.05);
sun.position.set(lx*10, ly*10, lz*10);
sun.castShadow = true; sun.shadow.mapSize.set(1024,1024);
const d=14; sun.shadow.camera.left=-d; sun.shadow.camera.right=d;
sun.shadow.camera.top=d; sun.shadow.camera.bottom=-d; sun.shadow.camera.near=1; sun.shadow.camera.far=40;
scene.add(sun);
scene.add(new THREE.HemisphereLight(0xffffff, 0xbfb9ad, 0.55));

const inked = [];   // meshes that get outline edges

// ---- floor tiles ----
for (const t of SPEC.floor){
  const g = new THREE.BoxGeometry(t.size[0], t.size[1], t.size[2]);
  const m = toon(t.color);
  const mesh = new THREE.Mesh(g, m);
  mesh.position.set(t.pos[0], t.pos[1], t.pos[2]);
  mesh.receiveShadow = true;
  scene.add(mesh);
  inked.push(mesh);
}

// ---- walls (skip window/door gaps via simple boxes) ----
(function(){
  const half = SPEC.walls.half, hgt = SPEC.walls.height, th = 0.2;
  const wc = S.wall_color || [0.92, 0.90, 0.86];
  function wall(cx,cy,cz,sx,sy,sz){
    const g=new THREE.BoxGeometry(sx,sy,sz);
    const m=toon(wc); const mesh=new THREE.Mesh(g,m);
    mesh.position.set(cx,cy,cz); mesh.receiveShadow=true; mesh.castShadow=false;
    scene.add(mesh); inked.push(mesh);
  }
  // back wall (z=-half) with two windows
  const wins = SPEC.walls.windows.filter(w=>w.wall==='back');
  // build as segments between/around windows
  let x = -half;
  const segY0=0, segY1=hgt;
  // simpler: full wall then cut window holes as lighter panels
  wall(0, hgt/2, -half, half*2, hgt, th);
  for (const w of wins){
    // window frame
    const g=new THREE.BoxGeometry(w.w, w.h, 0.24);
    const m=new THREE.MeshBasicMaterial({color:0x9fc4e8});
    const mesh=new THREE.Mesh(g,m); mesh.position.set(w.x, w.y, -half+0.02); scene.add(mesh);
    const frame=new THREE.Mesh(new THREE.BoxGeometry(w.w+0.12,w.h+0.12,0.1), toon([0.2,0.2,0.2]));
    frame.position.set(w.x,w.y,-half+0.05); scene.add(frame); inked.push(frame);
  }
  const lw = SPEC.walls.windows.filter(w=>w.wall==='left');
  wall(-half, hgt/2, 0, th, hgt, half*2);
  for (const w of lw){
    const g=new THREE.BoxGeometry(0.24,w.h,w.w);
    const m=new THREE.MeshBasicMaterial({color:0x9fc4e8});
    const mesh=new THREE.Mesh(g,m); mesh.position.set(-half+0.02, w.y, w.z); scene.add(mesh);
  }
  // right wall with door
  const door=SPEC.walls.door;
  // segments above and beside door
  wall(half, hgt/2, 0, th, hgt, half*2);
  const dg=new THREE.BoxGeometry(0.3, door.h, door.w);
  const dm=new THREE.MeshBasicMaterial({color:0x6a4a2a}); const dmesh=new THREE.Mesh(dg,dm);
  dmesh.position.set(half-0.02, door.y, door.z); scene.add(dmesh); inked.push(dmesh);
})();

// ---- furniture ----
function rotY(mesh, a){ mesh.rotation.y = a; }
for (const p of SPEC.furniture){
  let geo;
  if (p.kind==='box') geo = new THREE.BoxGeometry(p.size[0],p.size[1],p.size[2]);
  else geo = new THREE.CylinderGeometry(p.radius, p.radius, p.height, 16);
  const m = toon(p.color);
  const mesh = new THREE.Mesh(geo, m);
  mesh.position.set(p.pos[0], p.pos[1], p.pos[2]);
  mesh.rotation.y = p.rotY || 0;
  mesh.castShadow = true; mesh.receiveShadow = true;
  scene.add(mesh); inked.push(mesh);
}

// ---- ink outlines (inverted hull) ----
const outlineGroup = new THREE.Group();
for (const mesh of inked){
  const eg = new THREE.EdgesGeometry(mesh.geometry, 25);
  const line = new THREE.LineSegments(eg, new THREE.LineBasicMaterial({color:0x111111}));
  line.position.copy(mesh.position); line.rotation.copy(mesh.rotation); line.scale.copy(mesh.scale);
  outlineGroup.add(line);
}
scene.add(outlineGroup);

// ---- halftone overlay (screen-space dots) ----
const halftone = (function(){
  const c = document.createElement('canvas'); c.width=W; c.height=H;
  const g = c.getContext('2d');
  g.fillStyle = 'rgba(255,255,255,1)'; g.fillRect(0,0,W,H);
  g.fillStyle = 'rgba(40,40,40,0.30)';
  const step = 6;
  for (let y=0;y<H;y+=step){ for (let x=0;x<W;x+=step){ g.beginPath(); g.arc(x,y,1.1,0,7); g.fill(); } }
  const tex = new THREE.CanvasTexture(c);
  const mat = new THREE.MeshBasicMaterial({map:tex, transparent:true, opacity:0.5, depthTest:false});
  const plane = new THREE.Mesh(new THREE.PlaneGeometry(2,2), mat);
  plane.position.set(0,0,-1); plane.frustumCulled=false;
  return {tex, mat, plane};
})();

function placeCamera(t){
  const a = camA + (SPEC.camera && SPEC.camera.orbit ? (t/DUR)*SPEC.camera.orbit : 0);
  const x = Math.cos(a)*camR, z = Math.sin(a)*camR;
  camera.position.set(x, camH, z);
  camera.lookAt(0, 1.2, 0);
}

let curT=0;
const ovScene = new THREE.Scene();
ovScene.add(halftone.plane);
const ovCam = new THREE.OrthographicCamera(-1,1,1,-1,0,1);
function render(){
  renderer.autoClear = true;
  renderer.render(scene, camera);
  renderer.autoClear = false;
  renderer.render(ovScene, ovCam);
  renderer.autoClear = true;
}
function setTime(t){
  curT=t; placeCamera(t);
  render();
}

window.__setTime = function(t){ setTime(t); return true; };
window.__framePixels = function(){ return canvas.toDataURL('image/png'); };
window.__SCENE3D_DONE = true;
</script>
</body>
</html>
"""


def build_html(spec_json: dict, width: int, height: int, fps: int, duration_s: float) -> str:
    """Inject the room spec + render params into the page template."""
    payload = dict(spec_json)
    payload["width"] = width
    payload["height"] = height
    payload["fps"] = fps
    payload["duration_s"] = duration_s
    js = json.dumps(payload, ensure_ascii=False)
    return _PAGE.replace("/*__ROOM_SPEC__*/", js)
