// 17_ink 纹理底：整屏宣纸（纤维＋暗角）＋极淡的墨色晕染。
// 只做「全屏均匀底纹」，不含任何叙事元素（无窗、无家具、无人物/动物/器物）。
SCENES['17_ink'] = (() => {
  const W = 1920, H = 1080, { rng } = U, P = PAINT;

  // 宣纸底：纸色噪声 + 2600 根纸纤维短弧 + 径向暗角
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
    const vg = g.createRadialGradient(W / 2, H / 2, 500, W / 2, H / 2, 1250);
    vg.addColorStop(0, 'rgba(0,0,0,0)'); vg.addColorStop(1, 'rgba(120,90,50,.22)');
    g.fillStyle = vg; g.fillRect(0, 0, W, H);
  });

  // 极淡的墨晕：一处柔和的深灰洗染（无形状语义），随全片时间缓慢洇开
  const mist = (c, t, x, y, rx, ry, a, seed) => {
    const grow = 1 + 0.05 * Math.sin(t * 0.4 + seed);
    c.save(); c.globalCompositeOperation = 'multiply'; c.globalAlpha = a;
    c.translate(x, y); c.scale(grow, grow);
    const g = c.createRadialGradient(0, 0, 0, 0, 0, Math.max(rx, ry));
    g.addColorStop(0, 'rgba(58,56,52,.55)'); g.addColorStop(0.7, 'rgba(58,56,52,.16)'); g.addColorStop(1, 'rgba(58,56,52,0)');
    c.fillStyle = g; c.beginPath(); c.ellipse(0, 0, rx, ry, 0, 0, Math.PI * 2); c.fill(); c.restore();
  };

  return {
    draw(c, lt, t) {
      c.drawImage(ground(), 0, 0);
      mist(c, t, W * 0.20, H * 0.32, 430, 300, 0.10, 3);
      mist(c, t, W * 0.84, H * 0.70, 520, 360, 0.08, 9);
    },
  };
})();
