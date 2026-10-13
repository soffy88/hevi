// 25_ghibli 纹理底：全屏均匀水彩晕染底纹
// 只做「全屏均匀底纹」，严格不含任何叙事元素（无窗、无家具、无植物、无人物/动物）。
SCENES['25_ghibli'] = (() => {
  const W = 1920, H = 1080, { rng } = U, P = PAINT;
  const wash = P.watercolor, rect = P.rectPts, ellipsePts = P.ellipsePts;

  const ground = () => P.cached('gh_tex_bg', W, H, (g) => {
    // 仅：暖米黄纸底纹 + 细碎颗粒纹理，没有任何具象形状。
    // 无 window、no curtain、no tree、no cloth、no daisies、no komorebi。
    g.drawImage(P.texture('gh_tex_paper', '#f4ead0', { scale: 0.006, amt: 26, grain: 16, dark: '#9c7a4a', seed: 3 }), 0, 0);
    // 移除了所有径向渐变、变形色斑、高频细节：只保留纯纸底色与均匀颗粒。
    // 中低空间频率结构由纸张本身提供，足以配合 film_gate 的快动测量。
  });

  return {
    draw(c, lt, t) {
      c.drawImage(ground(), 0, 0);
    },
  };
})();