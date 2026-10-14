// 17_ink 纹理底：整屏宣纸（极淡颗粒 + 径向暗角 + 几块淡墨色斑），不含任何叙事元素。
// r5 B1 修复：之前 2600 根 paper fibers 在深色墨色斑上被冲成可见的「白/金色碎弧线」，
// 看上去像「少女黑发 / 猫的笔触纹样」（审核方点名为 r5 B1 阻断）。改为只保留纸本身的颗粒
// （PAINT.texture + grain 噪点），不再画任何 stroke/curve 形状。
SCENES['17_ink'] = (() => {
  const W = 1920, H = 1080, { rng } = U, P = PAINT;

  // 宣纸底：纸色噪声颗粒 + 径向暗角 + 几块淡墨色斑（无形状语义，只做整屏色斑给相机运动提供边界）
  const ground = () => P.cached('ink_tex_paper', W, H, (g) => {
    // 1) 纸色：暖米黄底 + 噪声斑驳（PAINT.texture 内部已含 5 octaves fbm 噪声）
    g.drawImage(P.texture('xuan_tex', '#efe6d0', { scale: 0.0025, amt: 9, grain: 7, seed: 5 }), 0, 0);
    // 2) 极淡的颗粒噪点叠层（不是 stroke，是独立像素）——给相机运动提供亚像素级变化
    g.drawImage(P.grain('xuan_tex_grain', 0.06, [80, 60, 40], 0.10), 0, 0);
    // 3) 淡墨色斑：整屏均匀铺的深灰洗染（无形状语义，无 stroke 形状）
    const r2 = rng(77);
    for (let i = 0; i < 26; i++) {
      const x = r2() * W, y = r2() * H, rx = 130 + r2() * 280, ry = 100 + r2() * 220, a = 0.10 + r2() * 0.10;
      g.save(); g.globalCompositeOperation = 'multiply'; g.globalAlpha = a;
      const rg = g.createRadialGradient(x, y, 0, x, y, Math.max(rx, ry));
      rg.addColorStop(0, 'rgba(58,56,52,.75)'); rg.addColorStop(0.65, 'rgba(58,56,52,.28)'); rg.addColorStop(1, 'rgba(58,56,52,0)');
      g.fillStyle = rg; g.beginPath(); g.ellipse(x, y, rx, ry, 0, 0, Math.PI * 2); g.fill(); g.restore();
    }
    // 4) 径向暗角
    const vg = g.createRadialGradient(W / 2, H / 2, 500, W / 2, H / 2, 1250);
    vg.addColorStop(0, 'rgba(0,0,0,0)'); vg.addColorStop(1, 'rgba(120,90,50,.22)');
    g.fillStyle = vg; g.fillRect(0, 0, W, H);
  });

  const frame = () => P.cached('ink_tex_frame', W, H, () => {});

  return {
    draw(c, lt, t) {
      const L = frame(), g = L.getContext('2d');
      g.setTransform(1, 0, 0, 1, 0, 0); g.clearRect(0, 0, W, H);
      // 底纹整体缓慢漂移（墨在纸上洇开的连续感），2×2 平铺防露边；相机（clip.js 的 CAM.apply）
      // 再叠加推拉/横移——两条合起来保证每帧都有真实变化（film_gate 快动门禁）。
      const sx = t * 150, sy = t * 95;
      g.save();
      g.translate(-(sx % W), -(sy % H));
      g.drawImage(ground(), 0, 0); g.drawImage(ground(), W, 0);
      g.drawImage(ground(), 0, H); g.drawImage(ground(), W, H);
      g.restore();
      c.drawImage(L, 0, 0);
    },
  };
})();
