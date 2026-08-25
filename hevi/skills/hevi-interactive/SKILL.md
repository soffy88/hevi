---
name: hevi-interactive
version: "0.1.1"
description: Interactive web animation core — map user input (scroll/mouse/drag/touch/device orientation) to animation frames, budget frames per control kind, decide resource form (webp atlas / seekable MP4 / sliced atlas / webcodecs), and build atlas manifests.
argument-hint: "budget --display 240x240 --dpr 2 --frames 180"
allowed-tools: Bash, Read
homepage: https://github.com/helios-plat/hevi
license: MIT
user-invocable: true
---

# /hevi-interactive

交互动画 Skill（内化自 oil-oil/oil-motion）：把 AI 生成的连续动作接入网页交互。核心引擎
`hevi/motion/interactive.py` 使用确定性数学，不依赖模型。

## 调用

```bash
cd "$HEVI_ROOT" && uv run python -m hevi.skills.interactive_cli budget --display 240x240 --dpr 2 --frames 180
uv run python -m hevi.skills.interactive_cli decide --transparency --frames 200 --display 240x240 --control scroll
uv run python -m hevi.skills.interactive_cli frames --control ring
uv run python -m hevi.skills.interactive_cli manifest --frames 180 --cols 15 --rows 12 --cell 480 --mapping scroll
```

先运行 `budget` 检查尺寸、总帧数、分片和内存；再运行 `decide` 选资源形式；最后用
`frames`/`manifest` 生成映射或图集元数据。不要凭经验覆盖 CLI 的计算结果。若参数或
命令行为与本文不一致，以 `--help` 和实际 JSON 输出为准。

## 纪律（来源 oil-motion）

- **关键画面先行**：先确认开始/中间/结束状态（主体身份、结构、构图不变），再生成连续动作。
- **帧数 ≠ FPS**：帧数是交互参数可访问的独立姿态数，不是播放帧率。常用起点：
  滚动 24 帧/屏、拖拽 48–72、环形 72–120；只有在输入范围或动作细节确实需要时增加。
- **输入映射要连续**：将归一化输入 `u∈[0,1]` 映射到
  `i=round(u*(N-1))`，并在边界 clamp；拖拽/指针应按位移累计，环形控制应使用角度
  的最短有符号差，避免跨 0° 跳变。输入方向必须与首尾动作方向一致，必要时反转映射，
  不要通过重复帧掩盖方向错误。
- **图集约束**：单元 = 显示尺寸 × DPR（禁止低分辨率放大）；图集宽高 ≤4096，超限
  分片或改用视频解码。RGBA 解码内存约为 `宽×高×4` 字节/帧；还要考虑纹理上传、
  多分片和并发预加载的峰值，而非只看单帧。
- **资源形式按需选**：透明且 `<300` 帧优先 WebP 图集；长顺序滚动优先可 seek 视频；
  高频随机访问且目标环境支持时用 WebCodecs；hover/click 使用多段短资源。透明、随机
  seek、首帧时间和浏览器兼容性冲突时，明确取舍并提供降级，不要只按文件体积决定。
- **图集元数据必须可复现**：`cols × rows` 应能容纳 `frames`；cell 必须等于实际像素
  单元尺寸；记录 frame 顺序、padding/空槽策略、映射方向和 DPR，避免导出后索引错位。
- **交互 QA**：快速反向不闪烁（环形使用最短距离）；输入↔动画方向对应；首尾边界不越界；
  低端设备不因同步解码卡顿；`prefers-reduced-motion` 下提供静态关键帧或低频淡变回退。
  在真实 DPR、快速输入、反向输入、刷新/恢复滚动位置四种情形验证。

## 输出与决策

向调用方报告：输入控制类型与范围、最终独立帧数、索引映射、单元像素尺寸、图集分片、
估算峰值内存、推荐资源形式及降级方案。若 `budget` 或 `manifest` 暴露超限，优先降低
单元尺寸/分片/改用视频，而不是静默裁切帧或放大素材。