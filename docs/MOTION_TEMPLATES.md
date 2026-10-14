# Hevi 确定性纯函数动效模板 (Motion Templates)

本文档说明 Hevi 动效模板架构、模板参数规范、技术来源署名以及接入 `hevi-fxreg` 统一模板注册表的实施方案。

---

## 1. 架构总览

针对 AI 短视频生成中常见的画面幻觉、时间轴漂移、CSS 动画不可逐帧 Seek、多宽高比裁切变形等痛点，Hevi 动效模板系统落地了一套**纯代码驱动的确定性动效引擎**：

1. **单 HTML + 单 Canvas + 纯函数 `draw(t)`**：
   - 模板没有 CSS transitions/animations，没有 `requestAnimationFrame`，没有 `setTimeout`/`setInterval`，也没有任何跨帧累积的可变状态。
   - 画面是浮点秒数时间戳 $t$ 的纯函数：`draw(t)` 在任意时刻 Seek，均输出确定性的像素结果。
2. **闭式弹簧 (Closed-Form Spring) 数学核心**：
   - 动画过渡均基于二阶无状态阻尼谐振子阶跃响应解析解：
     $$s(\tau) = 1 - e^{-\zeta \omega_n \tau} \left( \cos(\omega_d \tau) + \frac{\zeta}{\sqrt{1-\zeta^2}} \sin(\omega_d \tau) \right)$$
     其中 $\zeta = 0.82$ 带来高质感的微量受控过冲（< 2%），无生硬顿挫与卡通晃动。
   - 多目标状态变迁基于线性时不变系统（LTI）叠加原理：
     $$y(t) = y_0 + \sum_{k: t \ge t_k} \Delta y_k \cdot s(t - t_k)$$
     无需逐帧积分，支持任意时间点 $O(K)$ 复杂度直接求解。
3. **Headless Chromium + ffmpeg 逐帧渲染管线**：
   - Playwright 控制 Headless Chromium 逐帧调用 `draw(t)` 抓取 PNG 截图缓冲。
   - 管道流入 ffmpeg 编码为标准 `libx264`、`yuv420p` 广播级 MP4。
   - 渲染前先行生成 3×3 抽帧 Contact Sheet 网格图（`_contact.png`），便于快速审片与布局排查。
4. **多宽高比原生排版**：
   - 竖屏 `9:16` (1080×1920) 为主设计；同时自适应支持横屏 `16:9` (1920×1080) 与方形 `1:1` (1080×1080)。
   - 原生响应式布局，非粗暴黑边填充或主体裁切。
5. **严苛安全规范与禁项清单**：
   - 严格遵循禁项清单：禁 shockwave、禁粒子爆发、禁 RGB split、禁镜头抖动、禁 lens flare、禁霓虹辉光、禁网格地板、禁闪烁背景、禁 bouncy easing、禁大面积蓝紫、**禁屏上中文句号（"。"）**。

---

## 2. 模板清单与参数规范

### 2.1 B1 `morph_ui` (单形状连续形变模板)
- **模板文件**：`hevi/motion_templates/templates/morph_ui.html`
- **设计范式**：整片由一个容器几何形状贯穿始终，无硬切。通过 size、radius、border 与 color 的连续形变串联 5–8 个 UI 状态。
- **进出时序**：旧内容在容器形变前 0.2s 淡出，容器在形变窗口（~0.35s）伴随微量短模糊（< 4.5px），新内容在容器形变展开后 0.18s 淡入展开；屏幕配有平滑虚拟光标执行点击与拖拽。
- **JSON Spec 结构**：
```json
{
  "title": "智能视频生成流水线",
  "bpm": 120,
  "duration": 10.0,
  "states": [
    {
      "id": "btn_init",
      "type": "button",
      "title": "启动智能成片引擎",
      "badge": "INITIALIZE",
      "accent": "#f59e0b",
      "duration_beats": 4
    },
    {
      "id": "progress_parse",
      "type": "progress",
      "title": "脚本解析与分镜语义分解",
      "badge": "ANALYZING 88%",
      "progress": 0.88,
      "accent": "#10b981",
      "duration_beats": 4
    },
    {
      "id": "stat_shots",
      "type": "metric",
      "title": "原子镜头规划就绪",
      "badge": "SHOTS: 18 / 18",
      "value": "18",
      "unit": "CLIPS",
      "accent": "#38bdf8",
      "duration_beats": 4
    },
    {
      "id": "chart_render",
      "type": "chart",
      "title": "算力调度与并行渲染",
      "badge": "THROUGHPUT",
      "bars": [0.45, 0.72, 0.95, 0.84, 0.62],
      "accent": "#f59e0b",
      "duration_beats": 4
    },
    {
      "id": "player_preview",
      "type": "player",
      "title": "4K 原生画质实时预览",
      "badge": "PREVIEW 60FPS",
      "playhead": 0.75,
      "accent": "#e11d48",
      "duration_beats": 4
    }
  ]
}
```

### 2.2 B2 `timeline_explainer` (线稿风时间轴/知识讲解模板)
- **模板文件**：`hevi/motion_templates/templates/timeline_explainer.html`
- **设计范式**：技术蓝图线稿质感（Line-art Technical Blueprint），竖直/水平坐标轴驱动，时间游标下行平滑点亮里程碑节点，横向引出展开信息卡片。
- **排版与安全区约束**：中英双语文字，中文基于 `ctx.measureText` 动态计算折行，杜绝生硬截断与破词；严格遵循安全区边距（水平边距 $\ge 80\text{px}$，垂直边距 $\ge 160\text{px}$）。
- **音频支持**：可接收外部旁白音频 WAV 文件并按标记时间戳对齐，无音频输入时亦能纯粹依靠时间步长独立出片。
- **JSON Spec 结构**：
```json
{
  "title": "AI 视频模型技术演进史",
  "title_en": "Evolution of Generative Video Architecture",
  "duration": 10.0,
  "bpm": 120,
  "milestones": [
    {
      "index": "01",
      "year": "2023",
      "title_zh": "时空解耦注意力机制突破",
      "title_en": "Spatio-Temporal Decoupled Attention",
      "desc_zh": "在空间自注意力后引入一维时间注意力，使视频潜空间帧间连贯性获得质的跃升",
      "desc_en": "Introducing 1D temporal attention enabled radical temporal coherence in latent space",
      "accent": "#f59e0b"
    }
  ]
}
```

### 2.3 B4 `kinetic_lyrics` (动态歌词/卡点字排模板)
- **模板文件**：`hevi/motion_templates/templates/kinetic_lyrics.html`
- **设计范式**：按 BPM 网格严密对齐（如 120 BPM 下每拍恰为 0.5s），每拍触发独立画面事件。文字采用冲拳式冲击力（Punchy impact，微量超调回弹），支持 `center_punch`、`split_box`、`ticker_stack` 三种动态字排形态，底部配有 16 分音符网格音阶游标。
- **音频合成**：内置音频混流接口，可载入律动音轨或卡点伴奏同步输出。spec 的 `audio` 指向 `assets/audio/beat_120bpm_click.wav`；由于 `*.wav` 被 `.gitignore` 过滤，渲染器在文件缺失时会自动用 ffmpeg lavfi `aevalsrc` 现场合成确定性 120 BPM click 音轨（相同参数逐字节一致）。也可手动生成：
  ```bash
  PYTHONPATH=$PWD .venv/bin/python scripts/gen_motion_template_audio.py \
      --bpm 120 --duration 10 --out assets/audio/beat_120bpm_click.wav
  ```
- **JSON Spec 结构**：
```json
{
  "title": "代码律动 // 纯函数动效",
  "bpm": 120,
  "duration": 10.0,
  "accent": "#f59e0b",
  "audio": "assets/audio/beat_120bpm_click.wav",
  "phrases": [
    {
      "start_beat": 0,
      "beats_count": 4,
      "words": ["灵感", "触发", "毫秒", "对齐"],
      "subtext": "INSTANT INSPIRATION // SUB-FRAME PRECISION",
      "accent": "#f59e0b",
      "layout": "center_punch"
    }
  ]
}
```

### 2.4 B3 `layer_build` (分层揭示/建造类 B-roll 模板)
- **模板文件**：`hevi/motion_templates/templates/layer_build.html`
- **设计范式**：2.5D 等轴测（Isometric Axonometric）多层分级展开。各层平台沿 Z 轴以闭式弹簧受控下落降落卡位，连接支柱自动吸附对接，右侧引出数据指标与技术架构标牌。
- **JSON Spec 结构**：
```json
{
  "title": "多模态成片架构分层建造",
  "title_en": "System Architecture Layered Assembly",
  "duration": 10.0,
  "bpm": 120,
  "layers": [
    {
      "id": "substrate",
      "name_zh": "数据底座与素材接入层",
      "name_en": "L1: Asset & Substrate Layer",
      "tag": "SUBSTRATE",
      "accent": "#f59e0b",
      "stat": "100+ Multi-format Assets"
    }
  ]
}
```

---

## 3. 技术来源署名与版权合规声明

根据 Hevi 版权边界规范，本项目**不复制、不引用、不 vendor 任何第三方作者的作品源码或画面素材**。我们仅借鉴吸收其设计范式（如单一 `draw(t)`、闭式弹簧阶跃响应、BPM 网格同步、Contact Sheet 抽帧流水线），所有 HTML、JS 库与 Python 代码均为全新自主编写。

对 awesome-ai-motion 中的优秀参考案例署名如下：

1. **Case 2103483957266268381** — *MakerMap 连续产品旅程* (作者: Julian Anderson / @juliancanderson)
   - 借鉴点：单 HTML、单 Canvas、单 `draw(t)`、闭式弹簧阶跃响应叠加原理（LTI superposition）、3×3 Contact Sheet 先检后全渲流水线。
2. **Case 2103273003555402193** — *一个形状串起整套 UI*
   - 借鉴点：同一元素靠 size/radius/color 连续形变串起 UI 旅程，文字在形变开始后进、下次形变前出的时序规范。
3. **Case 2102554209166000267** — *节拍同步产品动效广告* (作者: Praveen / @praveen)
   - 借鉴点：120 BPM 网格硬对齐，禁项清单（禁 shockwave、粒子、霓虹辉光、网格地板、闪烁背景、bouncy easing、屏上句号）。
4. **Case 2102463796149440888** — *Claude 模型发展时间线* & **Case 2102844654169575547** — *Attention 到 AGI 简史*
   - 借鉴点：纵向里程碑时间轴展开，线稿图表与双语字幕规范。
5. **Case 2109087249572749553** — *Turn It Up Now 动态歌词* (作者: klöss / @kloss_xyz)
   - 借鉴点：动态文字卡点、冲击缩放与律动音轨同步。
6. **Case 2107548992640880755** — *施工顺序动画* & **Case 2108948624004526516** — *Anatomy 机器说明图*
   - 借鉴点：分层揭示/建造类 B-roll 等轴测图示与结构支柱吸附设计。

---

## 4. 注册进 FX Registry (`hevi-fxreg`) 的技术方案

在 `hevi-fxreg`（Unified FX Registry）分支中，模板以统一的数据模型 `FXTemplate` 进行编目与调用。为了将本模块的确定性纯函数动效模板平滑注册，方案如下：

### 4.1 数据模型扩展与枚举对齐
在 `hevi/fx/registry.py` 中：
1. 扩充来源枚举 `Source`：
   ```python
   class Source(StrEnum):
       TALKCRAFT = "talkcraft"
       XFADE = "xfade"
       SFX = "sfx"
       CUSTOM = "custom"
       AIMOTION = "aimotion"   # 新增来源标识
   ```
2. 类别归属：
   - `morph_ui`、`layer_build` 归入 `Category.STYLE`（视觉样式与 B-roll 场景）。
   - `timeline_explainer`、`kinetic_lyrics` 归入 `Category.OVERLAY`（知识排版与动态字排）。

### 4.2 模板条目声明 (Template Manifest)
在 FX Registry 的模板加载器中注册 4 个核心模板：
```python
FXTemplate(
    id="aimotion:morph-ui",
    name_zh="单形状连续形变动效",
    name_en="Morph UI Journey",
    description="一个几何形状通过闭式弹簧连续形变串接 6-10 个状态，纯函数逐帧渲染",
    category=Category.STYLE,
    source=Source.AIMOTION,
    supported_aspects=["9:16", "16:9", "1:1"],
    tags=["morph", "spring", "ui", "b-roll", "deterministic"],
    render_config={
        "engine": "canvas_headless",
        "entry": "hevi/motion_templates/templates/morph_ui.html",
        "cli_module": "hevi.motion_templates.cli",
        "default_duration": 10.0,
        "default_fps": 30,
    }
)
```

### 4.3 渲染适配器 (Render Adapter)
在 Registry 的执行调用层对接 `hevi.motion_templates.render.render`：
```python
def render_aimotion_template(
    template_id: str,
    spec: dict,
    out_mp4: Path,
    aspect: str = "9:16",
    fps: int = 30,
) -> Path:
    from hevi.motion_templates.render import render
    # 将 aimotion:morph-ui 解构为模板名 morph_ui
    template_name = template_id.split(":")[-1].replace("-", "_")
    result = render(
        template=template_name,
        spec=spec,
        out_mp4=out_mp4,
        aspect=aspect,
        fps=fps,
        contact_sheet=True,
    )
    return result.mp4_path
```

### 4.4 预览产物管线 (Preview Asset Pipeline)
对标 `output/fx_previews/` 规范，每个模板自动预渲染：
- `output/fx_previews/aimotion__morph-ui.mp4`
- `output/fx_previews/aimotion__morph-ui.jpg` (由 Contact Sheet 第一行或中心帧抽取)
以便在 Hevi Studio 与前端编辑器面板中实时检索预览。
