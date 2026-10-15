// 参数化片段运行时：一份 spec（JSON）→ 一段时长严格等于 spec.duration 的动画。给口播视频管线当「动画段」用。
// 契约见 references/09-视频动画语法.md「片段契约」。和 engine.js 的区别：没有段落表/转场，一个语法一个 draw(c, t, ctx)，画布尺寸从 spec 读（竖屏也行）。
//
// spec = { grammar, duration, fps=30, width=1920, height=1080, safe?: {top,bottom,left,right（px，留给字幕/平台 UI）, fill?（让开的边涂这个色）}, theme?, alpha?, data?, cues: [{at, kind, text?, sub?, data?, image?, frames?, fps?, dur?}] }
// spec.theme：全片共用的色板（lib/palettes.js）——名字（paper poster ink navy bauhaus snow wood chalk）、{name, 要覆盖的键}、或完整 6 键 {bg, surface, ink, sub, accent, accent2}。
//   解析成 ctx.pal（完整 6 键＋name），各语法按它上色；名字写错 / 缺键 → 启动失败。不写 → ctx.pal = null，各语法用自己的默认配色。
//   语法可以声明 legacyTheme(theme) → true：这个 theme 是它自己的旧写法（t3 的 'light' / 'dark' / 旧主题对象），不当色板解析，语法照旧读 ctx.theme。
// 素材路径（render.py 用 spec_assets.py 核存在并改写）：cue.image、cue.frames（帧序列：目录或路径数组）、data.image、data.character.frames（y4 帧库）。
// 任何一张加载失败 → 启动失败、拒绝渲染（不出空白帧）。语法里取素材：ctx.still(q) = 这条 cue 的静态图（有 frames 时是第一帧），ctx.frame(q, t) = t 时刻该画的那一帧。
// 语法文件 clips/<grammar>.js 注册 CLIPS[grammar] = { init?(ctx), draw(c, t, ctx), safe?: true（按 ctx.safe / ctx.box 排版了才写，否则 spec.safe 会告警） }。
// 对齐约定（CLIP.lt）：cue 的「揭开那一帧」= at 所在的那一帧——元素在 t = at 这一帧第一次可见，动画内部时间从 at − 1 帧起算。
(() => {
const cv = document.getElementById('c'); let c = cv.getContext('2d');   // let：8bit 像素化时临时切到低分辨率缓冲
window.__canvas = cv;
window.CLIPS = window.CLIPS || {};
const C = window.CLIP = {};
const fail = msg => { window.__bootFailed = msg; console.error('CLIP BOOT FAILED\n' + msg); };

// ---------- 给语法文件用的小工具 ----------
// 片内时间：cue 在 at 这一帧第一次可见
C.lt = (t, at, fps) => t - at + 1 / fps;
// 进度：从 at 起 dur 秒走完 0→1（at 这一帧已经 >0）
C.p = (t, at, dur, fps) => U.clamp(C.lt(t, at, fps) / dur);
// 等比放进框里（contain，不裁）：返回 {x, y, w, h}
C.fit = (iw, ih, bx, by, bw, bh) => { const s = Math.min(bw / iw, bh / ih); const w = iw * s, h = ih * s; return { x: bx + (bw - w) / 2, y: by + (bh - h) / 2, w, h, s }; };
// 归一化矩形 [x,y,w,h]（0..1，相对图片）→ 画面矩形
C.sub = (r, box) => ({ x: box.x + r[0] * box.w, y: box.y + r[1] * box.h, w: r[2] * box.w, h: r[3] * box.h });
C.text = (cue, ...fallback) => (cue && (cue.text ?? cue.data?.text)) ?? fallback.find(v => v != null) ?? '';

async function boot() {
  let spec = window.CLIP_SPEC;
  if (!spec) {                                                           // 预览：?spec=<相对 engine 的路径>
    const u = new URLSearchParams(location.search).get('spec');
    if (!u) return fail('没有 spec：render.py --spec 会注入 window.CLIP_SPEC；预览用 clip.html?spec=examples/<名>.json');
    spec = await (await fetch(u)).json();
    const base = u.replace(/[^/]*$/, '');
    const fix = p => p && !/^(data:|https?:|\/)/.test(p) ? base + p : p;   // 预览模式：frames 要写成路径数组（浏览器列不了目录），帧库要写 {frames: {姿势: 路径}}
    (spec.cues || []).forEach(q => { if (q.image) q.image = fix(q.image); if (Array.isArray(q.frames)) q.frames = q.frames.map(fix); });
    if (spec.data && spec.data.image) spec.data.image = fix(spec.data.image);
    const ch = spec.data && spec.data.character; if (ch && typeof ch === 'object' && ch.frames && typeof ch.frames === 'object') for (const k in ch.frames) ch.frames[k] = fix(ch.frames[k]);
  }
  if (location.search.includes('render=1')) document.body.classList.add('render');
  const W = spec.width || 1920, H = spec.height || 1080, FPS = spec.fps || 30;
  if (!spec.grammar) return fail('spec 缺 grammar');
  if (!(spec.duration > 0)) return fail('spec.duration 必须 > 0');
  cv.width = W; cv.height = H; U.setStage(W, H);
  // 语法文件（同步 XHR + eval，带 sourceURL，报错能定位）
  const x = new XMLHttpRequest(); x.open('GET', `clips/${spec.grammar}.js`, false);
  try { x.send(); } catch (e) { return fail('请求语法文件失败 ' + e); }
  if (x.status !== 200) return fail(`没有这个语法：clips/${spec.grammar}.js（HTTP ${x.status}）`);
  try { (0, eval)(x.responseText + `\n//# sourceURL=clips/${spec.grammar}.js`); } catch (e) { return fail(`clips/${spec.grammar}.js 执行出错 ${e.stack || e}`); }
  const G = CLIPS[spec.grammar]; if (!G || typeof G.draw !== 'function') return fail(`clips/${spec.grammar}.js 没注册 CLIPS['${spec.grammar}'] = { draw }`);
  // 风格场景（同步 XHR + eval）
  window.SCENES = window.SCENES || {};
  let styleScene = null;
  const styleId = spec.style || spec.style_id;
  // 纹理模式：仅加载背景纹理，不画人物/动物（避免叙事元素覆盖内容层）
  const textureMode = spec.texture_mode || ['17_ink', '25_ghibli', '14_8bit', '12_bauhaus'].includes(styleId);
  if (styleId) {
    const scenePath = textureMode ? `scenes_style/${styleId}_texture.js` : `scenes/${styleId}.js`;
    const sx = new XMLHttpRequest(); sx.open('GET', scenePath, false);
    try { sx.send(); } catch (e) { return fail(`请求风格场景失败 ${scenePath}: ` + e); }
    if (sx.status !== 200) return fail(`没有这个风格场景：${scenePath}（HTTP ${sx.status}）`);
    try { (0, eval)(sx.responseText + `\n//# sourceURL=${scenePath}`); } catch (e) { return fail(`${scenePath} 执行出错 ${e.stack || e}`); }
    styleScene = window.SCENES[styleId];
    if (!styleScene || typeof styleScene.draw !== 'function') return fail(`${scenePath} 没注册 SCENES['${styleId}'] = { draw }`);
    // 纹理模式下不显示标签
    if (textureMode) spec.show_style_label = false;
  }
  // 主题色板：在加载素材之前核，写错就别白等图片
  let pal = null;
  if (!(G.legacyTheme && G.legacyTheme(spec.theme))) { try { pal = PAL.resolve(spec.theme); } catch (e) { return fail(e.message); } }
  // 图片
  const IMG = {}, urls = new Set();
  for (const q of (spec.cues || [])) {
    if (q.image) urls.add(q.image);
    if (q.frames != null) { if (!Array.isArray(q.frames) || !q.frames.length) return fail(`cue ${q.kind} at=${q.at} 的 frames 要是非空的路径数组（render.py 会把目录展开成数组；预览模式只认数组）`); q.frames.forEach(f => urls.add(f)); }
  }
  if (spec.data && spec.data.image) urls.add(spec.data.image);
  const chr = spec.data && spec.data.character;
  if (chr && typeof chr === 'object') { if (!chr.frames || typeof chr.frames !== 'object' || Array.isArray(chr.frames)) return fail('data.character 写成对象时要有 frames: {姿势名: 图片路径}（或在 render.py 里给一个帧库目录）');
    Object.values(chr.frames).forEach(f => urls.add(f)); }
  try { await Promise.all([...urls].map(u => new Promise((res, rej) => { const im = new Image(); im.onload = () => { IMG[u] = im; res(); }; im.onerror = () => rej(u); im.src = u; }))); }
  catch (u) { return fail('图片加载失败：' + u); }
  // 字体＋字形检查（spec 里的字缺字形只警告：回退系统字体照样能渲，但换台机器会变样）
  for (const f of (window.FONT_FACES || [])) { const ff = new FontFace(f.family, `url(${f.url})`, f.desc || {}); await ff.load(); document.fonts.add(ff); }
  await document.fonts.ready; await U.loadCmaps();
  const cues0 = (spec.cues || []).map((q, i) => ({ ...q, i, at: +q.at || 0 })).sort((a, b) => a.at - b.at || a.i - b.i);
  for (const q of cues0) if (q.at > spec.duration + 1e-9) console.warn(`cue ${q.kind} at=${q.at} 超出片段时长 ${spec.duration}s，看不到，已丢掉（不占版面）`);
  const cues = cues0.filter(q => q.at <= spec.duration + 1e-9);   // 看不到的 cue 不进语法：否则照样占排版位置、进度轨照样数它
  // number 的说明字段各语法以前各认各的（t2/t3 认 text，y5 认 sub），写错了不报错只是没字。统一：text 与 sub 互为别名，data.text 也算
  for (const q of cues) if (q.kind === 'number') { const cap = q.text ?? q.sub ?? (q.data && q.data.text); if (cap != null) { q.text = cap; q.sub = cap; } }
  const safe = { top: 0, bottom: 0, left: 0, right: 0, ...(spec.safe || {}) };   // 让开的边（px）：管线烧录字幕、平台 UI 压在这里，带字的语法不往里排
  const box = { x: safe.left, y: safe.top, w: W - safe.left - safe.right, h: H - safe.top - safe.bottom };   // 让开之后的内容框，语法排版用它（ctx.box）
  const ctx = { spec, data: spec.data || {}, theme: spec.theme || {}, pal, cues, W, H, FPS, u: Math.min(W, H) / 1080, portrait: H > W, alpha: !!spec.alpha || !!styleScene, hasStyle: !!styleScene, style: styleId || null, IMG, dur: spec.duration, safe, box,
    of: (...kinds) => cues.filter(q => kinds.includes(q.kind)), lt: (t, at) => C.lt(t, at, FPS), p: (t, at, d) => C.p(t, at, d, FPS),
    // 素材：still = 定版式用的那张（image，或 frames 的第一帧）；frame = t 时刻画哪一帧（frames 从 at 起按 q.fps（默认 30）播，播完停在最后一帧，q.loop 循环）
    still: q => q && (q.image ? IMG[q.image] : q.frames ? IMG[q.frames[0]] : null),
    frame: (q, t) => !q ? null : q.frames ? MD.frameAt(q.frames.map(f => IMG[f]), t - q.at, q.fps || 30, !!q.loop) : q.image ? IMG[q.image] : null };
  if (G.fonts) { const txt = cues.map(q => [q.text, q.sub, q.data && q.data.text].filter(Boolean).join('')).join('') + JSON.stringify(spec.data || {});
    for (const fam of G.fonts) { const miss = U.missingGlyphs(fam, [...txt].filter(ch => ch.codePointAt(0) >= 0x2E80).join(''));   /* 只查汉字与全角符号：拉丁/希腊/数学符号各语法另有字体 */ if (miss.length) console.warn(`字体「${fam}」缺字：${miss.join('')}（会回退系统字体；常用字已在 GB2312 子集里，生僻字用 scripts/font_subset.py --text 补）`); } }
  if (spec.safe && (safe.top || safe.bottom || safe.left || safe.right) && !G.safe)
    console.warn(`语法 ${spec.grammar} 还没接 safe（语法对象里没有 safe: true），spec.safe 被忽略：字幕带可能压在字上`);
  if (G.init) G.init(ctx);
  window.CLIP_CTX = ctx;
  window.__total = spec.duration; window.__fps = FPS; window.__size = [W, H];
  // safe.fill：让开的边涂成这个颜色（竖屏片把图表做成和相邻 contain 素材同一块「卡片」，外面是片子的底色）；透明模式下不涂
  const band = (safe.fill && !spec.alpha && !styleScene) ? (cc => { cc.fillStyle = safe.fill; const { top: t0, bottom: b0, left: l0, right: r0 } = safe;
    if (t0) cc.fillRect(0, 0, W, t0); if (b0) cc.fillRect(0, H - b0, W, b0); if (l0) cc.fillRect(0, 0, l0, H); if (r0) cc.fillRect(W - r0, 0, r0, H); }) : null;

  // ---- 镜头动作表：动在事件上（停住 → 快推 / 横移 / 砸入 → 停住）----
  // 事件点 = cue 的落点（at）；口播节点之间空太久就在空档补一个，事件之间至少留 1.15 秒「停住」。
  // 每一步都是绝对机位（不是相对增量），所以镜头不会一路推到底；快推用 quintOut——速度前置，
  // 0.5 秒里前两帧就走完大半段位移，这是「猛动作」而不是匀速慢推（film_gate 的快动门禁量的是前者）。
  const CAM_EVENTS = (() => {
    const dur = spec.duration || 10, u = ctx.u, out = [];
    const KINDS = ['punch', 'punch', 'pan', 'punch', 'slam', 'punch', 'pan'];
    const push = at => {
      if (!(at > 0.30) || at > dur - 0.40) return;
      if (out.length && at - out[out.length - 1].at < 1.15) return;
      const i = out.length, k = KINDS[i % KINDS.length], dir = i % 2 ? 1 : -1;
      if (k === 'slam') out.push({ at, kind: 'slam', dur: 0.5, from: 1.42 });
      else if (k === 'pan') out.push({ at, kind: 'to', x: W / 2 + dir * 350 * u, y: H / 2 - dir * 100 * u, z: 1.35, dur: 0.5, ease: MO.quintOut });
      else out.push({ at, kind: 'to', x: W / 2 + dir * 140 * u, y: H / 2 + dir * 80 * u, z: 1.85, dur: 0.5, ease: MO.quintOut });
    };
    (spec.cues || []).forEach(q => push(+q.at || 0));
    // 空档补刀：每 0.8 秒一个镜头动作，保证整片都有足够的快动帧
    for (let at = 0.8, k = 0; at < dur - 0.6; at += 0.8, k++) {
      if (out.some(e => Math.abs(e.at - at) < 1.0)) continue;
      const dir = k % 2 ? 1 : -1;
      out.push({ at, kind: 'to', x: W / 2 + dir * (180 + (k % 4) * 120) * u, y: H / 2 - dir * (100 + (k % 3) * 60) * u, z: 1.6 + (k % 4) * 0.2, dur: 0.5, ease: MO.quintOut });
    }
    return out.sort((a, b) => a.at - b.at);
  })();
  // 持续微漂：事件之间的「空档」里也让画面每帧都在动，保证 film_gate 全片不报黄灯
  // 两路不同频率的正弦（漂移）+ 缓慢呼吸缩放（z 在 1.0–1.08 之间波动），保证每帧都有真实变化
  const DRIFT_SEED = 7;
  const driftVec = t => [
    22 * Math.sin(t * 0.7 + DRIFT_SEED) + 8 * Math.sin(t * 1.9 + DRIFT_SEED * 2.3),
    18 * Math.sin(t * 0.5 + DRIFT_SEED * 1.7) + 6 * Math.sin(t * 2.1 + DRIFT_SEED * 3.1),
  ];
  // ---- 文字层与相机解耦（r5 B3）：镜头推拉/横移不得把文字推出画面 ----
  // 风格底（全屏纹理）吃相机运动；语法层（公式、图表、文字）**不随相机运动**，永远按它自己的
  // safe 区排版，落定后就不动——这样相机再怎么推/移都推不出文字。
  // 每帧把语法层画出来的所有字框（fillText/strokeText 的屏幕包围盒）记进 ctx.__textBBox，
  // 供 produce/film_gate 的越界检查读取（≥2fps 逐帧）。低透明度（<0.3，如 y5 背景巨型序号）不算，
  // 那是装饰字不是正文。
  let acc = null, dcCanvas = null, dcT = null;
  // 语法层量化倍率（r6 B2）：8bit 风格里底纹照旧 1/8 像素化，但语法层（柱/线/字）单独进 1/2 缓冲——
  // 文字像素化倍率 ≤2，数字才读得清（r5 把整帧 1/8 量化，CJK 文字被毁成不可读的方块）。
  const PIX = styleId === '14_8bit' ? 2 : 1;
  const base = PIX > 1 ? [1 / PIX, 0, 0, 1 / PIX, 0, 0] : [1, 0, 0, 1, 0, 0];
  const pf = PIX;
  const fontSize = cc => { const m = /([\d.]+)px/.exec(cc.font || ''); return m ? parseFloat(m[1]) : 32; };
  const mul = (A, B) => ({ a: A.a * B.a + A.c * B.b, b: A.b * B.a + A.d * B.b, c: A.a * B.c + A.c * B.d, d: A.b * B.c + A.d * B.d, e: A.a * B.e + A.c * B.f + A.e, f: A.b * B.e + A.d * B.f + A.f });
  // 字框最终落在屏幕的哪里（真实像素坐标）：语法画在语法画布（dc）上就直接用它的变换；画到离屏缓冲
  // （如 alpha 模式的 BUF）上，BUF 之后会被贴回语法画布，所以先乘语法画布的变换再乘像素化倍率。
  // 之前的实现只取画布自身的 getTransform（离屏缓冲是单位阵），把相机变换整个漏掉，越界检查因此形同虚设。
  ctx.__textHit = (s, x, y, align, tbase, cc) => {
    if (!s) return;
    const sz = fontSize(cc), w = cc.measureText(String(s)).width;
    const x0 = align === 'center' ? x - w / 2 : align === 'right' ? x - w : x;
    const yBase = tbase === 'top' ? y + sz : tbase === 'middle' ? y + sz / 2 : y;   // 基线（默认 alphabetic）
    const loc = cc.getTransform();
    const M = (cc.canvas === dcCanvas || !dcT) ? loc : mul(dcT, loc);
    if (!acc) acc = { x0: Infinity, y0: Infinity, x1: -Infinity, y1: -Infinity };
    for (const [px, py] of [[x0, yBase - sz * 1.16], [x0 + w, yBase - sz * 1.16], [x0, yBase], [x0 + w, yBase]]) {
      const sx = pf * (M.a * px + M.c * py + M.e), sy = pf * (M.b * px + M.d * py + M.f);
      acc.x0 = Math.min(acc.x0, sx); acc.y0 = Math.min(acc.y0, sy); acc.x1 = Math.max(acc.x1, sx); acc.y1 = Math.max(acc.y1, sy);
    }
  };
  ctx.__bboxCommit = () => { ctx.__textBBox = acc ? { x0: acc.x0, y0: acc.y0, x1: acc.x1, y1: acc.y1 } : null; acc = null; };
  // 量字：临时挂上 CanvasRenderingContext2D.prototype 的 fillText/strokeText（主画布与 alpha 缓冲都覆盖）
  const trackText = fn => {
    const proto = CanvasRenderingContext2D.prototype, of = proto.fillText, os = proto.strokeText;
    proto.fillText = function (s, x, y, ...r) { if (this.globalAlpha >= 0.3) ctx.__textHit(s, x, y, this.textAlign, this.textBaseline, this); return of.call(this, s, x, y, ...r); };
    proto.strokeText = function (s, x, y, ...r) { if (this.globalAlpha >= 0.3) ctx.__textHit(s, x, y, this.textAlign, this.textBaseline, this); return os.call(this, s, x, y, ...r); };
    try { fn(); } finally { proto.fillText = of; proto.strokeText = os; }
  };
  const camFn = t => {
    const base = CAM.track({ x: W / 2, y: H / 2, z: 1 }, CAM_EVENTS, t);
    const [dx, dy] = driftVec(t);
    // 缓慢呼吸缩放：z 在 1.0–1.08 之间波动，确保相邻帧缩放差 > 0.5%
    const breath = 1.0 + 0.04 * (1 - Math.cos(2 * Math.PI * t / 8));
    return { x: base.x + dx, y: base.y + dy, z: base.z * breath, moving: true };
  };
  // 风格画面按 cover 铺满并留 30% 余量：镜头推到 1.85 也不会露出画面边界
  const SCENE_W = 1920, SCENE_H = 1080, SCENE_SCALE = Math.max(W / SCENE_W, H / SCENE_H) * 1.30;
  // 语法层相机（r5 B3）：整页文字版式（G.fixed，如 y5）**不挂相机**——文字层不随镜头推拉/横移，
  // 永远按 safe 区排版，运动由换页色带提供；其余语法（图表/公式，如 t1/t3）跟相机（内容随之移动，
  // film_gate 才有可测的快动）。两条路都由逐帧越界检查兜底：越界即红灯。
  const camG = t => (G.fixed ? { x: W / 2, y: H / 2, z: 1, moving: true } : camFn(t));
  // 8bit 像素化后处理（r6 B2）：底纹 1/8 量化（像素风），语法层 1/2 量化（文字可读）。两层分别合成。
  const PIXELATE = styleId === '14_8bit';
  // 风格底：吃相机运动（全屏纹理推/移，提供片子的运动感）。画进当前 c（像素化时是 1/8 缓冲）。
  const drawBg = t => {
    c.save();
    CAM.apply(c, camFn(t));
    if (styleScene && typeof styleScene.draw === 'function') {
      c.save();
      c.translate((W - SCENE_W * SCENE_SCALE) / 2, (H - SCENE_H * SCENE_SCALE) / 2);
      c.scale(SCENE_SCALE, SCENE_SCALE);
      styleScene.draw(c, t, t);
      if (typeof styleScene.label === 'function' && spec.show_style_label !== false) styleScene.label(c, t);
      c.restore();
    }
    c.restore();
  };
  // 语法层：跟随小幅相机（camG）；回到 base 变换（像素化时 1/2 缩放，语法仍按舞台坐标排版），
  // 画的时候记字框（字框含相机变换）。测出的字框按 pf 换算回舞台像素，越界检查用真实画幅。
  const drawGrammar = t => {
    c.setTransform(...base);
    acc = null;
    c.save(); CAM.apply(c, camG(t));
    dcCanvas = c; dcT = c.getTransform();   // 语法画布此刻的变换（base＋相机）：离屏缓冲贴回时用它换算屏幕坐标
    trackText(() => G.draw(c, t, ctx));
    c.restore(); ctx.__bboxCommit();
    c.setTransform(...base);
  };

  window.renderFrame = t => {
    c.setTransform(1, 0, 0, 1, 0, 0);
    c.clearRect(0, 0, W, H);
    // r6 B1：渲染前先铺一层不透明纸色兜底。风格底若因任何原因没盖满（纹理建错尺寸、场景异常），
    // 也不会漏成黑底；纹理场景的 ground() 另有 alpha=255 断言。alpha 模式（透明出片）不铺。
    if (styleScene && styleScene.bg && !spec.alpha) { c.fillStyle = styleScene.bg; c.fillRect(0, 0, W, H); }
    if (PIXELATE) {
      // 1) 风格底：1/8 缓冲量化（像素风底纹）
      const L8 = PAINT.lowres, g8 = L8.getContext('2d');
      g8.setTransform(1, 0, 0, 1, 0, 0); g8.clearRect(0, 0, L8.width, L8.height);
      g8.save(); g8.scale(1 / 8, 1 / 8);
      const real8 = c; c = g8;
      try { drawBg(t); } finally { c = real8; }
      g8.restore();
      c.imageSmoothingEnabled = false;
      c.drawImage(L8, 0, 0, L8.width, L8.height, 0, 0, W, H);
      // 2) 语法层：1/2 缓冲量化（柱/线/字像素化 ≤2，数字可读）
      const L2 = PAINT.lowres2, g2 = L2.getContext('2d');
      g2.setTransform(1, 0, 0, 1, 0, 0); g2.clearRect(0, 0, L2.width, L2.height);
      const real2 = c; c = g2;
      try { drawGrammar(t); } finally { c = real2; }
      c.imageSmoothingEnabled = false;
      c.drawImage(L2, 0, 0, L2.width, L2.height, 0, 0, W, H);
      c.imageSmoothingEnabled = true;
    } else {
      drawBg(t);
      drawGrammar(t);
    }
    c.setTransform(1, 0, 0, 1, 0, 0);
    if (band) band(c);
  };
  window.prepare = async () => {};
  window.__ready = true;
  window.renderFrame(0);
  const sc = document.getElementById('scrub'), tt = document.getElementById('tt'); sc.max = spec.duration; sc.step = 1 / FPS;
  sc.oninput = () => { window.renderFrame(+sc.value); tt.textContent = (+sc.value).toFixed(3); };
}
boot().catch(e => fail(String(e && e.stack || e)));
})();
