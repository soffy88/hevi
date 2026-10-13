// 14_8bit 纹理底：全屏均匀像素网格底纹
// 只做「全屏均匀底纹」，严格不含任何叙事元素（无窗、无家具、无人物/动物/植物）。
SCENES['14_8bit'] = (() => {
  const W = 1920, H = 1080, { rng } = U, P = PAINT;
  const rect = P.rectPts, ellipsePts = P.ellipsePts;

  const ground = () => P.cached('8b_tex_bg', W, H, (g) => {
    // 仅：8×8 像素网格均匀色块，没有任何具象形状（无窗、无挂画、无植物、无家具）。
    // 颜色块均为单一平涂，无渐变、无纹理细节、无图案变化。
    const C = ['#0a4a58', '#1a5a62', '#e8d9a6', '#a8c8b8'];
    const base = C[rng(4)];
    g.fillStyle = base;
    g.fillRect(0, 0, W, H);
    // 极简极细网格线（每 64 像素一道，不构成具象）
    g.fillStyle = 'rgba(255,255,255,.03)';
    for (let x = 0; x < W; x += 64) g.fillRect(x, 0, 1, H);
    for (let y = 0; y < H; y += 64) g.fillRect(0, y, W, 1);
  });

  // 持久的低分辨率画布（每帧清空重画）
  const frame = () => P.cached('8b_tex_frame', W, H, () => {});

  return {
    draw(c, lt, t) {
      const L = frame(), g = L.getContext('2d');
      g.setTransform(1, 0, 0, 1, 0, 0); g.clearRect(0, 0, W, H);
      g.drawImage(ground(), 0, 0);
      c.imageSmoothingEnabled = false;
      c.drawImage(L, 0, 0, W, H);
      c.imageSmoothingEnabled = true;
    },
  };
})();