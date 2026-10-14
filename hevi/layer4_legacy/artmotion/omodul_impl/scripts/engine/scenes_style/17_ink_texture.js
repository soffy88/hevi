// 17_ink 纹理底：整屏宣纸（暖米黄纸 + 噪声斑驳 + 淡墨洗染 + 径向暗角），不含任何叙事元素。
// r6 B1 修复（根因）：原来 ground() 是 1920×1080 缓存画布，但 P.texture/P.grain 按「舞台尺寸」建图；
// 竖屏舞台是 1080×1920，于是宣纸只盖住左 1080px，右侧 840px 透明，成片丢 alpha 后就是「黑底 + 灰色弧线」。
// 现在：纹理一律显式按 1920×1080 建（P.texture/P.grain 传 w/h）；ground() 建在 1920×1080 上；
// 平铺用 P.tileMirror 的镜像平铺（边缘镜像 → 接缝像素连续，消灭横屏那道硬边）；boot 时断言全不透明。
// r6 另一处：竖屏 y5 语法层不挂相机（fixed:true），画面运动全靠风格底——原来墨色太淡，整帧平均差
// 掉到 2.8（fast_ratio 0.003 红灯）。这里除静态墨洗染外加一层「活墨」：位置/大小/透明度都按 t 缓变的
// 淡墨晕（就是宣纸上墨在慢慢洇开，无任何具象形状），每帧都有真实变化，仍是全屏均匀底纹。
SCENES['17_ink'] = (() => {
  const W = 1920, H = 1080, { rng } = U, P = PAINT;
  const PAPER = '#efe6d0';                          // 兜底纸色（clip.js 渲染前铺一层，见 SCENES.bg）

  const ground = () => P.cached('ink_tex_paper_v4', W, H, (g) => {
    // 1) 纸色：暖米黄底 + 细密噪声斑驳。scale/amt/grain 取高频细密值——低频大晕在竖屏那一点可视区里
    //    几乎没有可测的帧间变化（film_gate 快动门禁掉到 0.003）；纸本身就得有细密的颗粒与明暗。
    g.drawImage(P.texture('xuan_tex', PAPER, { scale: 0.022, amt: 30, grain: 20, seed: 5, w: W, h: H }), 0, 0);
    // 2) 颗粒噪点叠层（独立像素，不是 stroke）
    g.drawImage(P.grain('xuan_tex_grain', 0.16, [70, 52, 36], 0.22, W, H), 0, 0);
    // 3) 墨色洗染：整屏铺的大块淡墨（「墨分五色」），无形状语义，但浓度和尺度都要够——
    //    相机推拉/横移要在成片上留下可测变化（film_gate 快动门禁）。
    const r2 = rng(77);
    for (let i = 0; i < 30; i++) {
      const x = r2() * W, y = r2() * H, rx = 180 + r2() * 380, ry = 140 + r2() * 300, a = 0.08 + r2() * 0.12;
      g.save(); g.globalCompositeOperation = 'multiply'; g.globalAlpha = a;
      const rg = g.createRadialGradient(x, y, 0, x, y, Math.max(rx, ry));
      rg.addColorStop(0, 'rgba(44,42,38,.9)'); rg.addColorStop(0.6, 'rgba(44,42,38,.42)'); rg.addColorStop(1, 'rgba(44,42,38,0)');
      g.fillStyle = rg; g.beginPath(); g.ellipse(x, y, rx, ry, 0, 0, Math.PI * 2); g.fill(); g.restore();
    }
    // 4) 中高频斑驳：密的小墨点（纸的纤维/墨垢感）。不是笔触，是颗粒细节，给漂移提供亚像素级变化。
    //    用椭圆（随机长短轴）而不是圆——圆排在一起会读成「网点」；透明度也压低，纸整体仍是暖米黄。
    const r3 = rng(1231);
    g.save(); g.globalCompositeOperation = 'multiply';
    for (let i = 0; i < 640; i++) {
      const x = r3() * W, y = r3() * H, rx = 4 + r3() * 16, ry = rx * (0.5 + r3() * 1.1);
      g.save(); g.translate(x, y); g.rotate(r3() * Math.PI);
      g.globalAlpha = 0.05 + r3() * 0.17;
      const rg = g.createRadialGradient(0, 0, 0, 0, 0, Math.max(rx, ry));
      rg.addColorStop(0, 'rgba(52,48,42,1)'); rg.addColorStop(1, 'rgba(52,48,42,0)');
      g.fillStyle = rg; g.beginPath(); g.ellipse(0, 0, rx, ry, 0, 0, Math.PI * 2); g.fill(); g.restore();
    }
    g.restore();
    // 5) 径向暗角
    const vg = g.createRadialGradient(W / 2, H / 2, 500, W / 2, H / 2, 1250);
    vg.addColorStop(0, 'rgba(0,0,0,0)'); vg.addColorStop(1, 'rgba(120,90,50,.10)');
    g.fillStyle = vg; g.fillRect(0, 0, W, H);
    P.assertOpaque(g.canvas, '17_ink/ground');      // 有透明像素 → boot fail
  });

  // 活墨层：12 块随时间缓变的淡墨晕（位置椭圆漂移、半径呼吸、透明度脉动）。确定性（只由 t 算），可跳帧。
  const LIVE = Array.from({ length: 12 }, (_, i) => ({ i, px: 0.5 + 0.34 * Math.sin(i * 1.7), py: 0.5 + 0.32 * Math.sin(i * 2.3 + 1.1), r: 0.26 + 0.14 * ((i * 37) % 11) / 11 }));

  return {
    bg: PAPER,
    draw(c, lt, t) {
      // 静态纸底 + 镜像平铺（接缝像素连续），漂移给画面提供持续变化
      P.tileMirror(c, ground(), t * 320, t * 200);
      // 活墨：每帧都在洇开的淡墨晕。multiply 压在纸色上，浓度低（≤0.22）——不会出现大面积近黑帧。
      c.save(); c.globalCompositeOperation = 'multiply';
      for (const e of LIVE) {
        const x = W * (e.px + 0.06 * Math.sin(t * 0.30 + e.i * 0.9));
        const y = H * (e.py + 0.06 * Math.sin(t * 0.24 + e.i * 1.4));
        const rx = W * (e.r + 0.05 * Math.sin(t * 0.19 + e.i * 2.1));
        const ry = H * (e.r * 0.78 + 0.04 * Math.sin(t * 0.17 + e.i * 1.1));
        const a = 0.06 + 0.16 * (0.5 + 0.5 * Math.sin(t * 0.26 + e.i * 1.7));
        const rg = c.createRadialGradient(x, y, 0, x, y, Math.max(rx, ry));
        rg.addColorStop(0, `rgba(44,42,38,${a})`); rg.addColorStop(0.72, `rgba(44,42,38,${a * 0.45})`); rg.addColorStop(1, 'rgba(44,42,38,0)');
        c.globalAlpha = 1; c.fillStyle = rg;
        c.beginPath(); c.ellipse(x, y, rx, ry, 0, 0, Math.PI * 2); c.fill();
      }
      c.restore();
    },
  };
})();
