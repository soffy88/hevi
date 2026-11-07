"""oskill: normalised scene + baked camera -> self-contained Three.js page.

The page exposes ``window.__setFrame(i, t)`` (camera from the baked array, object
animation from ``t`` only) and sets ``window.__READY`` / ``window.__ERROR``.
Nothing reads the wall clock and all randomness is seeded, so frame i is a pure
function of (scene, i).
"""
from __future__ import annotations

import json
from typing import Any

_PAGE = r"""<!DOCTYPE html>
<html><head><meta charset="utf-8"/>
<style>html,body{margin:0;padding:0;background:#000;overflow:hidden}#c{display:block}</style>
<script type="importmap">{"imports":{"three":"./vendor/three/three.module.js"}}</script>
</head><body><canvas id="c"></canvas>
<script type="module">
import * as THREE from 'three';
import { GLTFLoader } from './vendor/three/addons/loaders/GLTFLoader.js';
const S = /*SCENE*/null;
const CAM = /*CAMERA*/null;
const DEG = Math.PI / 180;
function rng(seed){ let a = seed >>> 0; return () => { a = (a + 0x6D2B79F5) >>> 0; let t = a;
  t = Math.imul(t ^ (t >>> 15), t | 1); t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
  return ((t ^ (t >>> 14)) >>> 0) / 4294967296; }; }
try {
const canvas = document.getElementById('c');
const R = S.renderer;
const renderer = new THREE.WebGLRenderer({canvas, antialias: R.antialias, preserveDrawingBuffer: true});
renderer.setPixelRatio(1); renderer.setSize(S.width, S.height, false);
canvas.style.width = S.width + 'px'; canvas.style.height = S.height + 'px';
renderer.shadowMap.enabled = !!R.shadows; renderer.shadowMap.type = THREE.PCFShadowMap;
if (R.tone_mapping === 'aces') renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = R.exposure;
const scene = new THREE.Scene();
const bg = S.background;
if (bg.type === 'gradient') {
  const cv = document.createElement('canvas'); cv.width = 4; cv.height = 256;
  const g = cv.getContext('2d'); const gr = g.createLinearGradient(0, 0, 0, 256);
  gr.addColorStop(0, bg.top || '#000000'); gr.addColorStop(1, bg.bottom || '#000000');
  g.fillStyle = gr; g.fillRect(0, 0, 4, 256);
  const tex = new THREE.CanvasTexture(cv); tex.colorSpace = THREE.SRGBColorSpace; scene.background = tex;
} else { scene.background = new THREE.Color(bg.color || '#000000'); }
const fog = S.fog;
if (fog.type === 'linear') scene.fog = new THREE.Fog(fog.color || '#ffffff', fog.near ?? 10, fog.far ?? 100);
else if (fog.type === 'exp2') scene.fog = new THREE.FogExp2(fog.color || '#ffffff', fog.density ?? 0.02);
for (const L of S.lights) {
  const c = L.color || '#ffffff', I = L.intensity ?? 1; let l;
  if (L.type === 'ambient') l = new THREE.AmbientLight(c, I);
  else if (L.type === 'hemisphere') l = new THREE.HemisphereLight(L.sky || c, L.ground || '#444444', I);
  else if (L.type === 'point') l = new THREE.PointLight(c, I, L.distance ?? 0, 2);
  else if (L.type === 'spot') l = new THREE.SpotLight(c, I, L.distance ?? 0, (L.angle_deg ?? 30) * DEG, 0.3, 2);
  else l = new THREE.DirectionalLight(c, I);
  if (L.position) l.position.set(...L.position);
  if (l.target && L.target) { l.target.position.set(...L.target); scene.add(l.target); }
  if (L.cast_shadow && l.shadow) { l.castShadow = true; l.shadow.mapSize.set(1024, 1024);
    if (l.shadow.camera.isOrthographicCamera) { const sc = l.shadow.camera; sc.left = -40; sc.right = 40; sc.top = 40; sc.bottom = -40; sc.near = 0.5; sc.far = 200; } }
  scene.add(l);
}
function material(m) {
  m = m || {}; const o = {color: m.color || '#cccccc'};
  if (m.flat_shading) o.flatShading = true; if (m.wireframe) o.wireframe = true;
  if (m.opacity !== undefined && m.opacity < 1) { o.transparent = true; o.opacity = m.opacity; }
  if (m.side === 'double') o.side = THREE.DoubleSide; else if (m.side === 'back') o.side = THREE.BackSide;
  const t = m.type || 'standard';
  if (t !== 'basic' && m.emissive) { o.emissive = m.emissive; o.emissiveIntensity = m.emissive_intensity ?? 1; }
  if (t === 'standard' || t === 'physical') { o.roughness = m.roughness ?? 0.8; o.metalness = m.metalness ?? 0.0; }
  if (t === 'basic') return new THREE.MeshBasicMaterial(o);
  if (t === 'lambert') { delete o.flatShading; return new THREE.MeshLambertMaterial(o); }
  if (t === 'phong') return new THREE.MeshPhongMaterial(o);
  if (t === 'toon') return new THREE.MeshToonMaterial(o);
  if (t === 'physical') return new THREE.MeshPhysicalMaterial(o);
  return new THREE.MeshStandardMaterial(o);
}
function geometry(type, p) {
  p = p || {};
  switch (type) {
    case 'box': return new THREE.BoxGeometry(p.width ?? 1, p.height ?? 1, p.depth ?? 1);
    case 'sphere': return new THREE.SphereGeometry(p.radius ?? 0.5, p.width_segments ?? 24, p.height_segments ?? 16);
    case 'cylinder': return new THREE.CylinderGeometry(p.radius_top ?? p.radius ?? 0.5, p.radius_bottom ?? p.radius ?? 0.5, p.height ?? 1, p.segments ?? 16);
    case 'cone': return new THREE.ConeGeometry(p.radius ?? 0.5, p.height ?? 1, p.segments ?? 16);
    case 'plane': return new THREE.PlaneGeometry(p.width ?? 1, p.height ?? 1);
    case 'circle': return new THREE.CircleGeometry(p.radius ?? 0.5, p.segments ?? 32);
    case 'ring': return new THREE.RingGeometry(p.inner ?? 0.3, p.outer ?? 0.5, p.segments ?? 32);
    case 'torus': return new THREE.TorusGeometry(p.radius ?? 0.5, p.tube ?? 0.15, p.radial_segments ?? 12, p.tubular_segments ?? 32);
    case 'icosahedron': return new THREE.IcosahedronGeometry(p.radius ?? 0.5, p.detail ?? 0);
    case 'dodecahedron': return new THREE.DodecahedronGeometry(p.radius ?? 0.5, p.detail ?? 0);
    case 'octahedron': return new THREE.OctahedronGeometry(p.radius ?? 0.5, p.detail ?? 0);
    case 'capsule': return new THREE.CapsuleGeometry(p.radius ?? 0.3, p.length ?? 1, 4, p.segments ?? 12);
  }
  throw new Error('unknown geometry ' + type);
}
const animated = [], waters = [], pending = [];
const loader = new GLTFLoader();
function setScale(obj, s) { if (Array.isArray(s)) obj.scale.set(...s); else if (s !== undefined) obj.scale.setScalar(s); }
function build(o, parent) {
  let node;
  if (o.type === 'group') node = new THREE.Group();
  else if (o.type === 'water') {
    const p = o.params || {}; const size = p.size ?? 200, seg = p.segments ?? 96;
    const g = new THREE.PlaneGeometry(size, size, seg, seg); g.rotateX(-Math.PI / 2);
    node = new THREE.Mesh(g, material(Object.assign({color: '#2a6f97', roughness: 0.35, metalness: 0.1, flat_shading: true}, o.material || {})));
    waters.push({mesh: node, base: Float32Array.from(g.attributes.position.array),
      waves: p.waves || [{amp: 0.18, kx: 0.35, kz: 0.2, speed: 1.2}, {amp: 0.1, kx: -0.15, kz: 0.5, speed: 1.7}]});
  } else if (o.type === 'points') {
    const p = o.params || {}; const n = p.count ?? 1000, r = rng((p.seed ?? S.seed) * 9973 + 17);
    const pos = new Float32Array(n * 3), rad = p.radius ?? 100, inner = p.inner_radius ?? 0;
    for (let i = 0; i < n; i++) { const u = r() * 2 - 1, th = r() * Math.PI * 2, s = Math.sqrt(1 - u * u);
      const d = inner + (rad - inner) * Math.cbrt(r());
      pos[i*3] = d * s * Math.cos(th); pos[i*3+1] = d * u; pos[i*3+2] = d * s * Math.sin(th); }
    const g = new THREE.BufferGeometry(); g.setAttribute('position', new THREE.BufferAttribute(pos, 3));
    node = new THREE.Points(g, new THREE.PointsMaterial({color: (o.material || {}).color || '#ffffff', size: p.size ?? 0.5, sizeAttenuation: true, fog: p.fog ?? true}));
  } else if (o.type === 'gltf') {
    node = new THREE.Group();
    pending.push(new Promise((res, rej) => loader.load(o.url, (gl) => {
      const m = gl.scene;
      if (o.fit_height) { const b = new THREE.Box3().setFromObject(m), sz = new THREE.Vector3(); b.getSize(sz);
        const k = o.fit_height / Math.max(sz.y, 1e-6); m.scale.setScalar(k);
        const b2 = new THREE.Box3().setFromObject(m), c = new THREE.Vector3(); b2.getCenter(c);
        m.position.set(-c.x, -b2.min.y, -c.z); }
      m.traverse(ch => { if (ch.isMesh) { ch.castShadow = o.cast_shadow ?? true; ch.receiveShadow = o.receive_shadow ?? true; } });
      node.add(m); res(); }, undefined, (e) => rej(new Error('gltf load failed ' + o.url + ': ' + (e && e.message))))));
  } else {
    node = new THREE.Mesh(geometry(o.type, o.params), material(o.material));
  }
  node.name = o.id;
  if (node.isMesh) { node.castShadow = o.cast_shadow ?? true; node.receiveShadow = o.receive_shadow ?? (o.type === 'water' || o.type === 'plane'); }
  if (o.position) node.position.set(...o.position);
  if (o.rotation) node.rotation.set(o.rotation[0] * DEG, o.rotation[1] * DEG, o.rotation[2] * DEG);
  setScale(node, o.scale);
  if (o.anim) animated.push({node, a: o.anim, p0: node.position.clone(), r0: node.rotation.clone(), s0: node.scale.clone()});
  parent.add(node);
  for (const c of (o.children || [])) build(c, node);
}
for (const o of S.objects) build(o, scene);
function kf(keys, t, field) {
  const ks = keys.filter(k => k[field] !== undefined); if (!ks.length) return null;
  const v = k => Array.isArray(k[field]) ? k[field] : [k[field], k[field], k[field]];
  if (t <= ks[0].t) return v(ks[0]); if (t >= ks[ks.length-1].t) return v(ks[ks.length-1]);
  for (let i = 0; i < ks.length - 1; i++) { const a = ks[i], b = ks[i+1];
    if (t >= a.t && t <= b.t) { const s = (t - a.t) / Math.max(b.t - a.t, 1e-9), A = v(a), B = v(b);
      return [0,1,2].map(j => A[j] + (B[j] - A[j]) * s); } }
  return null;
}
function animate(t) {
  for (const w of waters) { const arr = w.mesh.geometry.attributes.position.array;
    for (let i = 0; i < arr.length; i += 3) { const x = w.base[i], z = w.base[i+2]; let y = 0;
      for (const k of w.waves) y += k.amp * Math.sin(k.kx * x + k.kz * z + k.speed * t);
      arr[i+1] = y; }
    w.mesh.geometry.attributes.position.needsUpdate = true; w.mesh.geometry.computeVertexNormals(); }
  for (const e of animated) { const {node, a} = e;
    node.position.copy(e.p0); node.rotation.copy(e.r0); node.scale.copy(e.s0);
    if (a.keyframes) { const p = kf(a.keyframes, t, 'position'), r = kf(a.keyframes, t, 'rotation'), s = kf(a.keyframes, t, 'scale');
      if (p) node.position.set(...p); if (r) node.rotation.set(r[0]*DEG, r[1]*DEG, r[2]*DEG); if (s) node.scale.set(...s); }
    if (a.bob) node.position.y += (a.bob.amp ?? 0.1) * Math.sin(2 * Math.PI * (a.bob.freq ?? 0.5) * t + (a.bob.phase ?? 0));
    if (a.rock) node.rotation[a.rock.axis || 'z'] += (a.rock.amp_deg ?? 4) * DEG * Math.sin(2 * Math.PI * (a.rock.freq ?? 0.4) * t + (a.rock.phase ?? 0));
    if (a.spin) node.rotation[a.spin.axis || 'y'] += (a.spin.speed_deg ?? 10) * DEG * t; }
}
const C = S.camera;
const cam = new THREE.PerspectiveCamera(C.fov, S.width / S.height, C.near, C.far);
window.__setFrame = (i, t) => {
  const k = CAM[Math.min(i, CAM.length - 1)];
  animate(t);
  cam.position.set(...k.pos); cam.up.set(0, 1, 0); cam.lookAt(new THREE.Vector3(...k.look));
  if (k.roll_deg) cam.rotateZ(k.roll_deg * DEG);
  if (cam.fov !== k.fov) { cam.fov = k.fov; cam.updateProjectionMatrix(); }
  renderer.render(scene, cam);
  return renderer.info.render.triangles;
};
window.__objectNames = () => { const n = []; scene.traverse(o => { if (o.name) n.push(o.name); }); return n; };
Promise.all(pending).then(() => { window.__setFrame(0, 0); window.__READY = true; })
  .catch(e => { window.__ERROR = String(e && e.message || e); window.__READY = true; });
} catch (e) { window.__ERROR = String(e && e.stack || e); window.__READY = true; }
</script></body></html>
"""


def build_html(scene: dict[str, Any], camera_frames: list[dict[str, Any]]) -> str:
    """``scene`` must be normalised and GLTF objects must carry a page-relative ``url``."""
    page_scene = {k: v for k, v in scene.items() if k != "prompt_report"}
    dump = lambda o: json.dumps(o, ensure_ascii=False, sort_keys=True).replace("</", "<\\/")
    return _PAGE.replace("/*SCENE*/null", dump(page_scene)).replace("/*CAMERA*/null", dump(camera_frames))
