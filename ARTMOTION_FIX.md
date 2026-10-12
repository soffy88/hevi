# ARTMOTION 返工 r1（审核方 2026-10-12 08:40 CST 核验未通过）

上轮 FIX 已修好的：film_gate 的 cv2 兜底已删除（cv2 缺失直接 RuntimeError）、opencv 已装、finance_chart 不再是空画面（有柱状图逐根生长+最高值标注）、3b1b 有坐标轴+曲线+公式、tests/test_artmotion.py 在本 worktree 跑通、未 push、lint=基线 4 项。OpenMontage AGPL 长行比对无代码复制。

不通过的原因（必须修）：

1. **成片时长不达标且借此绕过质量门**：3 条成片 16.4s / 17.0s / 16.9s，任务要求 20–40 秒。deliver_out/交付说明.md 里 film_gate 三条全是**黄灯**（快速运动帧占比 0.0 / 0.005 / 0.0，90–95% 帧完全静止），只因「片长短于 20s，快动门禁只提示不拦」才被记成 pass。record.json 只写了 `"value": 0, "Passed deliver.py"`，没有真实指标。要求：每条 20–40 秒，film_gate 在 ≥20s 的正常门禁下判 green（不许改阈值/不许靠短片豁免），按交付说明里「动在事件上」的建议真加镜头内运动（快推/横移/砸入）；record.json 写入 film_gate 全部真实指标（fast_ratio、静止帧占比、blank_run_s 等）和灯色。
2. **内容是测试填充语**：口播与画面是「这段是一句非常长的测试口播」「凑够二十秒」「确保产物能过门禁检查」「测试图表/测试单位/A B C D」。必须用真实中文解说稿（每条一个真实主题，例如一个科普点、一组真实公开数据的财经图表并注明来源），画面上的文字/数字来自稿件。
3. **35 种艺术风格根本没接上**：`produce.py` 只把 style_id 当成语法引擎的 `theme`（snow/ink/navy 是配色主题），上游 `references/风格配方/17_ink.md` 等 35 种代码绘制的艺术风格完全没用到。task_1 宣称「17_ink 水墨」，画面却是黄/白/青绿纯色底 + 大黑字，没有任何水墨元素（墨晕、宣纸、笔触、留白山水等）。要求：实现风格配方（至少 17_ink 及另外 2 种风格，例如 25_ghibli、14_8bit）真正作用于画面；record.json 写明实际使用的风格配方 id（如 `17_ink`）与语法 id；contact sheet 能一眼看出风格。
4. **由输入驱动的对比**：E2E 增加一组对照——同一语法+风格，两份不同解说稿各渲染一次，DONE 里给出两份 contact sheet 路径，证明画面内容随输入变化。
5. 单元测试只有 1 个用例，补充覆盖：adapter 契约（输入稿+风格+语法+画幅→MP4+record.json）、cv2 缺失时 gate 抛错/判 red、style id 解析（17_ink）。
6. 重跑 `scripts/artmotion_e2e.py`（至少 3 条：16:9+3b1b+一种风格；9:16+kinetic_type+17_ink；16:9+finance_chart+另一风格），ffprobe（时长/分辨率/音轨）、sha256、亲自看 6 帧 contact sheet，真实数据写入 ARTMOTION_DONE.md；lint 不多于基线 4 项；commit，不要 push。禁止 mock/占位/写死样片。
