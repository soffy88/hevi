---
name: motion-canvas
version: "0.1.0"
description: Motion Canvas 编程教学向代码动画线——TypeScript generator 剧本 + 自带 Code 代码块组件，顺序叙事讲代码/算法/概念。无头渲染走已验证路线：vite 编辑器服务 + headless Chromium 驱动 RENDER + @motion-canvas/ffmpeg exporter 出 MP4（ubuntu26 实测出片）。
argument-hint: "<教学主题/代码片段> [--project <工程目录>]"
allowed-tools: Bash, Read
homepage: https://motioncanvas.io/
license: MIT
user-invocable: true
---

# /motion-canvas

编程教学向动画线：用 TypeScript 按时间顺序写 generator 剧本（`yield*` 一行一步），
画面由代码自己"演"出来——代码块逐字出现/增删改、图形随代码同步变化。
适合讲一段代码怎么跑、一个算法怎么动、一组概念怎么推导。

上游 Motion Canvas（MIT，`@motion-canvas/*` 3.17.x）：场景画布 + 实时预览编辑器。
hevi 本 skill 只做三件事：脚手架、场景写作约定、无头渲染脚本。**不注册成能力**——
它是渲染器/创作线（同 HyperFrames 线的定位：skill + 脚本落地，出片走脚本，不走
capability registry）；批量编排若将来需要，再由编排层调 `tools/render.mjs`。

## 适用 / 不适用

| 场景 | 用本线？ |
| --- | --- |
| 编程教学：代码逐行讲解、代码改一处画面动一处 | ✅ 本线主场（`Code` 组件原生支持代码 diff 动画） |
| 算法/数据结构演示：排序、指针移动、状态机 | ✅ generator 顺序剧本最自然 |
| 概念推导：公式/图形随叙述逐步生长 | ✅ |
| 幼儿认知/绘本/故事片 | ❌ 走 kids / handdraw / storyfilm 线 |
| 真人镜头、AI 生成视频 | ❌ 走 PixStag 线（`video.pixstag_generate`） |
| HTML 花字/片头、GSAP 构图 | ❌ 走 HyperFrames 线（hevi-hyperframes skill） |
| 数学板书（LaTeX 级排版） | ❌ 走 Manim（character_animation 线在用） |

与 Remotion 的分工：Remotion 是 `f(frame)` 纯函数式、服务端渲染一等公民；
Motion Canvas 是顺序剧本式（写代码的顺序就是播放顺序），讲"过程"更顺手，
但**无头渲染不是官方一等公民**（见下节），批量/并发渲染别指望它。

## 无头渲染路线（ubuntu26 已验证，2026-10-20）

官方事实：Motion Canvas **没有无头渲染 CLI**。渲染发生在浏览器编辑器里
（`Renderer` 逐帧 seek + 读回 canvas），`@motion-canvas/ffmpeg` exporter 把帧流
POST 给 Vite dev server，由 Node 侧调 ffmpeg（`@ffmpeg-installer` 自带静态
ffmpeg）封装成 MP4。所谓"无头渲染"就是把这套编辑器流程用 headless
Chromium 自动驱动——`tools/render.mjs` 干的就是这件事：

```bash
# 前置：工程目录里已 npm install（见脚手架节）
node tools/render.mjs <工程目录> [--port 9017] [--timeout 300]
# 成功输出：RENDER OK: <工程>/output/project.mp4 (<bytes>, <时长>s, wall <s>s)
```

脚本流程：起 `vite --port <p> --strictPort`（端口被占自动 +1 重试 5 次）→
playwright-core 起 headless Chromium → 打开编辑器 → 在 VIDEO SETTINGS 的
Rendering 区把 exporter 的原生 `<select>` 选为 `Video (FFmpeg)` → 点
`Render` 按钮 → 等 `output/` 里的新 MP4 定稿（≥10KB、大小 5 秒不变、
且 ffprobe 能解析出时长——exporter 一开始只写 48 字节头，单看"大小稳定"
会误判完成）→ 关浏览器/服务。产物固定在 `<工程>/output/project.mp4`。

环境事实（ubuntu26 实测）：
- Node 在 nvm 下（`~/.nvm/versions/node/v26.4.0/bin`），登录 PATH 没有 node/npm，
  先 `export PATH=$HOME/.nvm/versions/node/v26.4.0/bin:$PATH`。
- **Chromium 必须用完整版，不能用 headless shell**：Playwright 缓存里的
  `chromium-*/chrome-linux64/chrome` 实测秒级渲完；`chrome-headless-shell`
  会把编辑器渲染循环节流到约 0.25 fps（1080p 下 8 分钟只渲出 6 秒片的
  4.07 秒）。脚本的探测顺序已按此写死，`MC_CHROMIUM` 可覆盖。
- vite 默认 9000 端口在该机常被其他服务占用，必须 `--strictPort` + 冷门端口。
- npm 11 会拦截 postinstall 脚本（esbuild / @ffmpeg-installer 报 allow-scripts
  警告）——实测两者二进制均可直接运行，不影响 vite 与 ffmpeg exporter。
- 渲染帧率：编辑器 Rendering 默认 60 FPS（3.17），与场景时间轴的帧率无关，
  片长不变、帧数翻倍；教学片可在 VIDEO SETTINGS 里改 30，本脚本不改此项。
- 字体：代码块默认字体 JetBrains Mono 该机未装，画布自动回退；
  场景里显式写 `fontFamily: 'monospace'` 走 DejaVu Sans Mono 最稳。
  中文走 Noto Sans CJK / SimHei（该机已装）。

验证证据（demo 工程，见 examples 节）：6.02 秒、1920×1080、h264、
361 帧（60 FPS 渲染）、145,046 字节；抽帧核对：1.0s 为注释行 + 小蓝圆，
5.5s 为完整 4 行高亮代码 + 放大变红右移的圆 + 字幕。脚本端到端墙钟
17.7 秒（含 vite 冷启 + 浏览器启动 + 逐帧渲染 + 定稿等待）。

## 脚手架

```bash
bash tools/scaffold.sh <目标目录> [工程名]
# 等价官方命令（create 3.17.2 支持 minimist 参数覆盖 prompts，可全非交互）：
#   npm create @motion-canvas@latest -- --name <名> --path <目录> \
#       --language ts --plugins ffmpeg
# 然后 npm install，并补两个无头渲染/代码高亮依赖：
#   npm i @lezer/javascript && npm i -D playwright-core
```

脚手架产物即官方 template-2d-ts + `@motion-canvas/ffmpeg` 插件版
vite.config.ts。**node_modules（约 274MB）不进 hevi 仓库**；工程放在
`~/projects/_refs/` 或任务自己的工作区，首次使用先 `npm install`（约 20 秒）。

## 写场景

工程结构：`src/project.ts`（`makeProject({scenes: [...]})`）+
`src/scenes/*.tsx`（每镜一个 `makeScene2D` generator）。要点：

- 时间即代码顺序：`yield* a().scale(2, 1.2)` 等这步播完才走下一步；
  并行用 `all(...)`，延迟用 `waitFor(s)`，串行片段用 `chain/sequence`。
- 代码块用新 `Code` 组件（旧 `CodeBlock` 在 3.17 已从包根导出移除、且标记
  deprecated，不要用）：

  ```tsx
  import {Code, LezerHighlighter, makeScene2D} from '@motion-canvas/2d';
  import {parser} from '@lezer/javascript';
  Code.defaultHighlighter = new LezerHighlighter(parser); // 需 @lezer/javascript

  // 场景里：对 code 信号 tween 即是"打字/改代码"动画（自动 diff）
  yield* code().code(`const x = 1;\nx += 41;`, 1.8);
  // 精细编辑用 edit()/insert()/remove()/replace() 片段 API（见官方 Code 文档）
  ```

- 图形/文字节点（`Circle/Rect/Txt/Line` 等）都是信号驱动：
  `circle().fill('#e13238', 1.2)`、`position.x(690, 1.2)` 这类链式 tween。
- 分辨率/帧率：默认 1920×1080@30；教学片保持 16:9。改尺寸在
  `makeProject({...})` 或编辑器 VIDEO SETTINGS（渲染脚本按默认全幅全帧渲染）。
- 场景时长由 generator 总时长决定；渲染前在编辑器时间轴核对总帧数。

可跑的 demo 工程：`~/projects/_refs/motion-canvas-demo/`（官方脚手架 +
`src/scenes/example.tsx`：Code 打字增删 + Circle 缩放/变色/位移，6 秒）；
其场景源码同时存了一份在本 skill 的 `examples/example.tsx` 供抄写。

## 纪律

- 零付费：全部依赖走 npm 官方 registry，本地渲染，无任何按次计费接口。
- 渲染是浏览器逐帧回放，时长≈片长量级（分钟级片子按分钟等），
  `--timeout` 给足；不要并行起多个渲染抢同一端口/同一 output 目录。
- 渲染产物只认 `output/` 里新出现且大小稳定的 MP4；脚本失败会打印
  pageerror，不要拿图片序列或截图冒充成片。
- 工程与 node_modules 放仓库外（`~/projects/_refs/` 或任务工作区）；
  本 skill 目录只放 SKILL.md + tools 脚本 + examples 源码。
