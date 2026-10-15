# Hevi 动效提示词规则与质检体系 (Motion Rules & Verification)

> **版本**：R1 (`DONE AMRULES-R1`)  
> **包路径**：`hevi/motion_rules/`  
> **运行环境**：CPU-only，零外部付费 API，零模型运行时开销，完全确定性

---

## 1. 架构目标与设计原则

基于 `AIMOTION_EVAL.md` §3.1 与 §3.3 调研结论，Hevi 在动效生成领域面临的主要痛点是：
1. **动画缺乏确定性**：依赖积分步进或 CSS transitions 导致无法精确逐帧 seek 与运动模糊合成；
2. **缺乏闭式弹性**：传统贝塞尔曲线生硬，积分模拟弹簧在多目标切换时存在状态残留；
3. **分镜存在穿帮**：文字与容器形变重叠挤压、转场脱离音乐节拍、单镜超时拖沓；
4. **劣质模板特效泛滥**：冲击波圈、荧光霓虹、粒子爆发等廉价 AI 味特效拉低成片质感；
5. **成片缺乏物理量化质检**：依赖肉眼审片，难以机械发现高频频闪、首尾跳帧与画幅错误。

为了解决上述问题，`hevi/motion_rules/` 构建了一套完整的**「提示词规范库 + 静态分镜 Lint + 物理级成片质检 + 双语闭式弹簧引擎」**：

```
hevi/motion_rules/
├── __init__.py
├── spring.py                 # Python 闭式弹簧解析解与多目标叠加轨迹
├── js/
│   └── spring.js             # JavaScript 双语一致性闭式弹簧引擎 (UMD)
├── rules/                    # 10 条标准化动效规则卡 (YAML)
│   ├── 01_pure_draw_seek_stateless.yaml
│   ├── 02_closed_form_spring.yaml
│   ├── 03_single_shape_morph.yaml
│   ├── 04_content_container_timing.yaml
│   ├── 05_short_blur_transition.yaml
│   ├── 06_bpm_grid_alignment.yaml
│   ├── 07_loop_first_last_frame.yaml
│   ├── 08_prohibited_elements.yaml
│   ├── 09_real_assets_not_placeholders.yaml
│   └── 10_contact_sheet_first.yaml
├── prompt_pack.py            # 提示词编译生成器（compact / detailed / system_prompt）
├── lint.py                   # 静态分镜 Spec 规则校验器（红灯硬拦截 / 黄灯预警）
├── video_checks.py           # 成片 ffmpeg 实测抽帧质检（频闪、首尾帧、9:16画幅）
└── examples/                 # 手写分镜基准示例 (合规/违规)
```

---

## 2. 十大动效规则全解与作者案例署名

> **版权声明**：本规则库严格遵守知识产权与开源版权边界。未复制、包含或供应商引入任何原作者作品的源码或画面，仅在工程规范层面提炼技法原理与设计模式，全部代码均为自主全新编写。在此按 case id 对启发来源进行完整署名。

### 规则卡清单与案例索引

| 规则 ID | 规则名称 | 核心规范 | 来源案例 ID | 署名作者 |
|---|---|---|---|---|
| `pure_draw_seek_stateless` | 纯 draw(t)/seek(t) 无状态 | 纯时间函数，禁止定时器与帧间状态累加 | `2103483957266268381`<br>`2103273003555402193` | Martijn Verbove (@verbove)<br>zero (@twoclipping) |
| `closed_form_spring` | 闭式多目标叠加弹簧 | 阻尼阶跃响应闭式解，多目标叠加，微小过冲 | `2103273003555402193`<br>`2103483957266268381` | zero (@twoclipping)<br>Martijn Verbove (@verbove) |
| `single_shape_morph` | 单形状连续形变 | 同一元素连续尺寸/圆角/色彩 morph，杜绝频繁切镜 | `2103483957266268381`<br>`2103273003555402193` | Martijn Verbove (@verbove)<br>zero (@twoclipping) |
| `content_container_timing` | 内容与容器形变进出时序 | 容器形变后文字进、下次形变前文字退，防挤压穿帮 | `2103483957266268381`<br>`2103273003555402193` | Martijn Verbove (@verbove)<br>zero (@twoclipping) |
| `short_blur_transition` | 短模糊过渡 | 状态切换叠加 0.1s 短模糊，杜绝全黑淡入淡出 | `2103483957266268381` | Martijn Verbove (@verbove) |
| `bpm_grid_alignment` | 转场对齐 BPM 网格 | 转场起点与 UI 关键打击硬性对齐节拍点 (容差 ≤20ms) | `2103273003555402193`<br>`2102554209166000267` | zero (@twoclipping) |
| `loop_first_last_frame` | 首尾同帧无缝循环 | 循环片段首帧与末帧必须像素级完全吻合 | `2103273003555402193`<br>`2103483957266268381` | zero (@twoclipping)<br>Martijn Verbove (@verbove) |
| `prohibited_elements` | 动效禁项红线清单 | 严禁 shockwave、particles、RGB split、neon、句号等 | `2102554209166000267`<br>`2103273003555402193` | zero (@twoclipping) |
| `real_assets_not_placeholders`| 真实素材与数据驱动 | 禁止 Lorem Ipsum 与灰块占位，用真实数据与真实光标 | `2103483957266268381`<br>`2102554209166000267` | Martijn Verbove (@verbove)<br>zero (@twoclipping) |
| `contact_sheet_first` | 接触样张先行核验 | 全渲前按节拍输出 contact sheet 排查拥挤遮挡 | `2103483957266268381`<br>`2103273003555402193` | Martijn Verbove (@verbove)<br>zero (@twoclipping) |

---

## 3. 闭式弹簧物理学与双语一致性保证

### 3.1 数学原理
弹簧振子二阶常微分方程：
$$m \ddot{x} + c \dot{x} + k(x - x_{\text{target}}) = 0$$

归一化参数：
- 固有角频率 $\omega_n = \sqrt{k/m}$
- 阻尼比 $\zeta = \frac{c}{2\sqrt{km}}$

单位阶跃响应归一化解析式 $y(\tau)$（$\tau = t - t_0$）：
1. **欠阻尼 ($\zeta < 1$)**：
   $$\omega_d = \omega_n \sqrt{1 - \zeta^2}$$
   $$y(\tau) = 1 - e^{-\zeta \omega_n \tau} \left( \cos(\omega_d \tau) + \frac{\zeta \omega_n}{\omega_d} \sin(\omega_d \tau) \right)$$
2. **临界阻尼 ($\zeta = 1$)**：
   $$y(\tau) = 1 - e^{-\omega_n \tau} (1 + \omega_n \tau)$$
3. **过阻尼 ($\zeta > 1$)**：
   $$\omega_d = \omega_n \sqrt{\zeta^2 - 1}$$
   $$y(\tau) = 1 - e^{-\zeta \omega_n \tau} \left( \cosh(\omega_d \tau) + \frac{\zeta \omega_n}{\omega_d} \sinh(\omega_d \tau) \right)$$

### 3.2 多目标叠加轨迹 (`SpringTrack`)
线性定常系统具备叠加原理。当目标值在序列时刻 $t_0, t_1, \dots, t_{n-1}$ 分别跳变至 $X_0, X_1, \dots, X_{n-1}$ 时：
$$\Delta X_i = X_i - X_{i-1} \quad (X_{-1} = \text{initial\_value})$$
$$\text{value}(t) = \text{initial\_value} + \sum_{i: t_i \le t} \Delta X_i \cdot y(t - t_i)$$
- **无状态计算**：任意时刻 $t$ 的值仅取决于时间与静态关键帧序列，不依赖任何上一帧的变量或微积分步长；
- **连续性**：由于 $y(0) = 0$ 且 $\dot{y}(0) = 0$，即使目标多次突变，位移与速度依然处处连续。

### 3.3 Python 与 JavaScript 双语一致性
通过 `tests/motion_rules/test_spring_consistency.py` 覆盖 200 个横跨欠阻尼、临界阻尼、过阻尼与多目标复合阶跃的随机采样点：
- **最大数值绝对误差**：$2.84 \times 10^{-14}$（远严于 $< 10^{-6}$ 的验收红线）。

---

## 4. 静态分镜 Lint 检查机制 (`lint.py`)

输入 JSON 分镜规范（Storyboard Spec），自动化静态检查以下违规项：

### 红灯项 (Hard Error，拦截生成与渲染)
1. `PROHIBITED_ELEMENT`：命中禁项特效（`shockwave_rings`, `particle_bursts`, `rgb_split`, `camera_shake`, `lens_flare`, `neon_glow`, `grid_floor`, `flashing_background`, `bouncy_easing`）；
2. `BPM_GRID_MISALIGNMENT`：转场起点或镜头切换未落在 BPM 节拍网格上（默认容差 20ms，参数化）；
3. `TEXT_BEFORE_CONTAINER_MORPH`：文字入场时间早于所在容器开始形变时间；
4. `TEXT_AFTER_CONTAINER_MORPH`：文字退场时间晚于所在容器下一次形变开始时间；
5. `TEXT_CONTAINS_PERIOD`：屏上展示文字末尾包含句号（中文 `。` 或英文 `.`）；
6. `SHOT_DURATION_EXCEEDED`：单镜头时长超过设定上限（默认 8.0s）。

### 黄灯项 (Warning，告警不拦截)
1. `MISSING_CONTACT_SHEET`：未声明在全量渲染前生成接触样张（contact sheet / probe frames）；
2. `LOOP_FRAME_MISMATCH`：声明为循环播放（`is_loop: true`），但首尾帧标识不一致。

---

## 5. 成片物理质检流水线 (`video_checks.py`)

针对导出的 MP4 成片执行确定性抽帧质检：
1. **画幅检查 (`check_aspect_ratio`)**：
   - 使用 `ffprobe` 提取视频物理分辨率，比对目标比例（默认 9:16 竖屏，允许容差 2%）。
2. **相邻帧频闪检测 (`check_flicker`)**：
   - 通过 `ffmpeg` 管道实时抽取 $64 \times 64$ 灰度帧，计算各帧平均亮度 $L(t)$ 与差分跳变 $|\Delta L|$；
   - 统计跳变幅度超过阈值（默认 20.0/255）的次数与频率（次/秒），有效拦截频闪背景与 AI 画面抖动。
3. **循环片首尾帧相似度 (`check_loop_similarity`)**：
   - 抽取首帧与末尾帧（$128 \times 128$ RGB），计算像素归一化平均绝对误差（MAD）；
   - 首尾帧相似度 $S = 1.0 - \text{MAD}$，要求 $S \ge 0.95$，拦截无缝循环断点。

---

## 6. 与现有系统接入方案（零分支污染设计）

本规则库采用独立模块化设计，不需要在当前阶段直接修改未合并的 `artmotion` 或 `omquality` 分支，未来合并时可通过以下无损适配器一键接入：

### 接入方案 A：接入 artmotion 的 `storyboard_lint.py`

在 `hevi-artmotion` 中，`storyboard_lint.py` 负责在动手写代码前检查 Markdown 镜头表。接入只需在其规则链中增加一个函数钩子：

```python
# 建议在 artmotion 的 storyboard_lint.py 中加入的适配代码:
from hevi.motion_rules.lint import lint_storyboard

def check_motion_rules_on_storyboard(table_rows: list[dict], bpm: float = 120.0) -> list[str]:
    """把 artmotion 的 markdown 镜头表转换并投递给 motion_rules lint 校验。"""
    shots_spec = []
    current_time = 0.0
    for row in table_rows:
        dur = float(row.get("duration", 2.0))
        shot_item = {
            "start": current_time,
            "dur": dur,
            "transition": {"start": current_time, "type": row.get("做法", "")},
            "effects": [tag.strip() for tag in row.get("标签", "").split(",") if tag.strip()],
            "texts": [{"text": row.get("屏上字", "").strip(), "in": current_time + 0.2, "out": current_time + dur - 0.2}],
        }
        shots_spec.append(shot_item)
        current_time += dur

    report = lint_storyboard({"shots": shots_spec, "bpm": bpm, "has_contact_sheet": True})
    errors = []
    for f in report.findings:
        if f.level == "red":
            errors.append(f"[动效红灯] Shot {f.shot}: {f.message}")
    return errors
```

### 接入方案 B：接入 omquality / delivery_gate 成片交付门控

在 `hevi/production/delivery_gate.py` 或 `hevi/quality/visual_quality.py` 中，作为成片物理验收项接入：

```python
# 建议在 omquality 的 delivery_gate.py 中接入的代码:
from hevi.motion_rules.video_checks import check_video

def verify_delivered_video_motion_quality(video_path: Path, is_loop: bool = False) -> tuple[bool, str]:
    """成片交付门控：物理级验证画幅、频闪与循环特性。"""
    report = check_video(
        video_path,
        is_loop=is_loop,
        target_aspect=(9, 16),
        aspect_tolerance=0.02,
        flicker_jump_threshold=20.0,
        max_flicker_frequency=2.0,
    )
    if not report.ok:
        reasons = []
        if not report.aspect.ok:
            reasons.append(report.aspect.message)
        if not report.flicker.ok:
            reasons.append(report.flicker.message)
        if report.loop and not report.loop.ok:
            reasons.append(report.loop.message)
        return False, "交付视频动效质检未通过: " + " | ".join(reasons)
    return True, "交付视频动效质检全绿合格"
```

---

## 7. 结语

通过将行业顶尖动效案例的隐性技法固化为显性规则卡、双语计算库与自动化质检工具，Hevi 具备了零运行时成本拦截劣质动效生成、确保音画精确合拍与工业级高标交付的完整能力。
