// 17_ink 纹理底：整屏宣纸（暖米黄纸 + 噪声斑驳 + 极淡墨色斑 + 径向暗角），不含任何叙事元素。
// r6 B1 修复（根因）：原来 ground() 是 1920×1080 缓存画布，但 P.texture/P.grain 按「舞台尺寸」建图；
// 竖屏舞台是 1080×1920，于是宣纸只盖住左 1080px，右侧 840px 透明，成片丢 alpha 后就是「黑底 + 灰色弧线」。
// 现在：纹理一律显式按 1920×1080 建（P.texture/P.grain 传 w/h）；ground() 建得比画面大（带边距），
// 每帧从里面裁一块，永不露边、也就不用 2×2 平铺（横屏平铺接缝一并消除）；boot 时断言 ground 全不透明。
SCENES['17_ink'] = (() => {
  const W = 1920, H = 1080, { rng } = U, P = PAINT;
  const M = 200;                                   // 边距：ground 比画面大 2M，漂移时永远盖满
  const GW = W + 2 * M, GH = H + 2 * M;
  const PAPER = '#efe6d0';                          // 兜底纸色（clip.js 渲染前铺一层，见 SCENES.bg）

  const ground = () => P.cached('ink_tex_paper_v2', GW, GH, (g) => {
    // 1) 纸色：暖米黄底 + 噪声斑驳（显式 1920×1080 尺寸传入，避免按舞台尺寸建图）
    g.drawImage(P.texture('xuan_tex', PAPER, { scale: 0.0025, amt: 9, grain: 7, seed: 5, w: GW, h: GH }), 0, 0);
    // 2) 极淡的颗粒噪点叠层（独立像素，不是 stroke）
    g.drawImage(P.grain('xuan_tex_grain', 0.06, [80, 60, 40], 0.10, GW, GH), 0, 0);
    // 3) 淡墨色斑：整屏均匀铺的深灰洗染（无形状语义）
    const r2 = rng(77);
    for (let i = 0; i < 30; i++) {
      const x = r2() * GW, y = r2() * GH, rx = 130 + r2() * 280, ry = 100 + r2() * 220, a = 0.10 + r2() * 0.10;
      g.save(); g.globalCompositeOperation = 'multiply'; g.globalAlpha = a;
      const rg = g.createRadialGradient(x, y, 0, x, y, Math.max(rx, ry));
      rg.addColorStop(0, 'rgba(58,56,52,.75)'); rg.addColorStop(0.65, 'rgba(58,56,52,.28)'); rg.addColorStop(1, 'rgba(58,56,52,0)');
      g.fillStyle = rg; g.beginPath(); g.ellipse(x, y, rx, ry, 0, 0, Math.PI * 2); g.fill(); g.restore();
    }
    // 4) 径向暗角
    const vg = g.createRadialGradient(GW / 2, GH / 2, 520, GW / 2, GH / 2, 1400);
    vg.addColorStop(0, 'rgba(0,0,0,0)'); vg.addColorStop(1, 'rgba(120,90,50,.22)');
    g.fillStyle = vg; g.fillRect(0, 0, GW, GH);
    P.assertOpaque(g.canvas, '17_ink/ground');      // 有透明像素 → boot fail
  });

  return {
    bg: PAPER,
    draw(c, lt, t) {
      // 从超大 ground 里裁一块：偏移在 ±M 内缓慢漂移，永不露边、无平铺接缝
      const sx = M + Math.sin(t * 0.42) * (M * 0.8), sy = M + Math.sin(t * 0.31 + 1.3) * (M * 0.8);
      c.drawImage(ground(), sx, sy, W, H, 0, 0, W, H);
    },
  };
})();
