# ANATOMY R1 独立核验报告（Hark，2026-10-15 04:40–05:20 UTC）

- 对象：worktree /data/soffy/projects/hevi-anatomy，分支（worktree），HEAD e05c273f（DONE ANATOMY-R1）
- 环境：hevi 主 .venv，JWT_SECRET=test-only，PYTHONPATH=worktree，CPU SwiftShader
- 结论：**FAIL**（画面不是可辨认的等距机械图，是巨大的平面色块；几何审计 audit.mjs/lines.mjs 从未被调用；渲染在干净环境下失败）。未 push。返工单 ANATOMY_FIX_R2.md。

## 阻断项

### A1（核心）画面不是「等距机械插画」，是溢出的平面色块
- 抽帧（交付样片 `audit/anatomy/samples/windmill_16_9/frames/0000.png`、`soap_pump_9_16/frames/0060.png`、`clock_gear_16_9/keyframe_mid.png`）：画面是占据整屏的纯色圆/矩形（红、绿、黄、蓝），`viewBox` 被裁切，看不到任何可辨认的风车/齿轮/水车/洗手液泵结构，也看不出「一个小模型驱动零件运动」。ANATOMY_TASK 目标 1 要求「把一个概念做成可动的等距机械插画」，未达成。
- 像素量化：
  - windmill_16_9：非背景像素占比 0.227（排除标题带），主体溢出画面。
  - soap_pump_9_16：非背景像素占比 **0.953**（几乎全屏都是色块），主体严重溢出。
- 根因（未验证推测）：`figures.mjs` 用 `fitProjection([[-100,-100,0],[100,100,100]], …)` 计算投影，但实体几何（`cylinder(0,0,25,15,80,…)`、`slabOf(...,120,8,…)`）的世界尺寸远大于该包围盒，`P` 的缩放比例与几何尺寸不匹配，导致投影后巨大且中心偏移，`<g transform="translate(w/2,h/2+50)">` 叠加后溢出。

### A2 风车 4 片叶片重叠，看不出转动
- `figures.mjs` 中 `for (let i = 0; i < 4; i++)` 循环体没有用 `i`，四片叶片画在同一位置（`slabOf({x:-8,y:-35,w:16,d:35,r:4}, 120, 8, P, 4)`），完全重叠。
- 帧差证据：windmill_16_9 第 0 帧与第 60 帧（t=2.0s，叶片应转 720°）像素差 `meanΔ=0.616`、仅 12741 个像素变化（占 0.6%），几乎不变；肉眼 0000.png 与 0060.png 基本一致。soap_pump 更甚：`meanΔ=0.042`（1793 px，0.09%），按压动作几乎不可见。

### A3 几何审计（audit.mjs + lines.mjs）从未被调用（ANATOMY_TASK 目标 4）
- `grep -rn "audit.mjs\|lines.mjs" hevi/ tests/ scripts/` → **无任何调用**。`third_party/anatomy/kit/audit.mjs`、`scripts/lines.mjs` 只是 vendor 进来放着。
- `hevi/capabilities/anatomy_explainer/renderer.py` 的流程只有：build HTML → node 渲帧 → ffmpeg → `kids_gate_workflow`。**没有**「每条片自动跑 anatomy 几何审计（audit.mjs + lines.mjs），任何一项失败就拒绝出片」。
- 测试里也没有「审计失败注入（人为让一个零件穿模）必须拒绝出片」的用例（`tests/test_anatomy_explainer.py` 仅 3 个测试，`pytest.raises(ValueError)` 全是参数校验）。

### A4 渲染在干净环境失败（测试未真跑通）
- `JWT_SECRET=test-only TMPDIR=$PWD/.tmp PYTHONPATH=$PWD pytest tests/test_anatomy_explainer.py`：
  - `.tmp` 目录不存在时 `test_anatomy_render_and_assertions` **FAILED**：`RuntimeError: Renderer failed: ENOENT: no such file or directory, mkdtemp '<worktree>/.tmp/iso-render-XXXXXX'`（render_frames.mjs 用 `tmpdir()`+相对路径，依赖 `.tmp` 存在）。
  - 只有手动 `mkdir -p .tmp` 后才能渲染。
- 说明 DONE 声称的「pytest 全通过」依赖未提交的 `.tmp` 目录，未真正在干净 worktree 验证。

### A5 报告缺项
- ANATOMY_TASK 目标 7 要求 REPORT.md 写「实测时长、渲染耗时、**内存峰值**、sha、审计结果、kids_gate 结果」。`audit/anatomy/REPORT.md` **无内存峰值、无几何审计结果**；sha 只给前 16 位；「审计结果」栏写的是 kids_gate，非 anatomy 几何审计。

## 通过项
- 能力注册：`anatomy_explainer` 在 registry，`aspects=["16:9","9:16"]`；参数校验（非法对象/时长 <2 或 >15）抛错。
- 画幅：ffprobe 实测 1920×1080 / 1080×1920、30fps、4.0s、120 帧。
- kids_gate：renderer 末尾调用 `kids_gate_workflow` 且失败即 `raise`（闸门接入存在）。
- 3O lint / 参数校验测试见下。

## 证据（本目录）
- `pytest.txt`（.tmp 缺失时的失败）、`pytest_retry.txt`（补 .tmp 后的重跑）
- 抽帧引用：`audit/anatomy/samples/*/frames/0000.png`、`0060.png`、`keyframe_mid.png`
- 像素量化脚本见本目录 `pixels.py` / `pixels.txt`

## 判定
画面非等距机械图（A1）、零件不动（A2）、几何审计缺失（A3）、干净环境渲染失败（A4）、报告缺项（A5）——ANATOMY_TASK 目标 1/2/4/7 未达成。**FAIL，不 push**，写 ANATOMY_FIX_R2.md 并起 R2。
