# PaperPromo — 已验证模板替换指南(3O 内化 Round 3g)

`PaperPromo` 是 hevi 版产品宣传片模板(纸墨琥珀风格,1920×1080 @ 30fps,默认 17.4s),
结构按 **promo-energy-arc** 序列模式:①品牌开场(字卡 hold ≥1s)→ ②首功能立传 →
③功能爬升(功能卡 + 呼吸字卡交替)→ ④发布会收场(字标 hold)。

## 替换步骤(换产品复现)

1. **截图**:用 `hevi.motion.page_capture` 采集产品页面真实截图(全页 2x 纹理 +
   元素抠图 + layout.json),或手放 `public/` 下的 PNG。
2. **改 props**(`src/Root.tsx` 的 `PaperPromo` 组合 defaultProps):
   - `productName` / `tagline`:品牌与主标语(呼吸字卡复用 tagline,勿与 outro 重复)。
   - `features`:功能清单(每项一个功能卡;信息密度最高的放倒数第 2 位)。
   - `pages`:与 features 对齐的产品截图数组(真实截图,勿手搓复刻)。
   - `accentColor` / `paperColor` / `inkColor`:品牌 tokens(从设计 token 提取)。
3. **预览/渲染**:
   ```bash
   npx remotion studio        # 预览
   npx remotion render PaperPromo out/promo.mp4
   npx remotion still PaperPromo out/qa/f60.png --frame=60   # 逐镜静帧自检
   ```
4. **终检**:按 `hevi/verdict/final_review.py` 的 P/F/V/S/B/D 清单逐项过;节奏
   硬项:字标 hold ≥1s、功能收尾静止 ≥0.5s。

## 契约

- 1920×1080,30fps;截图 `object-fit: contain`(不裁剪)。
- 默认静音画面轨(配音/音乐后期);配 BGM 时按 beat_sync 卡点。
- 本模板用平面 + 轻推近(确定性,无 3D 文字糊风险);2.5D 页面相机为可选增强
  (对应 shotcraft PageCam 技法,需高倍栅格化防糊)。

## 已验证

- `tsc --noEmit` 干净;`remotion compositions` 注册成功;
- 静帧渲染实测:HandDrawn-Portrait(frame 80)、PaperPromo(frame 60)均 `Rendered 1/1`。
