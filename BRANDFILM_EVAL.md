# BRANDFILM 单元调研与评估报告 (BRANDFILM_EVAL.md)

本报告针对将 `code-brand-film`（MIT, nutllwhy）内化为 Hevi 的 CPU「15 秒品牌片」流水线（`line=brandfilm`）进行系统评估与架构设计。

---

## 1. 上游流水线解构

上游 `code-brand-film` 是针对 15 秒商业品牌宣传片/产品动效设计的 Agent Skill 与全代码生成管线，核心由五个阶段组成：

1. **资产规划与分镜先行 (Pre-production)**：
   - 规定在写任何代码前，必须先生成 `shot-list.md` 与 `copy.md`。
   - `shot-list.md` 采用五幕架构（S1 钩子 0-3s，S2 拆解 3-6s，S3 运转 6-9.5s，S4 交付 9.5-12.5s，S5 拍板 12.5-15s）。每幕必须包含 $\ge 5$ 个具名事件、具名摄影机运动（`.cam` 变换）、非淡入淡出转场机制、三层深度（背景/中景/前景），且必须有 $\ge 2$ 幕展示真实产品行为界面。
   - `copy.md` 逐行登记屏幕文案与其真实来源（Brief / 官网 / UI / 数据），禁止未经标注的主观杜撰。

2. **单页 HTML + GSAP 补间时间轴 (Core Composition)**：
   - 生成单页静态 HTML (`film/index.html`)，挂载于根容器 `[data-composition-id][data-duration="15"]`。
   - 动画逻辑封装在全局暂停的 GSAP 时间轴中：`window.__timelines[id] = gsap.timeline({ paused: true });`。
   - 严格的三层视觉树分离：
     - 外层 `.scene` 控制幕的透明度进出；
     - 中间层 `.cam` 控制 2D/3D 摄影机运镜（`scale`, `x`, `y`, `rotation`）；
     - 内层 `.scene-inner` 承载具体组件。
   - 初始隐藏状态写在 CSS（避免首帧闪烁与叠印），严禁在时间轴中调用 `Math.random()`（确保非顺序 seek 时的确定性）。

3. **逐帧驱动与光栅化渲染 (Renderer)**：
   - 上游以 [HyperFrames](https://github.com/heygen-com/hyperframes) 作为渲染后端，通过 headless 浏览器逐帧步进 GSAP 时间轴，捕获屏幕画面并通过 ffmpeg 编码为无声 H.264 MP4。

4. **节拍对齐的合成原创配乐 (Algorithmic Scoring)**：
   - `scripts/score_lib.py` 提供纯 Python / numpy 实现的加法合成器（Additive synthesis）、卷积混响（FFT Reverb）与软剪切母带处理，零采样文件依赖，零版权风险。
   - `score.py` 基于画面的动作切点（Cut points）计算 BPM 网格，乐器事件（底鼓 Kick、拍频 Pluck、打字音 Tick、拍板 Boom、打击乐铃声 Bell）纳秒级对齐画面关键帧。
   - 最终通过 ffmpeg `adelay` + `amix` + `loudnorm` 双遍响度归一化（$-14$ LUFS），与无声视频流合成最终成片。

5. **三道严苛质量闸门 (Three Quality Gates)**：
   - **代码闸门 (`scripts/film_audit.py`)**：静态 AST/正则审查 HTML 与 JS，强制检查量化地板（$\ge 90$ 非填充 tweens、$\ge 8$ 种进场机制、$\ge 2$ 种非淡入转场、$\ge 8$ 种缓动、$\ge 8$ 次摄影机运动、每幕 $\ge 5$ 事件、真实字体文件、真实矢量 Logo、无 PPT 式页码/进度条）。
   - **摆位闸门 (`scripts/layout_audit.mjs`)**：在 Headless 浏览器中每 0.1s 步进并实测 DOM 空间关系，精准捕获文字被遮挡（Text Hidden）、文字重叠碰撞（Text Collision）、文字边缘截断（Text Clipped）、48px 安全区违规（Safe Area）、静止半悬卡片（Parked off-edge）及角标台标违规（Corner Logo）。
   - **像素闸门 (`scripts/frame_audit.py`)**：实测渲染后 MP4 的灰度直方图与边缘梯度，保证中位数非背景画面覆盖率 $\ge 0.065$、边缘细节率 $\ge 0.065$、帧间运动率 $\ge 0.025$、最长静止时长 $\le 2.5$s、最薄弱幕覆盖率 $\ge 0.04$。
   - 规则：**三道闸门必须全部 0 failed 才能交付**。

---

## 2. HyperFrames 在 CPU Headless Chromium 的可行性评估

### 2.1 调研结论与实测验证
在当前受限环境（12th Gen Intel Core i7-12700KF 20 核心 CPU，无可用硬件 GPU）下，经过对上游示例 `examples/office-agent` 的真实端到端渲染测试，验证结论如下：

1. **CPU 渲染完全可用**：
   - HyperFrames (v0.8.149 / v0.8.152) 内置的 Chrome Headless Shell 可在 CPU 模式下通过 SwiftShader (CPU 软件光栅) 稳定运行。
   - 运行参数 `hyperframes render . -q draft --fps 30 -o output.mp4`，15 秒（450 帧 @ 1920×1080）渲染总耗时约 60 秒至 120 秒，平均帧渲染耗时约 120ms，完全满足离线批处理与 CI 要求。
   - 渲染出的视频流通过 `frame_audit.py` 检验：覆盖率 0.066、细节率 0.087、运动率 0.029，全部 PASS。

2. **画面输出确定性（Determinism）实测**：
   - 在相同环境和固定配置下对同一工程独立渲染两次：
     - 第一次渲染帧哈希：`framemd5 = 44fa8c320047fa321dbece83fc6e5cc1`
     - 第二次渲染帧哈希：`framemd5 = 44fa8c320047fa321dbece83fc6e5cc1`
   - 证明 CPU 软件光栅具备位级别（Bit-exact）的可复现性与确定性。

3. **环境适配关键点 (Linux 沙箱限制)**：
   - 上游原生 `scripts/layout_audit.mjs` 中调用 `puppeteer.launch` 时仅传入了 `['--allow-file-access-from-files', '--disable-web-security']`。
   - 在现代 Linux (Ubuntu 24.04+ / AppArmor 用户命名空间受限环境) 下，Headless Chromium 启动会因缺少 SUID sandbox 报错 `No usable sandbox` 崩溃。
   - **适配修复**：必须在 launch args 中补充 `'--no-sandbox'` 与 `'--disable-dev-shm-usage'`，修复后 Headless 摆位探测完全正常通过（0 failed）。

### 2.2 双引擎设计与 Playwright 回退方案
虽然 HyperFrames 原生支持 CPU 运行，但考虑到 Hevi 系统的自主可控性与轻量化部署，Hevi 将设计双引擎架构：
- **主引擎 (Engine A: HyperFrames)**：用于标准生产，调用系统全局 HyperFrames CLI 渲染。
- **回退引擎 (Engine B: Hevi Playwright Native)**：参照 `scene3d` 的成熟做法（`hevi/layer4_legacy/scene3d/renderer.py`），利用 Python `playwright` 驱动 Chromium，注入 `window.__setTime(t)` 逐帧调用 GSAP `tl.seek(t, false)`，通过 `page.screenshot()` 截帧后直接调用 ffmpeg H.264 编码。该路径完全摆脱外置 CLI 封装，作为健壮的保底方案。

---

## 3. 与 Hevi 现有相关资产的重叠与差异

| 维度 | `brandfilm` (本单元) | `artmotion` (huashu) | `amtpl` (motion-templates) | `amrules` (aimotion-rules) | `sfxbad` |
|---|---|---|---|---|---|
| **核心定位** | 15秒商业品牌/广告片 | 20-40秒知识解说动画 | 单 HTML 参数化动效卡片 | 动效通用提示词与校验规则 | 基础音效库与质量破坏集 |
| **画面载体** | DOM/CSS + GSAP 时间轴 | SVG/Canvas/Manim/DOM 混排 | 单 Canvas 2D `draw(t)` | 抽象分镜 JSON / 视频流 | 无画面 / 损坏测试视频 |
| **内容驱动** | 品牌卖点、产品行为、大字动效 | 深度解说长文案、语音对齐 | JSON Spec 数据状态连续变换 | 规则卡清单（8条以上） | 坏片特征标记 (Manifest) |
| **音频模式** | Python 纯算法合成配乐（切点卡拍） | 本地 TTS 旁白 + ASR 时间戳 | 可选背景音频轨 | 转场与 BPM 网格约束 | $\ge 60$ 种离散合成音效 |
| **质量控制** | 三道硬性闸门（代码/布局/像素） | 交付红绿灯评分体系 | Canvas 文本越界测试 | 静态 AST Lint + 闪烁检测 | 物理缺陷检测回归 |
| **重叠点** | 均采用 CPU 软件光栅化渲染，强调确定性与无状态 seek。 | | | | |

**与 `amtpl` 的关键技术交叉**：
- `amtpl` 目前的测试仅依靠 Canvas 的 `measureText` 检查文本是否超出画布，无法感知由于图层重叠导致的视觉碰撞或被实体背景块遮挡。
- 本单元将 `layout_audit.mjs` 中的文字图层 hit-testing、轴对齐包围盒 (AABB) 碰撞与重叠率算法抽象为通用模块，反哺给 `amtpl` 做真实文字遮挡/碰撞校验。

---

## 4. 依赖管理、Vendoring 边界与第三方许可证合规

### 4.1 可 Vendor 资产清单
以下文件从上游 `/data/soffy/refs/code-brand-film` 内化至 `hevi/layer4_legacy/brandfilm/`：
- `LICENSE`：原作者 MIT 许可证；
- `THIRD_PARTY_NOTICES.md`：上游第三方声明；
- `references/*.md`：分镜、动效配方、质检基准等文档（9篇）；
- `scripts/*.py, scripts/*.mjs, scripts/*.sh`：三道质检闸门、字体裁剪、合成配乐库；
- `examples/office-agent/`：完整可渲染参考片工程（含 `film/`, `src/`, `audio/`, `shot-list.md`, `copy.md`, `assets.md`）。

### 4.2 第三方许可证合规处理策略

1. **上游原创代码 (MIT License)**：
   - 归属作者 `nutllwhy (2026)`，保持原有版权头与 MIT LICENSE 文本不变；
   - 在 `docs/third_party/provenance-ledger.yaml` 中登记源地址、许可与用途。

2. **中文字体 (Noto Sans SC / Noto Serif SC)**：
   - 遵循 **SIL Open Font License 1.1 (OFL)**。
   - 上游已通过 `fetch_cjk_fonts.sh` 将字体针对每部片子实际使用的汉字进行了精简子集化（体积仅约 26KB-34KB）。子集化后的 woff2 字体保留 OFL 说明，允许随工程内嵌分发。

3. **动画核心库 (GSAP)**：
   - 遵循 **GSAP Standard License**。
   - 上游在 HTML 中采用 CDN 引入（`https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js`），不作为源码修改，避免分发冲突。
   - 为确保在无网络或内网离线环境下的确定性，流水线支持本地 fallback 缓存（放置在 `vendor/gsap/` 下并保留官方 License 注释）。

4. **品牌与产品资产**：
   - 原作示例中的 `logo.svg` 等资产仅作为 Office Agent 虚构产品的示例占位符；
   - 在 Hevi 的生产线中，E2E 样片采用虚构品牌「Hevi 视频工厂」，使用纯自主绘制的高标准矢量 SVG Logo，不使用任何未授权的外部商业素材。

---

## 5. 结论与执行计划

1. **Step 1 完成**：确认上游全流程、验证 CPU 渲染与确定性可行、明确与其他动效模块的边界、确立合规策略。
2. **下一步执行**：
   - 将上游代码导入 `hevi/layer4_legacy/brandfilm/` 并更新 `provenance-ledger.yaml`；
   - 运行并打通 `examples/office-agent` 渲染与三道闸门（0 failed）；
   - 构建 `line=brandfilm` 模块化流水线，支持 16:9 与 9:16 自适应排版；
   - 抽取通用布局文字闸门供 `amtpl` 复用测试；
   - 产出「Hevi 视频工厂」横竖屏两部真实样片与全量测试。
