// 25_ghibli 纹理底：整屏水彩晕染（暖米黄纸底 + 大幅变形的透明色晕 + 纸纹颗粒），不含任何叙事元素。
// r6 B1/非阻断：ground 建得比画面大（带边距），每帧从里面裁一块 —— 取代原来的 2×2 平铺（横屏平铺接缝一并消除）；
// 纹理显式按 ground 尺寸建，boot 时断言全不透明。
SCENES['25_ghibli'] = (() => {
  const W = 1920, H = 1080, { rng } = U, P = PAINT;
  const wash = P.watercolor, rect = P.rectPts, ellipsePts = P.ellipsePts;
  const M = 220, GW = W + 2 * M, GH = H + 2 * M;
  const PAPER = '#fbf6ea';

  const ground = () => P.cached('gh_tex_bg_v2', GW, GH, (g) => {
    // 暖米黄纸底 + 亮心暗角渐变洗染（整屏，无边界）
    g.drawImage(P.texture('gh_tex_paper', PAPER, { scale: 0.02, amt: 6, grain: 10, seed: 3, w: GW, h: GH }), 0, 0);
    const wl = g.createRadialGradient(GW * 0.3, GH * 0.3, 100, GW / 2, GH / 2, 1600);
    wl.addColorStop(0, '#fbf3e0'); wl.addColorStop(0.6, '#f1e1bf'); wl.addColorStop(1, '#dcc49a');
    wash(g, rect(-20, -20, GW + 40, GH + 40), '#efdcb4', { layers: 5, alpha: 0.4, amp: 12, seed: 2, edge: 0, fill: wl });
    // 60 块水彩色晕（暖黄/赭石/粉/蓝灰/浅绿交替）——整屏均匀铺，不构成任何具象形状。
    const r = rng(404), tints = ['#e0a860', '#c98a6a', '#8fa8c4', '#e8c274', '#b98a52', '#9fb89a'];
    for (let i = 0; i < 60; i++) {
      const x = r() * GW, y = r() * GH, rx = 110 + r() * 250, ry = 80 + r() * 190;
      wash(g, ellipsePts(x, y, rx, ry, 10), tints[i % tints.length], { layers: 3, alpha: 0.12, amp: 40, seed: 100 + i, edge: 0.28 });
    }
    // 纸纹颗粒（颜料在纸凹处沉积）
    g.save(); g.globalCompositeOperation = 'multiply'; g.globalAlpha = 0.3;
    g.drawImage(P.texture('gh_tex_gran', '#f4efe2', { scale: 0.06, amt: 18, grain: 26, seed: 9, w: GW, h: GH }), 0, 0);
    g.restore();
    P.assertOpaque(g.canvas, '25_ghibli/ground');
  });

  return {
    bg: PAPER,
    draw(c, lt, t) {
      const sx = M + Math.sin(t * 0.36) * (M * 0.8), sy = M + Math.sin(t * 0.27 + 0.7) * (M * 0.8);
      c.drawImage(ground(), sx, sy, W, H, 0, 0, W, H);
      // 一层暖色柔光（整屏，无方向性光源的具象暗示），缓慢呼吸
      c.save(); c.globalCompositeOperation = 'screen';
      const a = 0.12 + 0.03 * Math.sin(t * 0.5);
      const lg = c.createRadialGradient(W / 2, H / 2, 120, W / 2, H / 2, 1150);
      lg.addColorStop(0, `rgba(255,240,200,${a})`); lg.addColorStop(1, 'rgba(255,240,200,0)');
      c.fillStyle = lg; c.fillRect(0, 0, W, H); c.restore();
    },
  };
})();
