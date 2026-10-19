# Hevi 动画品味规则（Taste R1）

来源：`emilkowalski/skills`（MIT，Emil Kowalski，Vercel / Linear 背景），按 hevi 出品线改写。
原文：https://github.com/emilkowalski/skills（2026-10-19 同步，commit 2d22863）

## 定位

- `docs/rules/web_animation.md`（R1）管**工程正确性**：确定性渲染、seek、内存泄漏、GPU 加速。
- 本卡（R2）管**品味**：动得好不好看、该不该动、曲线与时长选得对不对。
- 两者冲突时工程优先；幼儿线另受 `KIDS_ANIME_DIRECTION.md` 的 kids_gate 约束（安全闸门优先级最高，本卡的 delight 不得违反：无闪切、单镜头≥2.5s、转场只用柔和类型）。

适用：所有写动画代码的 agent worker —— `hevi-remotion` / `hevi-remotion-talkcraft` /
`hevi-remotion-whiteboard` / `hevi/webrender` / `hevi-web`，以及调用能力注册表做转场/标题卡/特效的能力实现。

## 0. 总纲

品味 = 该动才动 × 曲线选对 × 时长合适 × 属性干净。四项全对才算过。
"功能能跑但看着廉价"，在本卡下视为未完成。

## 1. 该不该动（频率四档）

先回答"观众多久看到一次"，再决定动不动。答不上来就不写。

| 频率 | 例子 | 决策 |
| --- | --- | --- |
| 每集多次 / 高频交互 | 片头标题卡、转场、字幕条、键盘触发的 UI | 极简或不动。能省则省 |
| 每集几次 / 每天几十次 | 章节标题、问答弹窗、列表 hover | 克制、快，近乎无感 |
| 偶尔出现 | 片尾、特殊效果、toast、抽屉 | 标准动画 |
| 罕见 / 高光时刻 | 庆祝、转折点、首次引导 | 可以加料，这是 delight 预算的唯一去处 |

**键盘触发的动作永远不动。** 每集重复出现的元素（标题卡、转场）按"高频"处理：越常见越要短、越要收。

## 2. 目的（六个合法词）

每个动画必须能用下面其中一个词说出"为什么动"，说不出就不做：

- **Feedback**（反馈）：确认收到了用户的操作，如按钮按压缩放。
- **Spatial consistency**（空间一致）：进出同路，如 toast 从哪条边进就从哪条边出，滑动关闭才符合直觉。
- **State indication**（状态指示）：让状态变化可读，如按钮变形表示状态切换。
- **Preventing a jarring change**（防跳变）：内容凭空出现/消失会显得像 bug，用过渡桥接。
- **Explanation**（讲解）：演示功能怎么用，只允许出现在营销/引导类内容。
- **Delight**（愉悦）：只允许在"罕见/高光"档。

"看着酷"不是理由。在高频元素上"看着酷"是扣分项。

## 3. Easing 选择

决策顺序：进/出场 → `ease-out`；屏内移动/变形 → `ease-in-out`；
hover/颜色 → `ease`；匀速（跑马灯、进度条）→ `linear`；默认 → `ease-out`。

**禁止 `ease-in` 用于进场/UI 动画。** 它延迟了观众最关注的起始瞬间，同为 200ms，
`ease-in` 体感比 `ease-out` 慢得多。

内置 easing 太弱，必须用下面的强曲线（不要手搓，不要用"看着眼熟"的值）：

```css
--ease-out:     cubic-bezier(0.23, 1, 0.32, 1);    /* UI 交互的强 ease-out */
--ease-in-out:  cubic-bezier(0.77, 0, 0.175, 1);   /* 屏内移动/变形的强 ease-in-out */
--ease-drawer:  cubic-bezier(0.32, 0.72, 0, 1);     /* iOS 风格抽屉曲线（源自 Ionic） */
```

各引擎映射（用精确值，不近似）：

| 引擎 | 写法 |
| --- | --- |
| CSS / WAAPI | 上面的 `cubic-bezier(...)` 原样 |
| Remotion | `Easing.bezier(0.23, 1, 0.32, 1)`（Remotion 原生支持 bezier） |
| GSAP | `CustomEase.create("ease-out", "0.23,1,0.32,1")`，或 `expo.out`/`power4.out` 做近似 |

弹簧（spring）只用在四种情况：带惯性的拖拽、要"活起来"的元素、可被中途打断的手势、
装饰性跟随。用 Apple 式配置（好推理）：`{ type: "spring", duration: 0.5, bounce: 0.2 }`，
bounce 保持 0.1–0.3，多数 UI 场景不要 bounce。

## 4. 时长

| 元素 | 时长 |
| --- | --- |
| 按钮按压反馈 | 100–160ms |
| tooltip、小 popover | 125–200ms |
| 下拉框、选择器 | 150–250ms |
| 弹窗、抽屉 | 200–500ms |
| 营销/讲解类 | 可更长 |

**UI 动画一律 < 300ms。** 180ms 的下拉框体感比 400ms 的更跟手。
（叙事节奏另受 kids_gate 约束：单镜头≥2.5s，本卡不管故事 pacing，只管元素动效。）

感知性能：转得快的 spinner 让人觉得加载更快（耗时相同，体感不同）；
第二个起的 tooltip 跳过延迟和动画，整个工具栏都会显得更快。

## 5. 属性与物理正确性

- **只动 `transform` 和 `opacity`**（外加一个特许：`clip-path`）。`width`/`height`/`margin`/
  `padding`/`top`/`left` 会触发 layout+paint+composite，是掉帧主因。实在没有 transform
  等价物时（如 accordion 高度）才容忍 `height`。
- **永不从 `scale(0)` 进场。** 现实中没有东西凭空出现。从 `scale(0.9–0.97)` + `opacity: 0` 起步。
- **`transform-origin` 对准触发点。** popover/下拉/tooltip 从触发它的按钮长出来，不是
  从自己中心长出来。例外：modal（无触发锚点，保持居中）。
- `translate()` 用百分比：`translateY(100%)` 按元素自身高度位移，不随内容变化，比写死像素稳。
- **进出同路。** 从底边滑进的 toast 从底边滑出，对称路径是滑动关闭符合直觉的原因。
- **非对称时序。** 需要" deliberate" 的阶段慢（按住确认 2s linear），系统响应快
  （松开 200ms ease-out）。进出同速是 finding。
- **高频触发用 transition，不用 keyframes。** transition 可中途重定向，keyframes 会从头重播。
  toast、toggle 这类一秒能触发两次的元素一律 transition。
- **多元素同时进场要 stagger。** 间隔 30–80ms，级联出现；间隔太长显慢。stagger 是装饰，
  永不阻塞交互。
- **crossfade 别扭时加一点 blur。** `filter: blur(2px)` 能糊掉新旧两态重叠的生硬感。
  动画中的 blur 保持 < 20px（Safari 更贵），2–5px 通常够用。

## 6. 性能（本卡补充 R1 之外的坑）

R1 已覆盖 GPU 加速大原则，以下是 Agent 最容易漏的：

1. **禁 `transition: all`。** 写死具体属性。`all` 会把下一次变化的任何属性都带进动画，
   包括没人想动的 layout 属性。
2. **不要用父级 CSS 变量驱动子元素的 transform。** 变量继承会触发所有子节点的
   style recalc，内容越多每帧越慢。直接写元素自身的 `transform`。
3. **Framer Motion 的 `x`/`y`/`scale` 速记不是硬件加速的**（走 CSS 变量+主线程 rAF）。
   在页面繁忙时会掉帧的动画，改用完整 `transform` 字符串。
4. **`box-shadow` 动画改用 `filter: drop-shadow()`。** 阴影动画每帧重绘，看着无害实际很贵。
5. **React 手写动画不要经过 state。** rAF 里 `setState` = 每帧一次重渲染。
   写 `ref.current.style.transform`。
6. **`will-change` 是最后手段。** 先修属性和线程问题；只在看到 1px 抖动或实测掉帧后加，
   加在动画元素本身，永不加 `*` 或大容器。

## 7. 审查（review-animations 十项硬标准）

写完动画代码先自查，逐条过。违反任何一条即 finding：

1. **Justified motion** — 每个动画都能说出第 2 节的合法目的。
2. **Frequency-appropriate** — 频率与动效强度匹配；键盘/高频动作无动画。
3. **Responsive easing** — 进/出场用 `ease-out` 或强自定义曲线；UI 上出现 `ease-in` 即 block。
4. **Sub-300ms** — UI 动画 < 300ms，超了要有理由。
5. **Origin & physical correctness** — 触发锚点对齐 origin；永不 `scale(0)` 进场。
6. **Interruptibility** — 高频/手势驱动的可中途打断（transition/spring，不用 keyframes）。
7. **GPU-only properties** — 只动 `transform`/`opacity`（+`clip-path`）。
8. **Accessibility** — `prefers-reduced-motion` 要处理（减弱不断：保留 opacity/颜色过渡，
   去掉位移）；hover 动效包在 `@media (hover: hover) and (pointer: fine)` 里。
9. **Asymmetric enter/exit** — deliberate 慢、响应快；对称时序是 finding。
10. **Cohesion** — 动效气质与内容气质一致（幼儿线温和圆润，不用生硬弹跳）；
    拿不准时最强的动作往往是删掉这个动画。

输出格式（给 worker 做 code review 时用）：

| Before | After | Why |
| --- | --- | --- |
| `transition: all 300ms` | `transition: transform 200ms ease-out` | 指名具体属性；`all` 会带上非 GPU 属性 |
| `transform: scale(0)` | `transform: scale(0.95); opacity: 0` | 现实中没有凭空出现的东西 |

结论二选一：**Block**（feel-breaking 回归、高频/键盘动作有动画、`scale(0)`/`ease-in`、
非 GPU 动画有简单修法）或 **Approve**。拿不准手感时，用慢放/逐帧检查代替猜值，
隔夜再看一遍。

## 8. 全库审计工作流（improve-animations）

需要对一条线的全部动画做审计时，按此流程（只读代码，不直接改）：

1. **Recon** — 先画出动效全景：技术栈、动效库、现有 easing/duration token（只扩展不另起）、
   产品气质、频率地图。
2. **Audit** — 按第 7 节十项标准逐条审，`grep transition|@keyframes|ease-in|scale(0)|
   prefers-reduced-motion` 扫。
3. **Vet** — 逐条回到 file:line 确认，by-design 的不报（如 modal 的居中 origin 是对的）。
4. **Plan** — 输出按"影响/成本"排序的表，severity 分 HIGH（feel-breaking）/ MEDIUM / LOW，
   每个 plan 写死精确值（曲线、时长、文件路径、代码摘录），弱执行者也能照做。
   另列 2–4 个"该动没动"的机会点（加法项，单独列）。

## 9. 词汇表

动效词汇（中英对照）见 `docs/rules/animation_vocabulary.md`。
写 prompt、给 AI 描述动效、跟设计师对词时用它 —— 先对上词，再谈实现。
