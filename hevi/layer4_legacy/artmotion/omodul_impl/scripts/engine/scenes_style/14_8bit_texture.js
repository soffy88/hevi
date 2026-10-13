// 14_8bit 纹理底：整屏像素格纹（240×135 低分辨率 → 最近邻放大 8 倍）。
// 只做「全屏均匀底纹」：量化色块 + 像素网格，不含任何叙事元素（无窗、无家具、无人物/动物/植物）。
SCENES['14_8bit'] = (() => {
  const W = 1920, H = 1080, S = 8, LW = 240, LH = 135, { rng } = U, P = PAINT;
  // 低分辨率调色板：深青底 + 米黄/浅青块（全屏均匀，不构成任何具象形状）
  const C = { bg: '#0a4a58', c1: '#0d6a72', c2: '#12484f', c3: '#e8d9a6', c4: '#a8c8b8', c5: '#1a5a62' };
  const PAL = [C.bg, C.c1, C.c2, C.c5, C.c1, C.bg, C.c2, C.c4].map(P.hex);

  // 低分辨率底：量化色块（大块同色，偶尔一块浅色），像像素画的天空/水面底纹
  const ground = () => P.cached('8b_tex_bg', LW, LH, (g) => {
    const r = rng(97);
    for (let y = 0; y < LH; y += 6) for (let x = 0; x < LW; x += 6) {
      const v = r();
      const col = v < 0.62 ? C.bg : v < 0.78 ? C.c1 : v < 0.88 ? C.c2 : v < 0.95 ? C.c5 : C.c4;
      g.fillStyle = col; g.fillRect(x, y, 6, 6);
    }
    // 像素网格线（每 6 低像素一道暗线）
    g.fillStyle = 'rgba(0,0,0,.16)';
    for (let x = 0; x < LW; x += 6) g.fillRect(x, 0, 1, LH);
    for (let y = 0; y < LH; y += 6) g.fillRect(0, y, LW, 1);
  });

  // 持久的低分辨率画布（每帧清空重画）
  const frame = () => P.cached('8b_tex_frame', LW, LH, () => {});

  return {
    draw(c, lt, t) {
      const L = frame(), g = L.getContext('2d');
      g.setTransform(1, 0, 0, 1, 0, 0); g.clearRect(0, 0, LW, LH);
      g.drawImage(ground(), 0, 0);
      // 缓慢横移的像素亮带（步进，整低像素），让底纹每帧都在动但不闪烁
      const bx = Math.floor((t * 12) % (LW + 40)) - 20;
      for (let y = 0; y < LH; y += 6) {
        const col = (y / 6) % 3 === 0 ? C.c4 : C.c1;
        g.fillStyle = col; g.fillRect(bx, y, 4, 3);
      }
      c.imageSmoothingEnabled = false;
      c.drawImage(L, 0, 0, LW, LH, 0, 0, W, H);
      c.imageSmoothingEnabled = true;
    },
  };
})();
