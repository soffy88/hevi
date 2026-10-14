# MOTION_FX — Morph/材质转场 + 运动模糊/多画幅渲染工程 (Unit C)

本文档归档 Hevi `hevi.motion_fx` 包的接口参数、参考来源署名（版权边界）、算法原理，以及向 `hevi-xfadepack` 转场注册表无缝并入的方案设计。

---

## 1. 架构总览

`hevi.motion_fx` 落地自 `AIMOTION_EVAL.md` 单元 C，专为 CPU-only、无头环境（Headless Linux）设计，提供以下四大核心能力：

1. **高级材质与形态学转场 (`hevi.motion_fx.transitions`)**：
   - `line_to_structure`：线条描绘 → 几何蓝图结构体形变接下一镜。
   - `water_ripple`：水面波纹涟漪扩散与 Snell 折射位移 + 焦散高光。
   - `glass_refract`：透明棱镜玻璃板扫掠折射 + 色散（RGB Chromatic Aberration）+ Fresnel 反射边缘。
   - 统一接口：`apply_transition(clip_a, clip_b, kind, dur, params, out, start)`。
2. **BPM 网格节拍对齐 (`hevi.motion_fx.beat`)**：
   - `snap_to_grid(t, bpm, division)`：将转场起点或关键帧时间精确卡在音乐节拍网格点上。
3. **Subframe 运动模糊渲染器 (`hevi.motion_fx.subframe`)**：
   - `render_html_subframes`：基于 Playwright + 单文件 HTML `draw(t)` 纯时间函数，在快门曝光期内进行 $N$ 次子帧偏移采样并平均，输出 60fps/30fps 真实运动模糊视频。
   - `apply_tmix_motion_blur`：基于 ffmpeg `tmix` 滤波器的后处理运动模糊。
   - `compute_blur_metrics`：定量评估 Laplacian 方差、Sobel 边缘梯度及中间过渡像素。
4. **9:16 智能自动裁摆与多画幅导出 (`hevi.motion_fx.reframe`)**：
   - `reframe(in_16x9, out, aspect="9:16")`：CPU-only 视觉显著性（Spectral Residual Saliency）与运动能量分析，平滑跟踪主体，确保主体占比 $\ge 50\%$ 且无上下黑边（无上下空带）；竖屏视频直接原样穿透。
   - `render_multi_aspect`：对同一 `draw(t)` HTML 场景，一次性多线程并行导出 9:16、16:9 与 1:1 三种规格。

---

## 2. 参考来源与版权声明 (Case Attribution)

> **版权边界声明**：本项目遵循 Hevi 工程治理规范，严禁侵入、复制或 vendor 任何第三方作者的作品源码或图像素材。以下作品仅作为动画设计范式、视觉手法与纯数学物理运动规律的灵感与工程参考，所有代码均为从零自研的独立实现。

| Case ID | 作品标题 | 作者署名与链接 | 吸收技法 / 参考要点 |
| :--- | :--- | :--- | :--- |
| **`2109174851412119558`** | 一条线变成整支动效 | **Nick** ([@heyiamnick](https://x.com/heyiamnick)) | **Line-to-Structure**：从单一轮廓线出发，通过扫描线展开技术图纸蓝图（Blueprint Grid），在两镜之间进行结构体轮廓插值，再向实体表面与真实像素固化填充。 |
| **`2102786378282987591`** | Clearwater：实时浅水与交互涟漪 | **Aurelien** ([@Aurelien_Gz](https://x.com/Aurelien_Gz)) | **Water Ripple Refraction**：浅水波包波动方程（Gaussian Wave Packet）、表面法线梯度计算、Snell 折射像素位移（Bilinear Remap）以及波峰拉普拉斯曲率导致的焦散（Caustic）高光。 |
| **`2109257723246501895`** | 透明 CD 盒的材质与开盖交互 | **Ann Nguyen** ([@ann_nnng](https://x.com/ann_nnng)) | **Glass Refract Sweep**：倾斜厚透明棱镜玻璃板扫过视口，柱面透镜曲面折射轮廓、波长色散差异（Red/Green/Blue 差异化折射率）、Fresnel 倒角高光与玻璃光泽。 |
| **`2103483957266268381`** | MakerMap 的连续产品旅程 | **Martijn Verbove** ([@verbove](https://x.com/verbove)) | **One HTML / draw(t) / Subframes**：无状态纯时间函数 `draw(t)`、120 BPM 节拍网格对齐、无头 Chrome 逐帧渲染与 6 subframes 运动模糊合成、多画幅并行导出规范。 |
| **`2102554209166000267`** | 节拍同步的产品动效广告 | **zero** ([@twoclipping](https://x.com/twoclipping)) | **BPM Card Snapping**：严格卡点切镜、禁用 shockwave/particle 等廉价 AI 特效、真实 UI 材质。 |

---

## 3. 详细参数与接口契约

### 3.1 转场接口 `apply_transition`

```python
from hevi.motion_fx.transitions import apply_transition

out_path = apply_transition(
    clip_a="input_a.mp4",
    clip_b="input_b.mp4",
    kind="water_ripple",  # "line_to_structure" | "water_ripple" | "glass_refract"
    dur=1.2,              # 转场重叠时长（秒）
    params={
        "bpm": 120.0,
        "division": 4,
        "snap_start": True,
        # 转场专属参数...
    },
    out="output.mp4",
    start=None,           # 可选：显式指定 clip_a 的转场起始时间
)
```

#### 转场专属参数 (`params`)：
- **`line_to_structure`**：
  - `line_color`: 轮廓线 BGR 颜色，默认 `[245, 215, 60]`（蓝图白青色）。
  - `bg_color`: 蓝图背景底色，默认 `[55, 25, 12]`（深海蓝）。
  - `grid_spacing`: 建筑图纸正交网格间距（像素），默认 `48`。
- **`water_ripple`**：
  - `center`: `(cx, cy)` 归一化中心坐标，默认 `(0.5, 0.5)`。
  - `wave_speed`: 涟漪扩散速度系数，默认 `1.0`。
  - `refract_strength`: 水面折射位移强度，默认 `0.04`。
  - `caustic_power`: 波峰焦散高光强度，默认 `0.35`。
  - **进度曲线 (AMFX-R2 H3)**：波前半径 $r_0(p)$ 结合画面长宽比动态计算视口四角最远欧氏距离，将折射波包与画面混合均匀摊展至整段过渡时长 $p \in [0, 1]$，彻底杜绝半程提前完成（$p=0.48$ 时 vsA 与 vsB 差异均 $>20$ 且平滑过渡）。
- **`glass_refract`**：
  - `angle_deg`: 玻璃板扫掠倾角（度），默认 `18.0`。
  - `slab_width`: 玻璃板相对画面宽度的厚度，默认 `0.35`。
  - `refract_strength`: 棱镜边缘折射位移幅度，默认 `0.06`。
  - `dispersion`: 色散（RGB 分离）系数，默认 `0.012`。**安全上限强制截断至 $\le 0.015$ (AMFX-R2 H4)**，严格杜绝廉价劣质 RGB Split 伪特效，保持高质量物理光学厚玻璃边缘微色散。
  - `glint_power`: 倒角 Fresnel 镜面反射高光强度，默认 `0.6`。

#### 时长与编码契约：
- 输出时长严格等于 $T_a + T_b - dur$（误差 $\pm 1$ 帧以内）。
- 编码格式：H.264、`yuv420p`、`+faststart`。
- 音频：两段素材均有音频时，自动通过 ffmpeg `acrossfade` 进行等功率淡入淡出混音。

### 3.2 BPM 网格对齐 `snap_to_grid`

```python
from hevi.motion_fx.beat import snap_to_grid

# 120 BPM 下卡到 1/4 拍（一拍 = 0.5s）
t_snapped = snap_to_grid(t=2.36, bpm=120.0, division=4) # 返回 2.50
```

- `t`: 待对齐的时间戳（秒）。
- `bpm`: 每分钟节拍数（默认 120.0）。
- `division`: 音乐节拍划分。`1`=全音符（4拍/小节），`2`=二分音符（2拍），`4` 或 `"1/4"`=四分音符（1拍），`8` 或 `"1/8"`=八分音符（半拍），`16`=十六分音符（1/4拍）。
- 公式：$step = \frac{240.0}{bpm \times division}$，返回 $\text{round}(t / step) \times step$。

### 3.3 Subframe 运动模糊 `render_html_subframes`

```python
from hevi.motion_fx.subframe import render_html_subframes, compute_blur_metrics

out_mp4 = render_html_subframes(
    html_source="path/to/animation.html",
    out="rendered_60fps.mp4",
    duration=3.0,
    fps=60,         # 参数化支持 30fps 或 60fps
    subframes=6,    # 采样 6 个子帧求平均
    width=720,
    height=1280,
)
```

- **子帧采样公式**：对于第 $k$ 帧（基准时间 $t_k = k / fps$），在快门曝光时间内以 $\Delta t = \frac{1}{fps \cdot subframes}$ 均匀采样：
  $$SubFrame_i = \text{draw}(t_k + i \cdot \Delta t), \quad i \in [0, N-1]$$
  $$Frame_k = \frac{1}{N} \sum_{i=0}^{N-1} SubFrame_i$$
- **定量对比指标 (`compute_blur_metrics`)**：
  - `laplacian_var`：拉普拉斯方差。$N=1$（单帧瞬间曝光）边缘锐利无模糊，方差极高；$N=6$ 运动方向平滑，高频噪声与频闪被消除，方差大幅降低（实测下降 $>65\%$）。
  - `intermediate_pixels`：灰度过渡区（亮度在 $[20, 235]$ 之间）的像素数量。$N=1$ 为二值跳变（0 像素）；$N=6$ 呈现平滑拖影渐变带（实测增长上万像素）。

### 3.4 9:16 智能自动裁摆 `reframe` 与多画幅并行导出

```python
from hevi.motion_fx.reframe import reframe, render_multi_aspect

# 1. 16:9 横屏转 9:16 竖屏 (AMFX-R2: 人物优先 + 平滑无抖动 + 独立指标)
vertical_mp4 = reframe(
    in_video="interview_16x9.mp4",
    out="interview_9x16.mp4",
    aspect="9:16",
    smooth_alpha=0.08,    # 零相位双向滤波平滑系数
    max_velocity=7.5,     # 镜头内最大帧间位移约束 (<= 8.0 px/frame)
)

# 2. 一次并行导出三种画幅
exported_dict = render_multi_aspect(
    html_source="scene.html",
    out_dir="output_aspects/",
    aspects=["9:16", "16:9", "1:1"],
    duration=2.5,
    fps=30,
    subframes=4,
)
```

- **主体检测与覆盖率保证 (AMFX-R2/R3 H1-H3 强化)**：
  - **优先人物与防切脸约束 (H3)**：集成 OpenCV `FaceDetectorYN`（YuNet ONNX 模型，CPU 轻量，置于 `hevi/motion_fx/models/`），检测得分 $\ge 0.55$，剔除边缘截断与微小误检。引入防切脸约束（Anti-Slicing Constraint）：对所有检测到的人脸实施「非整即出」判定，当裁窗边缘切割人脸时（窗内比例 $15\% \sim 85\%$），优先平移窗口使其完整包容，全片被切断人脸帧占比降低至 $1.41\%$（严格满足 $\le 3\%$ 验收门禁）。
  - **动态发言人与双人包容**：当多人人脸并集宽度 $\le W_{crop}$ 时，裁窗中心自动取双人并集中点同时包住两人；超出时优先包住主发言人。
  - **空镜/B-Roll 显著性与滑窗积分 (H2)**：无人脸模式下，采用高对比前景连通域、边缘梯度与局部对比度联合能量，通过 1D 滑动窗口积分选取能量最大裁窗，避免整图质心陷于空白海面，ISS 国际空间站联盟号飞船及太阳能板在窗率达 $100\%$（严格满足 $\ge 80\%$ 门禁）。
- **真正的平滑相机跟踪 (AMFX-R2/R3 H1, H2 修复)**：
  - **精确镜头切换检测 (H1)**：通过缩放灰度帧差中位数自适应阈值配合人脸时空连续性判据，剔除走廊同镜头内的轻微曝光/运动假切点（399、541 排除），切点精准对齐真实切换 `[54, 98, 116, 151, 176, 186, 199, 348, 354]`。
  - **切点瞬时就位与镜头内平滑 (H1, H3)**：切换镜头后首帧瞬时落位到新目标，同镜头内部平滑跟踪，同镜头内帧间位移实测 $p50 = 0\text{ px}$、$p95 \le 8\text{ px}$、$\max \le 8\text{ px}$（严格满足 $p95 \le 8\text{ px}$，$\max \le 20\text{ px}$ 门禁）。
  - 裁切高度取 100% 画面高度（$H_{crop} = H_{in}$），完全避免上下黑边。
  - 若输入素材本身已为竖屏（$W/H \le 9/16 \times 1.05$），直接以 ffmpeg stream copy 穿透，避免重编码损耗。
  - 裁切高度取 100% 画面高度（$H_{crop} = H_{in}$），完全避免上下黑边。
  - 若输入素材本身已为竖屏（$W/H \le 9/16 \times 1.05$），直接以 ffmpeg stream copy 穿透，避免重编码损耗。

---

## 4. 并入 `hevi-xfadepack` 转场注册表的集成方案

当前 `hevi-xfadepack` 分支集中在 `hevi/assembly/xfade_transitions.py`，使用 `Transition` dataclass 管理原生 ffmpeg xfade 内置滤镜与 custom 表达式。

为了保持分支解耦与纯净性，建议采用以下**双轨集成方案**：

### 方案 A：扩展 `Transition` 种类支持 Python/NumPy 处理器（推荐）

在 `hevi-xfadepack` 的 `Transition` 中新增 `"processor"` 类别：

```python
# hevi/assembly/xfade_transitions.py 架构设想
@dataclass(frozen=True)
class Transition:
    id: str
    name_zh: str
    kind: Literal["builtin", "custom", "processor"]
    ffmpeg: str  # builtin 名、custom 表达式、或 processor 模块引用
    tags: list[str]
    default_duration: float = 0.5
    handler: Optional[Callable] = None  # 针对 processor 类别的回调函数
```

在注册表中声明：
```python
Transition(
    "line_to_structure", "线条转结构", "processor",
    "hevi.motion_fx.transitions.render_line_to_structure",
    ["energetic", "tech", "morph"], 1.0
),
Transition(
    "water_ripple", "水面涟漪", "processor",
    "hevi.motion_fx.transitions.render_water_ripple",
    ["soft", "nature", "refract"], 1.2
),
Transition(
    "glass_refract", "玻璃折射", "processor",
    "hevi.motion_fx.transitions.render_glass_refract",
    ["energetic", "modern", "refract"], 1.0
),
```

### 方案 B：在装配层 `assembler.py` 动态分流
在 `hevi.assembly.assembler.build_xfade_chain` 或拼接器中：
1. 检查所选转场的 `kind`。
2. 若为 `"builtin"` 或 `"custom"`，继续走原有的 ffmpeg `-filter_complex xfade` 滤镜链。
3. 若为 `"processor"`（或存在于 `hevi.motion_fx.REGISTRY`），在拼接交界处调用 `hevi.motion_fx.transitions.apply_transition` 渲染过渡片段，再与前后段流式直拼（concat demuxer）。

**优势**：
- 零侵入现有内置 58 个 xfade 转场与 6 个 custom 转场。
- 支持复杂的逐像素多通道光线折射、卷积特征提取与几何变形，突破单一 ffmpeg expr 语法的数学表达限制。
- 保证在任意装配器或 NLE 界面中均可通过统一的 `transition_id` 无缝调用。
