// 12_bauhaus 纹理底：整屏色块构成（米白旧纸 + 大块红/蓝/黄/浅蓝平涂 + 斑驳做旧）。
// 只做「全屏均匀底纹」：色块与纸纹，不含任何叙事元素（无人偶、无动物、无文字、无家具）。
SCENES['12_bauhaus'] = (() => {
  const W = 1920, H = 1080, { clamp } = U, P = PAINT;
  const C = { paper: '#ebe3cf', ink: '#161514', red: '#d3262b', blue: '#2a58b4', yellow: '#efc12f', lblue: '#b9cee0', grey: '#c6c3bb', cream: '#f2ecdf' };

  // 斑驳小噪声图（放大使用）：给纸和色块做旧
  const mottle = (key, seed, col, amt) => P.cached('bh_tex_m_' + key, 320, 180, (g) => {
    const im = g.createImageData(320, 180), r = U.rng(seed);
    for (let y = 0; y < 180; y++) for (let x = 0; x < 320; x++) {
      const v = P.fbm(x * 0.045 + seed, y * 0.045, 4), i = (y * 320 + x) * 4;
      im.data[i] = col[0]; im.data[i + 1] = col[1]; im.data[i + 2] = col[2];
      im.data[i + 3] = clamp(v * 1.6 + 0.1) * 255 * amt + r() * 10;
    }
    g.putImageData(im, 0, 0);
  });

  // 全屏色块版式：大块平涂矩形铺满画面（无具象形状），米白纸作底
  const COLS = [C.paper, C.red, C.blue, C.yellow, C.lblue, C.cream, C.grey, C.paper];
  const ground = () => P.cached('bh_tex_ground', W, H, (g) => {
    g.fillStyle = C.paper; g.fillRect(0, 0, W, H);
    // 8×5 大格平涂，格间留细缝，颜色按确定性顺序铺（全屏均匀色块）
    const gx = W / 8, gy = H / 5;
    let k = 0;
    for (let j = 0; j < 5; j++) for (let i = 0; i < 8; i++, k++) {
      if ((i + j) % 3 === 2) continue;                       // 部分格留纸底，形成留白节奏
      g.fillStyle = COLS[k % COLS.length];
      g.fillRect(i * gx + 3, j * gy + 3, gx - 6, gy - 6);
    }
    // 贯穿画面的细斜线（构成主义味道，全屏均匀）
    g.strokeStyle = C.ink; g.lineWidth = 2.2;
    g.beginPath(); g.moveTo(40, 170); g.lineTo(1900, 840); g.stroke();
    // 做旧：斑驳噪声 + 颗粒
    g.globalAlpha = 0.5; g.drawImage(mottle('paper', 3, [150, 130, 95], 0.35), 0, 0, W, H); g.globalAlpha = 1;
    g.drawImage(P.grain('bh_tex', 0.02, [40, 35, 30], 0.35), 0, 0);
  });

  return {
    draw(c, lt, t) {
      c.drawImage(ground(), 0, 0);
      // 一格色块按拍缓慢轮换（每 0.7s 一格），让底纹每帧都在动但不闪
      const r = U.rng(19), step = Math.floor(t / 0.7);
      const gx = W / 8, gy = H / 5, cyc = [C.red, C.yellow, C.blue, C.cream, C.lblue, C.grey];
      for (let n = 0; n < 3; n++) {
        const idx = (step * 3 + n * 7 + r() * 40 | 0) % 40;
        const i = idx % 8, j = (idx / 8 | 0) % 5;
        if ((i + j) % 3 === 2) continue;
        c.fillStyle = cyc[(step + n) % cyc.length];
        c.fillRect(i * gx + 3, j * gy + 3, gx - 6, gy - 6);
      }
    },
  };
})();
