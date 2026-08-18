---
name: hevi-hyperframes
version: "0.1.0"
description: Hevi 第二渲染运行时。HTML/GSAP 构图，缺 CLI 则逐卡回退出片。
argument-hint: "<topic>"
allowed-tools: Bash, Read
homepage: https://github.com/soffy88/hevi
license: MIT
user-invocable: true
---

# /hevi-hyperframes

Remotion 仍是默认装配。HyperFrames 管片头、花字、动效标题、网站转视频。

## 何时用

- 配方 `render_runtime: hyperframes`（`kinetic_promo`）
- 意图含片头 / 花字 / promo / kinetic
- Veya `render_runtime=hyperframes` 且 `execute=true`

## 调用

```bash
cd "$HEVI_ROOT" && uv run python -c "
import asyncio
from hevi.studio.tools import invoke_tool
print(asyncio.run(invoke_tool('runtime.hyperframes.compile', {'topic': '盐税'})).payload['html'][:200])
"
```

`runtime.select` 在配方未锁时按意图挑 Remotion / HyperFrames / Manim / ffmpeg。禁止静默换栈。

HTTP:`POST /api/studio/veya/produce` `{"line_id":"kinetic_promo","slots":{"topic":"…"},"execute":true}`
