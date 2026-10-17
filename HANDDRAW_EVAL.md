# HANDDRAW 技术调研与集成评估（sweety-handdraw-video v1.2.3）

## 1. 上游流水线各阶段分解

上游 `sweety-handdraw-video` (v1.2.3) 是一个基于 Python / Pillow / SciPy / FFmpeg 实现的确定性手绘视频渲染管线。其核心原则是**整篇声音先行，画面适配声音**，包含以下连续阶段：

1. **创作与分镜设计 (Design & Storyboard)**
   - 输入：主题、文章或既有讲解稿。
   - 产出：`design.json`、`job.json` 以及分镜结构（页面与 beat 序列）。
   - 逻辑：按因果关系安排生活常见错误、概念、机制与收束；每页包含若干 beats，每个 beat 绑定台词与可视动作（文本手写、画笔标记、插画绘制）。
2. **可选制作设置与画风解析 (Production Options & Style Selection)**
   - 风格选择器（20 款风格目录）、手部选择（6 款手部 + pen-only 纯笔）、笔杆文字与浮动水印。
   - 画风解析写入 `style/resolved.json`，出图前必须有 `drawing-plan.json` 及其预检。
3. **整篇旁白先行与母带锁定 (Continuous Narration Master & Alignment)**
   - 采用整篇口播稿一次性合成完整 WAV，不按镜头切片，保留自然语流与换气。
   - 生成后核对 SHA-256 并提取逐 beat / 逐句的时间戳对齐文件（`alignment.json`）。
   - 旁白母带绝对锁定，后续分镜、动画节奏与字幕完全由母带的时间戳驱动。
4. **插画骨骼化与语义部位分拆 (Illustration Skeletons & Semantic Parts)**
   - 每个主体划分为有序语义部位（如 head → neck → torso → left_arm → right_arm → lower_body）。
   - `thin_ink` (中轴骨架化) + `trace_strokes` (邻接图连通分支追踪) 提取黑白/深色轮廓的矢量笔划路径。
   - 区域填色（`build_painting`）按同一部位顺序计算刷涂路径与覆盖时间戳。
   - 生成 `.npz` 时间图（`ink` 轮廓时序通道与 `color` 刷色时序通道，按 $250\times$ 渐变显影）。
5. **笔尖运动与手部贴合 (Paint Motion & Hand Tracking)**
   - 依据时间戳在路径上的插值计算笔尖位置 $(x, y)$。
   - 手部素材通过校准的笔尖锚点（`nib`）与比例贴合在笔尖位置，手腕/前臂边缘在画外延伸，避免断肢暴露。
   - 笔划之间抬笔（travel）平滑过渡。
6. **字幕与片尾排版 (Subtitles & Ending)**
   - 字幕排版（`caption_assets.py`）采用独立清晰字体（白字黑边或深色底板），严格单行或受控双行居中，不破坏词义。
   - 交付硬门槛：整片同一时刻只允许一套字幕，禁止烘焙字幕与外挂字幕轨并存。
   - 固定封面 1.0 秒（前 0.5 秒静止，后 0.5 秒渐隐），末句后保留阅读停留与淡出。
7. **逐帧光栅化合成与音画混流 (Frame Rasterization & FFmpeg Encoding)**
   - Python 逐帧合成背景底纸、插画显影、手写文字、手部叠加、静态字幕与浮动水印。
   - 通过管道喂给 `ffmpeg -f rawvideo -pix_fmt rgb24 -c:v libx264 -crf 18 -pix_fmt yuv420p`。
   - 音轨经 `loudnorm` 响度归一化至 $-17 \pm 3$ LUFS，与视频对齐封装。
8. **工程与质量闸门核验 (Verification & Finalize)**
   - `video_verifier.py`：单调递增性、无未覆盖像素、笔尖距离限制、音画时长一致、响度范围检测、完整 H.264/AAC 解码自检。

---

## 2. 哪些组件可以直接 Vendor，哪些必须替换

### 2.1 可以直接 Vendor 的核心组件
上游遵循 MIT 许可证，以下无模型依赖、纯算法与渲染逻辑可完整保留或直接搬迁至 `hevi/layer4_legacy/handdraw/`：
- **`stroke_paths.py`**：纯 NumPy 实现的快速 Zhang-Suen 细化骨架提取算法与笔划拓扑链追踪。
- **`paint_motion.py`**：基于 SciPy 距离变换的主方向刷色算法、抬笔移动与显影时间图生成。
- **`stroke_assets.py`**：文字字形笔划测量、高亮/下划线笔刷生成、插画分部位图层与轮廓时序构建。
- **`caption_assets.py`**：字幕测量、自动换行与安全边距排版。
- **`watermark_assets.py`**：柔和浮动文字水印生成与三角函数漂移动态。
- **`timeline_contract.py`**、**`subtitle_contract.py`**：时间线单手规则、封面规则与单套字幕契约校验。
- **`video_job.py` / `video_renderer.py` / `video_verifier.py`**：工程构建编排、逐帧管道渲染器与工程验证器。
- **手部资产规范与资产**：`assets/hands/catalog.json` 中的锚点几何描述，以及 `pen-only` 与 `navy`（深蓝袖马克笔）手部位图。

### 2.2 必须替换的两处核心依赖

| 环节 | 上游方案 | Hevi 替换方案 | 替换理由与落地策略 |
| :--- | :--- | :--- | :--- |
| **生图来源** | Codex / 云端生图 API + 强交互美术指导 (`sweety-image-art-direction`) | **CPU Keyframe / 确定性插画渲染器 (Style Presets + 本地素材)** | 遵照零付费 API 与 CPU-only 硬规则。开发专用 CPU 插画生成器，依据国风水墨/极简线条/淡彩速写/墨线绘本等 style_presets 生成带透明通道和明确部位多边形的插画素材，或导入本地合规素材。 |
| **配音引擎** | VoxCPM2 MLX (Apple Silicon 专属) 或 VoiceStudio (本地 3900 服务) | **CosyVoice (`127.0.0.1:17600`)，piper 本地离线兜底** | 生产环境为 Linux CPU，利用已就绪的本地 `hevi-gen-engine` CosyVoice 接口（内置 `builtin:zh_default` 参考音）进行全篇旁白母带合成；当 CosyVoice 不可用时无缝降级到本地 CPU piper (`zh_CN-huayan-medium.onnx`)。结合静音频谱/ASR 对齐获取精确到每个 beat 的时间戳。 |

---

## 3. 五项内置依赖的许可证核验

上游在 `dependencies/` 内置了 5 项制作资料与规范快照。经核验全部为宽松的开源协议（MIT），无 GPL 或传染性条款：

| 依赖名称 | 上游固定版本 / 快照 | 许可证 | 商业使用与衍生说明 |
| :--- | :--- | :--- | :--- |
| **`huashu-art-motion`** | `9ff59339f934e08483ba0a5b1db20f4c2c421b35` (alchaincyf) | **MIT License** | 原著作权属于花叔 (花生)，允许商业闭源集成与修改，需保留版权声明。 |
| **`omniailab-ai-director`** | `772a1477cd436dd8d9fdff60e626a0338ff2f682` (tomatoparkdao) | **MIT License** | 原著作权属于 OmniAiLab (Mochiball)，提供叙事与导演分镜设计规范，允许任意再分发。 |
| **`hand-drawn-styles`** | `4132988b8596bfa36321c970a4472d4e3bb25d96` (threerocks / liulei) | **MIT License** | 20 款手绘风格配方与提示词规范，允许修改与内置。 |
| **`sweety-image-art-direction`** | 入口 SHA-256 `fbbfd33d...` (threerocks) | **MIT License** | 图像美术指导与门禁规范，允许商业闭源集成。 |
| **`sweety-image-privacy`** | v1.1.0 锁定快照 (threerocks) | **MIT License** | 隐私清理与相机元数据剥离工具，宽松 MIT 许可。 |

全部 5 项依赖均登记入 `docs/third_party/provenance-ledger.yaml`，并在 `hevi/layer4_legacy/handdraw/` 根部保留 `LICENSE` 与 `THIRD_PARTY_NOTICES.md`。

---

## 4. 与 Hevi 现有体系的重叠与差异

| 维度 | Hevi 现有 `artmotion` 路线 (花叔动效/Remotion) | Hevi `stickdir` (火柴人简笔画概念) | Hevi `talkcraft` (口播音画对齐) | 新化入的 `handdraw` (手绘手写线) |
| :--- | :--- | :--- | :--- | :--- |
| **渲染宿主** | Node.js / Remotion / CSS 关键帧 / 浏览器无头渲染 | 早期原型 / SVG 几何骨架 | 纯 Python 音频切片与对齐 | **纯 Python / Pillow / SciPy / FFmpeg**（零浏览器、零 Node 依赖） |
| **核心视觉动效** | 卡片翻转、图表展开、动效排版 | 简单折线运动、无手臂物理遮挡 | 无（仅输出音轨及对其时间轴） | **逐笔中轴描线、同序笔刷填色、逐字手写、真实手臂/画笔跟随遮挡** |
| **画面与音频时钟关系** | 多数按字数预估固定时长，后拉伸音频或切片 | 固定节拍时间轴 | 声音为主导，ASR 生成对齐数据 | **整篇声音先行锁定绝对时间轴，画面元素动作依音频动态计算伸缩** |
| **生图与美术依赖** | Remotion SVG 或文生图卡片 | 纯矢量预设 | 无图 | **CPU 确定性矢量/分层渲染，提取部位并中轴骨架化** |
| **算力与运行开销** | 需启动 Chromium，内存开销大 | 极轻量但表现力单一 | 纯 CPU ASR/TTS | **纯 CPU 矩阵运算，无 GPU 依赖，内存小，跨平台确定性高** |
| **字幕系统** | Remotion DOM 字幕，容易出现双层重叠 | 简易 SVG 文本 | 外挂 SRT / VTT | **静态像素级单套烧录字幕，物理禁止双字幕与溢出断词** |

### 协同与重用点
- **口播分镜层**：可复用 Hevi 既有的 `director` 或 `script2video` 结构化长文本，一键转为 handdraw 的 `pages` + `beats` 结构。
- **声音层**：复用 Hevi 的 `CosyVoice` 客户端与 `piper` 离线 fallback，省去多套 TTS 部署维护。
- **验证层**：Handdraw 的严格质量门禁（单调递增、物理描线检验、单套字幕、响度归一化）补充了 Hevi 在离线交付物校验上的硬约束。
