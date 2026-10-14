// 17_ink 纹理底：整屏宣纸（纤维＋暗角）＋淡墨色晕染。
// 只做「全屏均匀底纹」，不含任何叙事元素（无窗、无家具、无人物/动物/器物、无山石花木）。
SCENES['17_ink'] = (() => {
  const W = 1920, H = 1080, { rng } = U, P = PAINT;

  // 宣纸底：纸色噪声 + 2600 根纸纤维短弧 + 径向暗角 + 数块淡墨晕（无形状语义，只做整屏色斑）
  const ground = () => P.cached('ink_tex_paper', W, H, (g) => {
    g.drawImage(P.texture('xuan_tex', '#efe6d0', { scale: 0.0025, amt: 9, grain: 7, seed: 5 }), 0, 0);
    const r = rng(41);
    g.lineCap = 'round';
    for (let i = 0; i < 2600; i++) {
      const x = r() * W, y = r() * H, a = r() * Math.PI * 2, l = 6 + r() * 26;
      g.strokeStyle = r() < 0.5 ? `rgba(150,125,90,${0.05 + r() * 0.08})` : `rgba(255,252,240,${0.12 + r() * 0.15})`;
      g.lineWidth = 0.6 + r() * 0.8;
      g.beginPath(); g.moveTo(x, y);
      g.quadraticCurveTo(x + Math.cos(a + 0.6) * l * 0.5, y + Math.sin(a + 0.6) * l * 0.5, x + Math.cos(a) * l, y + Math.sin(a) * l);
      g.stroke();
    }
    // 淡墨色斑：整屏均匀铺的深灰洗染（无形状语义），给相机推拉/横移提供可见的对比边界
    const r2 = rng(77);
    for (let i = 0; i < 26; i++) {
      const x = r2() * W, y = r2() * H, rx = 130 + r2() * 280, ry = 100 + r2() * 220, a = 0.10 + r2() * 0.10;
      g.save(); g.globalCompositeOperation = 'multiply'; g.globalAlpha = a;
      const rg = g.createRadialGradient(x, y, 0, x, y, Math.max(rx, ry));
      rg.addColorStop(0, 'rgba(58,56,52,.75)'); rg.addColorStop(0.65, 'rgba(58,56,52,.28)'); rg.addColorStop(1, 'rgba(58,56,52,0)');
      g.fillStyle = rg; g.beginPath(); g.ellipse(x, y, rx, ry, 0, 0, Math.PI * 2); g.fill(); g.restore();
    }
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
