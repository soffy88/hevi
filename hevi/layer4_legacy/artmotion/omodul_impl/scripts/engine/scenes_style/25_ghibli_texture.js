// 25_ghibli 纹理底：整屏水彩晕染（暖米黄纸底 + 大幅变形的透明色晕 + 纸纹颗粒）。
// 只做「全屏均匀底纹」，不含任何叙事元素（无窗、无家具、无窗帘、无植物、无人物/动物）。
SCENES['25_ghibli'] = (() => {
  const W = 1920, H = 1080, { rng } = U, P = PAINT;
  const wash = P.watercolor, rect = P.rectPts, ellipsePts = P.ellipsePts;

  const ground = () => P.cached('gh_tex_bg', W, H, (g) => {
    // 暖米黄纸底 + 亮心暗角渐变洗染（整屏，无边界）
    g.drawImage(P.texture('gh_tex_paper', '#fbf6ea', { scale: 0.02, amt: 6, grain: 10, seed: 3 }), 0, 0);
    const wl = g.createRadialGradient(580, 340, 100, W / 2, H / 2, 1500);
    wl.addColorStop(0, '#fbf3e0'); wl.addColorStop(0.6, '#f1e1bf'); wl.addColorStop(1, '#dcc49a');
    wash(g, rect(-20, -20, W + 40, H + 40), '#efdcb4', { layers: 5, alpha: 0.4, amp: 12, seed: 2, edge: 0, fill: wl });
    // 48 块水彩色晕（暖黄/赭石/粉/蓝灰/浅绿交替）——整屏均匀铺，不构成任何具象形状。
    // 提高对比度与边缘（更深的赭石/蓝灰、alpha 0.12、edge 0.28 的深色水痕边）：
    // 相机推近/横移时才有可测的画面变化（film_gate 快动门禁）。
    const r = rng(404), tints = ['#e0a860', '#c98a6a', '#8fa8c4', '#e8c274', '#b98a52', '#9fb89a'];
    for (let i = 0; i < 48; i++) {
      const x = r() * W, y = r() * H, rx = 110 + r() * 250, ry = 80 + r() * 190;
      wash(g, ellipsePts(x, y, rx, ry, 10), tints[i % tints.length], { layers: 3, alpha: 0.12, amp: 40, seed: 100 + i, edge: 0.28 });
    }
    // 纸纹颗粒（颜料在纸凹处沉积）
    g.save(); g.globalCompositeOperation = 'multiply'; g.globalAlpha = 0.3;
    g.drawImage(P.texture('gh_tex_gran', '#f4efe2', { scale: 0.06, amt: 18, grain: 26, seed: 9 }), 0, 0);
    g.restore();
  });

  const frame = () => P.cached('gh_tex_frame', W, H, () => {});

  return {
    draw(c, lt, t) {
      const L = frame(), g = L.getContext('2d');
      g.setTransform(1, 0, 0, 1, 0, 0); g.clearRect(0, 0, W, H);
      // 底纹整体按时间缓慢漂移（水彩在纸上洇开的连续感），2×2 平铺防露边；
      // 相机（clip.js 的 CAM.apply）再在其上叠加推拉/横移——两条合起来保证每帧都有真实变化。
      const sx = t * 150, sy = t * 95;
      g.save();
      g.translate(-(sx % W), -(sy % H));
      g.drawImage(ground(), 0, 0); g.drawImage(ground(), W, 0);
      g.drawImage(ground(), 0, H); g.drawImage(ground(), W, H);
      g.restore();
      c.drawImage(L, 0, 0);
      // 一层暖色柔光（整屏，无方向性光源的具象暗示），缓慢呼吸
      c.save(); c.globalCompositeOperation = 'screen';
      const a = 0.12 + 0.03 * Math.sin(t * 0.5);
      const lg = c.createRadialGradient(W / 2, H / 2, 120, W / 2, H / 2, 1150);
      lg.addColorStop(0, `rgba(255,240,200,${a})`); lg.addColorStop(1, 'rgba(255,240,200,0)');
      c.fillStyle = lg; c.fillRect(0, 0, W, H); c.restore();
    },
  };
})();
