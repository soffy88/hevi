# 动画词汇表（Animation Vocabulary）

来源：`emilkowalski/skills` 的 `animation-vocabulary`（MIT），中英对照改写。
用途：写 prompt 时精确描述想要的动效；跟 AI / 设计师对词时先对上词再谈实现。
规则：词表内的词按原文引用，不自造词；没有精确对应的就说"近似"，或用词表里的词组合描述。

## 进出场（Entrances & Exits）

- **Fade in / Fade out** — 淡入 / 淡出：靠 opacity 出现或消失。
- **Slide in** — 滑入：从屏幕外（上/下/左/右）滑进来。
- **Scale in** — 缩放进入：由小放到正常尺寸出现，常配淡入。
- **Pop in** — 弹出：带一点过冲，像弹到位。
- **Reveal** — 揭示：内容逐渐被揭开，常靠 clip-path / mask 动画。
- **Enter / Exit** — 进场 / 退场：元素加入或离开屏幕时播放的动画。

## 序列与时间（Sequencing & Timing）

- **Keyframes** — 关键帧：定义 0%/50%/100% 等点，浏览器补中间。
- **Interpolation / Tween** — 插值/补间：起止值之间生成所有中间帧， motion 连续。
- **Stagger** —  stagger/级联：多个元素逐个延迟出现，形成波浪。
- **Orchestration** — 编排：多个动画刻意对时，感觉像一个整体动作。
- **Delay** — 延迟：动画开始前的等待时间。
- **Duration** — 时长：动画持续多久。
- **Fill mode** — 填充模式：动画前后是否保持首/尾帧样式（如 forwards）。
- **Stepped animation** — 步进动画：切成离散步，如倒计时。

## 移动与变换（Movement & Transforms）

- **Translate** — 位移：沿 X/Y 轴移动。
- **Scale** — 缩放：变大变小。
- **Rotate** — 旋转：绕一点转。
- **Skew** — 斜切：沿 X/Y 轴压斜。
- **3D tilt / Flip** — 3D 倾斜/翻转：rotateX/rotateY 做出纵深。
- **Perspective** — 透视：3D 效果的强度，值越小纵深越夸张。
- **Transform origin** — 变换原点：缩放/旋转的锚点。
- **Origin-aware animation** — 原点感知动画：元素从触发它的位置长出来
  （如 popover 从按钮处长出，而不是从自己中心）。

## 状态过渡（Transitions Between States）

- **Crossfade** — 交叉淡化：一个淡出的同时另一个在同一位置淡入。
- **Continuity transition** — 连续性过渡：前后视觉相连，不让用户跟丢，如同一矩形放大缩小。
- **Morph** — 变形：一个形状平滑变成另一个形状，如 Dynamic Island。
- **Shared element transition** — 共享元素过渡：一个元素从 A 位置飞到 B 位置并变形，
  如缩略图展开成卡片。
- **Layout animation** — 布局动画：元素尺寸/位置变化时滑到新位置而不是瞬移。
- **Accordion / Collapse** — 手风琴/折叠：区块平滑展开收起。
- **Direction-aware transition** — 方向感知过渡：前进往一边滑、后退往反方向滑，
  导航有方向感。

## 反馈与交互（Feedback & Interaction）

- **Hover effect** — 悬停效果：光标移上去的视觉变化。
- **Press / Tap feedback** — 按压缩放：点击时轻微缩小，有"按下去"的实在感。
- **Hold to confirm** — 按住确认：按住时进度条涨满，防止误触。
- **Drag** — 拖拽：抓住移动，松手常带惯性。
- **Swipe to dismiss** — 滑动关闭：把元素拖出屏幕关闭，如抽屉/toast。
- **Rubber-banding** — 橡皮筋：拖过边界时有阻力并回弹（iOS overscroll 手感）。
- **Shake / Wiggle** — 抖动：左右快速小抖，表示错误或拒绝输入。
- **Ripple** — 涟漪：从触点扩开的圆，确认按压。

## Easing（速度曲线）

- **Easing** — 缓动：动画速度随时间的变化率。
- **Ease-out** — 快出慢收： شروع快、结尾慢。UI 与响应用户操作的默认选择。
- **Ease-in** — 慢出快收：起始慢，体感拖沓，UI 里一般不用。
- **Ease-in-out** — 慢-快-慢：屏内已有元素从 A 到 B 用它。
- **Linear** — 匀速：UI 里不用，留给 spinner/跑马灯。
- **Cubic-bezier** — 三次贝塞尔：自定义精确曲线。
- **Asymmetric easing** — 非对称缓动：加速和减速不对称，比对称曲线更"活"。

## 弹簧（Spring Animations）

- **Spring** — 弹簧：靠物理参数（张力/质量/阻尼）而非固定时长驱动。
- **Stiffness / Tension** — 刚度/张力：弹簧拉回目标的力度，越大越跟手。
- **Damping** — 阻尼：弹簧多快停下来，越小越弹。
- **Mass** — 质量：元素"有多重"，越大越迟钝。
- **Bounce** — 回弹：过冲再落定，带俏皮感。
- **Momentum** — 惯性：拖拽松手后速度延续。
- **Velocity** — 速度：大小+方向；弹簧被打断时会把速度带进下一个动画。
- **Interruptible animation** — 可中断动画：飞到一半能被平滑改向，不用等它播完。

## 循环与氛围（Looping & Ambient）

- **Marquee** — 跑马灯：内容循环滚动。
- **Loop** — 循环：重复播放。
- **Alternate (yoyo)** — 往返：播完倒着播回来，而不是跳回开头。
- **Pulse** — 脉冲：轻微重复缩放/透明度变化，吸引注意。
- **Float** — 漂浮：轻微持续上下浮动，让静止元素有"活着"感。
- **Idle animation** — 待机动画：元素闲置时的 subtle  motion。

## 抛光特效（Polish & Effects）

- **Blur** — 模糊：柔化元素，或糊掉过渡的小瑕疵。
- **Clip-path** — 裁剪路径：按形状裁元素，做揭示/遮罩/对比滑杆。
- **Mask** — 遮罩：用形状或渐隐边缘隐藏/显示局部（clip-path 的柔边版）。
- **Line drawing** — 线条绘制：SVG 路径像被无形的手画出来。
- **Text morph** — 文字变形：数字/文字逐字滚动变化，吸引注意。
- **Skeleton / Shimmer** — 骨架屏/微光：加载中的占位+扫光。
- **Number ticker** — 数字滚动：数字滚动累加到目标值。
- **Typewriter** — 打字机：文字逐字出现，像被敲出来。

## 性能（Performance）

- **Frame rate (FPS)** — 帧率：每秒多少帧，60fps 是流畅基线。
- **Jank** — 卡顿：浏览器掉帧导致的肉眼可见一顿一顿。
- **Dropped frame** — 掉帧：没赶上绘制 deadline 的那一帧。
- **Compositing** — 合成：GPU 在独立图层上移动/淡化元素，不重排不重绘。
- **will-change** — 给浏览器的提示：这个元素马上要动了，提前提图层（最后手段）。
- **Layout thrashing** — 布局抖动：逐帧改 width/height/top/left 逼浏览器每帧重排。

## 原则（Principles）

- **Purposeful animation** — 目的性动画：动效要起功能（定位/反馈/表意），不纯装饰。
- **Anticipation** — 预备动作：大动作前先往反方向小蓄力，预告要发生什么。
- **Follow-through** — 跟随：主体停下后局部再晃两下，有重量感。
- **Squash & stretch** — 挤压拉伸：运动中变形，传达重量速度弹性。
- **Perceived performance** — 感知性能：对的动画让人觉得更快，哪怕实际没快。
- **Frequency of use** — 使用频率：越常看到的动画越要短、越收。
- **Spatial consistency** — 空间一致：元素跨状态保持身份和位置，用户不跟丢。
- **Reduced motion** — 尊重 `prefers-reduced-motion`：减弱而不断，去位移、留淡入。
