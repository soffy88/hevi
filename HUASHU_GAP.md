# HUASHU_GAP.md — hevi 动效模块 vs huashu-motion 对比审计

## 1. 概述
本文档对比了 `hevi` 项目现有动效相关模块（含 TALKEDIT/SHOTLANG 已实现的动效卡片、逐字卡点、提示词/脚本生成等）与 `alchaincyf/huashu-motion` 提供的完整能力（动态单文件 HTML 引擎、OM 运行时、浏览器内点到即改收件箱架构、ABC记谱法配乐/真乐器合成音色、23种音效、20种运动语言、多核 Chrome 并行渲染与质检等）。

---

## 2. 能力对照表 (HUASHU_GAP)

| 能力维度 | `huashu-motion` 能力 | `hevi` 现有实现 (TALKEDIT / SHOTLANG / 现有动效) | 状态 (已有 / 部分 / 缺失) |
| :--- | :--- | :--- | :--- |
| **核心架构与单文件渲染** | 基于纯静态单文件 HTML/JS/CSS 构成的可渲染、可交互、带时间轴与播放器的动效引擎 (`runtime/om.js`, `runtime/om-player.js`) | `hevi-remotion` (Remotion) + 静态/动态 Web 组件，多采用 React 组件或服务端渲染管线，缺少统一轻量单文件打包分发 | **部分** (hevi 侧重 Remotion/Web，huashu 侧重纯单文件 HTML 轻量交付) |
| **浏览器内“点到即改” (Point-to-Edit)** | 浏览器内按 C 键点击任意画面元素，记录时间轴、元素选择器、源码位置，写入 `.om/inbox.jsonl` 供 Agent 增量修复 (`om inbox`, `om studio`) | `hevi-web` 控制台有各种 Console / Studio，但缺少专门针对时间轴/元素点击反向写入 Agent 收件箱的点到即改逆向调试闭环 | **缺失** |
| **作曲家模式与音频引擎** | 基于 ABC记谱法 的文本配乐、三角钢琴/弦乐/鼓组真乐器采样合成、12类产品兜底配乐、23种精细音效同步落地触发 (`om sound`, `om samples`) | `hevi` 拥有 `audio_master_clock_workflow.py` 及基础 TTS/音频，但缺少结构化 ABC 记谱配乐与精准帧对齐音效引擎 | **缺失** |
| **导演规则与运动语言库** | 20种量化运动语言（具备适用场景、节奏曲线、速度参数说明）、21支顶级发布片分析提炼的起步节奏单与镜头策略 | 有部分提示词与剧本生成 (`shotlang`)，但缺少系统化的 20 种运动语言标准库及发布片节奏单引擎 | **部分** |
| **多核并行渲染与质检** | 基于本地 Chrome 的多核并发截帧渲染、`om check` 脚本静态检查、`om qa` 成片抽帧质检 | 有 `visual_quality.py` 等视觉质量门禁 (`tests/test_visual_quality_gate.py`)，但缺少针对单文件动效网页的多核 Chrome 抽帧渲染和动效质检 | **部分** |
| **口播与逐字对齐** | 支持系统音色或 Kokoro 语音、whisper-cli 逐字对齐、说话时背景音乐自动让位 | TALKEDIT 实现了口播清理、鬼影/对齐脚本等 (`talkedit_clean.py`, `talkedit_ghost.py`)，具备基础口播及对齐能力 | **已有** |

---

## 3. 详细差距分析

1. **单文件交互与逆向收件箱 (`om inbox` / `om studio`)**:
   - `huashu-motion` 独有的亮点是浏览器编辑器实时预览与反向点击交互（点击画面直接生成结构化修改需求给 Agent）。`hevi` 现有前端虽然有丰富的 Studio 控制台，但缺少这种专为动效调试设计的轻量收件箱与点到即改协议。
2. **文本配乐与音效引擎 (`om sound`)**:
   - `hevi` 拥有强大的主时钟音频工作流，但没有集成 ABC 记谱法作曲与 23 种细粒度音效在动画触发点的精准绑定能力。
3. **运动语言与节奏单 (`library/`)**:
   - `huashu-motion` 的核心价值在于方法论（20种运动语言、节奏单生成逻辑）。`hevi` 可以直接将这些设计规范与运动模版引入自身的创意与导演模块 (`hevi/creative/shotlang` 或 `hevi/studio/recipes.py`)。
