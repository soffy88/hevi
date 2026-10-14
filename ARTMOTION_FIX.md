# ARTMOTION 返工 r6（审核方 2026-10-14 13:0x CST 独立复核 @3f444c56 DONE ARTMOTION-R5 —— 不通过）

复核方法：自算 ffprobe/sha256（4 条与 DONE 一致，渲染 02:38–02:42 UTC，晚于最后代码提交 230b1eb8 02:35 UTC，确为当前代码产物）；每条 6 帧 3x2 + 12 帧 4x3 拼图，task_1 另做 2fps 54 帧拼图，全分辨率抽帧亲眼看；volumedetect；逐帧暗像素统计；pytest；3O lint；读 clip.js / y5_kinetic_type.js / lib/paint.js / scenes_style/*.js 源码。

## 本轮已确认修好（不要回退）
- 时长 26.90–32.00s、分辨率、aac 音轨（mean −18.2~−19.8 dB）✓
- 横屏 task_0（ghibli）/task_2（8bit）：示范房间/家具/窗/人物全部消失，底纹是全屏水彩晕/像素格 ✓
- scenes_style/*.js grep 不到 girl|cat|shrimp|curtain|window|WIN|tablecloth|daisies|plant|mug|desk|bg()，scan_texture_files 已接入 produce 门禁 ✓
- LaTeX：task_0 屏上为「QKᵀ/√dₖ」「Softmax(QKᵀ)V」，无 \ ^ _ { }；sanitize_latex + find_latex_source 门禁 + 测试 ✓
- 文字出框：12 帧/2fps 全看，4 条均无左右切字；task_2 标题完整、2023/2024 柱在画内；textsafe.json 4 条 violations=0 ✓
- MIT：third_party/huashu-art-motion/LICENSE + NOTICE.md；docs/third_party/provenance-ledger.yaml 已登记 ✓
- pytest tests/test_artmotion.py 6 passed；3O lint 仅基线 4 项 ✓

## 阻断（必须修）
1. **竖屏 ink 纹理仍有约 40% 帧是黑底+灰色弧线/棕色大块（r5 B1 同一症状未修）**。
   - 实测（2fps，暗像素 luma<60 占比 >25% 的帧）：task_1 25/54（46%，其中 22 帧 >50%），task_3 20/54（37%）；横屏 task_0 为 0。时间段约 0.5–6s、14–19s；画面硬竖边一半宣纸一半黑（见 verify_r5b/task_1_2fps.jpg、t1_15.5.png）。黑底上的黑字只靠白描边勉强可读。
   - 根因（读源码确认）：lib/paint.js 的 P.texture / P.grain 按**舞台尺寸** W×H 建图（竖屏 = 1080×1920），而 17_ink_texture.js 的 ground() 是 1920×1080 缓存画布，于是宣纸只盖住左 1080px，右侧 840px 透明；上面那 26 块 rgba 径向墨斑和暗角是半透明的，渲染丢 alpha 后就成了「黑底 + 灰色同心弧 + 棕色块」。230b1eb8 删纸纤维没碰到根因。
   - 要求：texture 场景内部一律显式按 1920×1080 建纹理（给 P.texture/P.grain 传尺寸，或场景里自己建 W×H 画布，不依赖舞台尺寸）；ground() 不得有透明像素（加断言：getImageData 全部 alpha=255，否则 boot fail）；渲染前把主画布先铺一层不透明纸色兜底。
   - 新增门禁：film_gate/produce 加「大面积近黑帧」检查（≥2fps，单帧 luma<40 像素 >20% 且该风格底色不是深色 → 红灯），输出写进 DONE。验收：task_1/task_3 暗帧 0。
   - 同时检查 12_bauhaus/25_ghibli/14_8bit 竖屏是否有同样问题（各跑一条竖屏 10s 样片看）。
2. **8bit 图表文字被 8× 像素化毁掉，数字读错**。task_2 全分辨率帧：2024 柱值「887」显示成「SS7」，2023「609」像「G09」；标题「累计装机容量」糊成「SR计耧机宫量」；单位行、Y 轴刻度、注释（「历史新高」那条）完全不可读（见 t2_28_crop.png、t2_28_title.png）。r5 B2 要求的是「像素量化 + **像素字体**」，不是把 CJK 文字整体 1/8 降采样。
   - 要求：底纹/柱/线照旧像素化；文字层不进 1/8 低分辨率缓冲，改用像素风位图字体（如 Zpix/Fusion Pixel 等 OFL 字体，入 third_party + ledger）在原分辨率按整数倍画；或像素化倍率对文字 ≤2。数字必须 100% 可读：对 task_2 每个数值标签做 OCR（本地 tesseract/paddleocr，不准用云 API）或像素比对测试，读出 206/309/392/609/887 全对才算过。

## 非阻断（顺手修）
- 横屏纹理 2×2 平铺有明显接缝：task_0 多帧出现一条横向/竖向硬边（上下两块水彩颜色突变，见 t0_27.png y≈450 处）。ground 改成无缝可平铺（边缘镜像/周期噪声），或别用平铺。
- task_0 小号蓝色说明文字压在高对比水彩色块上，可读性一般；给说明文字加纸色衬底或描边。
- produce.py:635 still_ratio 门禁写死 `"passed": True`（48fdfec1 起就有）：要么按 film_gate 的灯判定，要么改名为 info 项并从 gates 移出，不要以 passed=True 形式出现。
- r4 遗留非阻断（highlight/number cue 旁白不上屏、task_0 折线示意数据、produce 无时长门禁、audio 均分伪对齐）仍只写"已记录"。

## 验收
重跑 scripts/artmotion_e2e.py 4 条 + 新增 1 条竖屏 ghibli 或 bauhaus 10s；自己 2fps 抽帧逐张看：竖屏无黑块/硬竖边、8bit 数字全部可读、横屏无平铺接缝；暗帧门禁、OCR/数字可读检查、textsafe 输出写入 DONE；ffprobe/sha256 写入 DONE；pytest 不新增失败；lint ≤ 基线 4；commit，不 push。禁止 mock/占位/写死样片/写死 passed。

## 安全规则
只改本 worktree；不删 worktree 外任何文件；不清理磁盘（/data <5G 写 DISK_FULL_NOTE.md 停止）；所有 python 设 PYTHONPATH=/data/soffy/projects/hevi-artmotion；不 push；不调付费 API。完成后在 ARTMOTION_DONE.md 最后一行写 DONE ARTMOTION-R6。
