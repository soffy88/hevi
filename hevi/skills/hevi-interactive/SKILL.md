---
name: hevi-interactive
version: "0.1.0"
description: Interactive web animation core — map user input (scroll/mouse/drag/touch/device orientation) to animation frames, budget frames per control kind, decide resource form (webp atlas / seekable MP4 / sliced atlas / webcodecs), and build atlas manifests.
argument-hint: "budget --display 240x240 --dpr 2 --frames 180"
allowed-tools: Bash, Read
homepage: https://github.com/helios-plat/hevi
license: MIT
user-invocable: true
---

# /hevi-interactive

交互动画 Skill(内化自 oil-oil/oil-motion):把 AI 生成的连续动作接入网页交互。
核心引擎 `hevi/motion/interactive.py` —— 全部确定性数学,不依赖模型。

## 调用

```bash
cd "$HEVI_ROOT" && uv run python -m hevi.skills.interactive_cli budget --display 240x240 --dpr 2 --frames 180
uv run python -m hevi.skills.interactive_cli decide --transparency --frames 200 --display 240x240 --control scroll
uv run python -m hevi.skills.interactive_cli frames --control ring
uv run python -m hevi.skills.interactive_cli manifest --frames 180 --cols 15 --rows 12 --cell 480 --mapping scroll
```

## 纪律(来源 oil-motion)

- **关键画面先行**:先确认开始/中间/结束状态(主体身份/结构/构图不变),再生成连续动作。
- **帧数 ≠ FPS**:帧数是交互参数上可访问的独立姿态数(滚动 24 帧/屏、拖拽 48-72、
  环形 72-120)。
- **图集约束**:单元 = 显示尺寸 × DPR(禁止低分辨率放大);图集 ≤4096,超限分片或
  视频解码;解码内存 ≈ 宽×高×4。
- **交互 QA**:快速反向不闪烁(环形最短距离)、输入↔动画方向对应、reduced-motion 回退。
- **资源形式按需选**(decide):透明+<300帧→WebP 图集;长顺序滚动→可 seek 视频;
  高频随机+WebCodecs 目标→webcodecs;hover/click→多段短资源。
