// 14_8bit 纹理底：全屏均匀的 8×8 像素块色场（8-bit 抖动/棋盘质感）。
// 只做「全屏均匀底纹」：像素网格与色块，严格不含任何叙事元素（无窗、无家具、无人物/动物/植物）。
// r6 B1：纹理按显式尺寸建、boot 断言全不透明；像素网格平铺天然无缝（格子对齐），保留滚动平铺。
SCENES['14_8bit'] = (() => {
  const W = 1920, H = 1080, { rng } = U, P = PAINT;
  const CELL = 8;
  // 单一平涂的 8-bit 冷色调色板（青绿到深青），无渐变、无具象
  const COLS = ['#0a4a58', '#0d5260', '#115a66', '#0a4450', '#125f6a', '#0e4e5a', '#155a52', '#0b4750'];
  const BG = COLS[0];

  // 全屏色块场：每格由低频噪声挑一个色（相邻格有差 → 有像素纹理；整体均匀 → 无具象形状）
  const ground = () => P.cached('8b_tex_bg_v2', W, H, (g) => {
    const gw = Math.ceil(W / CELL), gh = Math.ceil(H / CELL);
    for (let y = 0; y < gh; y++) for (let x = 0; x < gw; x++) {
      const v = P.fbm(x * 0.07 + 3.1, y * 0.07 + 7.7, 3);          // 约 [-1,1]
      const idx = Math.max(0, Math.min(COLS.length - 1, Math.floor((v * 0.5 + 0.5) * COLS.length)));
      g.fillStyle = COLS[idx];
      g.fillRect(x * CELL, y * CELL, CELL, CELL);
    }
    // 极细的格线（每格一道，不构成具象），强化像素网格观感
    g.fillStyle = 'rgba(255,255,255,.05)';
    for (let x = 0; x < W; x += CELL) g.fillRect(x, 0, 1, H);
    for (let y = 0; y < H; y += CELL) g.fillRect(0, y, W, 1);
    P.assertOpaque(g.canvas, '14_8bit/ground');
  });

  return {
    bg: BG,
    draw(c, lt, t) {
      const sW = (globalThis.STAGE && globalThis.STAGE.W) || 1920;
      const sH = (globalThis.STAGE && globalThis.STAGE.H) || 1080;
      // 像素滚动：每帧整格平移（30fps 下 8px/帧 = 1 格/帧）。整帧像素化（clip.js 的 PIXELATE）会把
      // 每帧的亚格位移量化掉，只有 ≥1 格/帧 的位移才能在量化后的成片上留下真实变化（film_gate 的快动测量）。
      const sx = Math.round((t * 240) / CELL) * CELL, sy = Math.round((t * 120) / CELL) * CELL;
      const ox = -((sx % W) + W) % W, oy = -((sy % H) + H) % H;
      c.save();
      c.imageSmoothingEnabled = false;
      c.beginPath(); c.rect(0, 0, sW, sH); c.clip();
      for (let y = oy; y < sH; y += H) {
        for (let x = ox; x < sW; x += W) {
          c.drawImage(ground(), x, y);
        }
      }
      c.restore();
    },
  };
})();
