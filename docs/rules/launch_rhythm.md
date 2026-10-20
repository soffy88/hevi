# 发布片规则卡（launch rhythm）

> 出处与方法：本卡的数字来自 huashu-motion 的 `rhythm.md` 实测——量过
> 21 支真实产品发布片的时间轴，再拆过 142 支高互动片的切点与能量分布。
> 本卡用自己的话重述这些结论，并按 hevi 的产品线改写成可执行口径；
> 每条硬规则都在 `motion.rhythm_sheet`（`hevi/motion/rhythm_sheet.py`）
> 里有对应的校验/实测，不靠评审时凭感觉争论。
> 声音响度/峰值的细则不在本卡重复，以 [audio_gate.md](audio_gate.md) 为准；
> 剪辑通则见 [editing_basics.md](editing_basics.md)。

## 这张卡管什么

产品发布片（launch film）与叙事短片不同：它没有情节可借力，观众的
注意力全靠**时间轴上的调度**——什么时候密、什么时候停、产品（hero）
在哪一刻以什么姿态落地。本卡只管这一件事：一支发布片在时间上怎么走。
画面长什么样由 CSK 风格管（见文末「与 hevi 现有资产的关系」）。

开工顺序：先选路线 → 按能量曲线排 stretch（段落）→ 填节奏单 →
`motion.rhythm_sheet` 校验通过再生成/装配 → 成片后用同能力的
measure 模式验收。

## 路线三选一

| 路线 | 形态 | 适用 |
|---|---|---|
| `continuous` | 一镜到底或伪一镜：镜头不断，靠运镜与主体运动推进 | 单一产品、单一卖点；空间关系本身就是卖点（穿戴、家居、空间产品） |
| `montage` | 快切蒙太奇：每切一个新信息点，切点踩音头 | 卖点多、功能列举型；软件功能演示、参数秀 |
| `hybrid` | 主体段落连续推进，高潮段切入 montage 爆发，收尾回到连续 | 大多数发布片的默认选：既有产品完整感，又有爆发点 |

选错路线的典型症状：卖点有五个却走 continuous（中段必闷）、只有一个
卖点却走 montage（切无可切，只能重复切同一信息）。路线写进节奏单的
`route` 字段，校验器只认这三个值。

## 能量曲线形状

一支发布片的时间轴大致是同一条曲线，四个锚点：

1. **钩子 ≤ 3 秒。** 第一个 stretch 必须是 `hook`，且其内首次事件
   （一个切点、一次运动启动、一个信息点）在 3 秒内出现。3 秒还没有
   任何事发生，观众已经划走，后面做得再好也救不回来。
2. **中段爆发在全片约 37% 处。** 在全片 30%–60% 的窗口内，必须有一段
   密度拉满的 stretch：切点密度达到 **5–8 切 / 5 秒**的量级（节奏单里
   以 `events_per_bar ≥ 4` 记）。爆发太靠前，后半程全是下坡；太靠后，
   观众等不到。校验口径：全片没有任何一段达到爆发密度 = 不合格；
   有爆发段但落在窗口外 = 警告（位置偏了，不是没有）。
3. **hero 落在最强音乐点。** 全片恰有一个 hero stretch（产品正式
   亮相/定妆的那一段），它的计划能量必须是全片最高，且排在爆发段
   之后——爆发负责把情绪推上去，hero 负责接住。hero 提前出场或
   能量不是最高，都算顺序/调度错误。
4. **drop 前停顿（可选）。** 在高潮（peak/hero）之前可以插一段
   `stop`：0.5–1.6 秒，画面与声音一起收住，制造"屏住呼吸"的空缺，
   紧跟其后必须是 peak 或 hero——停顿后面接平段，停顿就白停了。
   停顿是可选件，但一旦用了，时长与跟随关系是硬规则。
5. **收尾落点。** 最后一段是 `resolve`：密度降回 1–2，给品牌/
   slogan 一个安静的落点，不要以高密度硬切结束（那是没剪完，
   不是有冲击力）。

## 密度表

`events_per_bar` = 每小节的事件数（切点、运动启动、信息点都算事件）。
一小节时长由 BPM 定：`240 / BPM` 秒（4 拍）。

| role | events_per_bar | 说明 |
|---|---|---|
| hook | 2–4 | 一上来就有事，但别把高潮的料先抖完 |
| build | 2–4 | 持续给新信息，密度稳步抬 |
| stop | 0–1 | 计划内停顿，唯一的"允许空" |
| peak | 4–8 | 爆发段：5–8 切 / 5 秒就在这一档 |
| resolve | 1–2 | 落点，只留一个记忆点 |

**死段规则（硬）：** 除计划内的 stop 外，任何 stretch 都不许"没事
发生"——`events_per_bar == 0` 直接不合格；一段拉长到超过约 2 小节
（`2 × 240 / BPM` 秒）且密度低于 1，同样判死段。换成制作口径就是：
任何约 2 小节以上的跨度里必须有新事件，唯一的例外是你亲手写进
节奏单的那次停顿。

## 对比调度

节奏不只是密度，还有**段与段之间的差异**。每个段界至少改变两项，
可选维度共七项：景别、速度、缓动族、机位、密度、色彩、音乐织体
（节奏单 `changes` 字段就填这些维度名，声明"本段相对上一段改了
什么"）。

- 非首段 `changes` 少于 2 项 = 不合格：只换一项，观众感知不到段落
  切换，片子会糊成一整段。
- peak / hero 段（drop 处）要**全变**的姿态：至少 4 项，实务上是
  景别、速度、密度、音乐织体一起翻面。drop 处只改一两项，高潮
  就只是"稍微热闹一点"，不是高潮。

## 音乐侧

- **BPM 不是杠杆。** 实测的发布片 BPM 分布在 89–130 之间，快慢
  都有爆款也有哑炮；决定节奏感的是**切点密度与音头的对齐**，
  不是把曲子整体加速。选曲先看音头清不清楚、织体有没有可用的
  强点给 hero 落，而不是先看 BPM 数字。
- **切点踩音头。** 半拍/全拍切换：build 段切点踩全拍即可，peak
  段可以加密到半拍——密度翻倍感就是从这来的；montage 路线每切
  必中一击（一个切点对一个音头/打击点），切在音头之间会显得
  "剪辑跟不上音乐"。
- **drop 前的声音手法。** 停顿段在音乐侧的对应动作是 tape stop
  （磁带停转式的整体下滑静音）或一记反向镲先行——先把声音抽走
  或倒吸一口，drop 的第一击才够响。只停画面不停声音，停顿感
  会打对折。
- hero 的落点要对齐全曲最强音乐点，排片时先在曲子里标出那个点，
  再反推前面各段的时长，不要先排画面再找音乐凑。

## 节奏单格式

节奏单是本卡的人类可读版与机器版的同一份东西：人类读下面这张表，
机器读同结构的 JSON（schema 见 `hevi/motion/rhythm_sheet.py` 的
`RhythmSheet` / `Stretch`）。

| 字段 | 含义 |
|---|---|
| `title` | 片名 |
| `route` | `continuous` / `montage` / `hybrid`，三选一 |
| `bpm` | 音乐 BPM（只用于换算小节时长，不作质量判定） |
| `duration_s` | 全片时长（秒） |
| `stretches[]` | 段落列表，必须从 0 连续覆盖到 `duration_s`，不许有缝、不许重叠 |

每个 stretch：

| 字段 | 含义 |
|---|---|
| `name` | 段名（报告里引用它） |
| `start_s` / `end_s` | 起止秒，与相邻段首尾相接 |
| `role` | `hook` / `build` / `stop` / `peak` / `resolve` / `section` |
| `energy` | 计划能量 0–10 |
| `events_per_bar` | 每小节事件数（密度，对照上文密度表） |
| `changes` | 相对上一段改变的维度名列表（首段可空） |
| `music` | 音乐说明（自由文本：音头、织体、tape stop 等） |
| `hero` | 是否 hero 段（可选，全片恰一个） |
| `first_event_s` | 本段首次事件的绝对秒（可选，只对 hook 有判定意义；缺省取 `start_s`） |

示例（30 秒 hybrid 发布片，骨架示意）：

```json
{
  "title": "示例新品发布片",
  "route": "hybrid",
  "bpm": 120,
  "duration_s": 30,
  "stretches": [
    {"name": "钩子", "start_s": 0, "end_s": 3, "role": "hook",
     "energy": 6, "events_per_bar": 3, "changes": [],
     "music": "第一记音头直接进", "first_event_s": 0.5},
    {"name": "铺垫", "start_s": 3, "end_s": 11, "role": "build",
     "energy": 7, "events_per_bar": 3, "changes": ["shot_scale", "density"],
     "music": "全拍切点"},
    {"name": "爆发", "start_s": 11, "end_s": 16, "role": "peak",
     "energy": 9, "events_per_bar": 6,
     "changes": ["speed", "density", "music_texture", "colour"],
     "music": "半拍加密，每切一击"},
    {"name": "屏息", "start_s": 16, "end_s": 17.2, "role": "stop",
     "energy": 2, "events_per_bar": 0, "changes": ["speed", "music_texture"],
     "music": "tape stop"},
    {"name": "产品定妆", "start_s": 17.2, "end_s": 24, "role": "peak",
     "energy": 10, "events_per_bar": 4,
     "changes": ["shot_scale", "camera", "colour", "music_texture"],
     "music": "最强音乐点，hero 落此", "hero": true},
    {"name": "落点", "start_s": 24, "end_s": 30, "role": "resolve",
     "energy": 4, "events_per_bar": 1, "changes": ["density", "colour"],
     "music": "织体收薄，留品牌音"}
  ]
}
```

## 开工前自查清单

- [ ] 路线选了吗，与卖点数量匹配吗？
- [ ] 节奏单 stretches 从 0 连续覆盖到片尾，没有缝/重叠？
- [ ] hook 的首次事件 ≤ 3 秒？
- [ ] 30%–60% 窗口内有爆发段（`events_per_bar ≥ 4`），位置靠近 37%？
- [ ] hero 恰一个、能量全片最高、排在爆发之后、落在最强音乐点？
- [ ] 用了 stop 的话：0.5–1.6 秒，且紧跟 peak/hero，音乐侧有 tape stop 或反向镲？
- [ ] 每个段界至少变两项，drop 处至少变四项？
- [ ] 除 stop 外没有死段（密度为 0，或长段低密度）？
- [ ] 收尾是低密度 resolve 落点，不是高密度硬切结束？
- [ ] `motion.rhythm_sheet` 只校验模式（不传 `media_path`）跑过且 `ok`？

## 验收方法

成片（或粗剪）出来后，用同一能力的 measure 模式对表：

```python
from hevi import capabilities as caps
import hevi.capabilities.rhythm_sheet  # 本模块尚未接 __init__，先 import 注册

cap = caps.get("motion.rhythm_sheet")
result = cap.render_safe(
    {"sheet": sheet_dict, "media_path": "output/launch.mp4"},
    out_dir, duration=30, aspect="9:16", seed=1,
)
print(result.qa["ok"], result.qa["dead_stretches"], result.qa["shape_correlation"])
```

measure 模式逐段实测（`hevi/motion/rhythm_sheet.py: measure_rhythm`）：

- **音频 RMS（dB）**：ffmpeg 解码单声道 16 kHz 后按段计算；
- **画面运动量**：ffmpeg 抽 10 fps、缩到 96×54 灰度，逐帧平均绝对差，
  按段聚合；低于阈值（1.0）且该段不是计划内 stop → `dead_flag`，
  汇总进 `qa["dead_stretches"]`——计划里有事、成片里没动静，就是
  这一项在抓；
- **能量形状**：计划能量归一化曲线与实测音频能量归一化曲线逐段作差
  （`energy_diff`），并给出整体形状相关系数 `shape_correlation`——
  接近 1 说明成片的能量走向跟节奏单是一回事；明显偏低，先看逐段差
  最大的那一段，多半是爆发没爆起来或 hero 段声音没顶上去。

报告落 `rhythm_sheet_report.json`。媒体文件不可读直接抛
`CapabilityError`——验收不了的片子不许静默放行，这一点与
`qa.export_gate` 同口径。校验不通过是数据（`qa["ok"] == False` +
`qa["violations"]`），拦不拦由管线决定。

## 与 hevi 现有资产的关系

- **CSK 18 风格管"长什么样"，本卡管"时间上怎么走"。** CSK
  （`image.gpt_generate` / styled 线在用的 18 种代码风格）决定一帧
  的视觉语言：配色、版式、质感；本卡决定这些帧在时间轴上以什么
  密度、什么顺序、什么能量出现。两者正交：一支片可以 CSK 风格
  完全对，但节奏全错（hook 迟到、没有爆发、hero 不在强点）；
  反之节奏对、风格错也是另一回事。评审时分开下结论，不要用一句
  "感觉不对"混过去。
- **`motion_library.py` 的桥接桩不构成已实现，如实标注。**
  `hevi/creative/shotlang/motion_library.py` 里有一个自称"桥接
  20 种运动语言与节奏单"的 `MotionLibraryBridge`，实际是 WIP 桩：
  只有 4 条硬编码条目（core-focus / fast-cut / glitch-stream /
  number-zoom，含名称与一句话描述），没有校验、没有实测、没有
  接进任何能力注册或产品线。本卡与 `motion.rhythm_sheet` 不依赖
  它；将来若真要做运动语言库，应以本卡的节奏单为时间轴契约重新
  立项，而不是把那个桩当作已有资产引用。
- **om check 式文字遮挡 / WCAG 对比度检查未在 hevi 落地，原因是
  方法前提不成立。** 那类检查需要知道每个文本框的位置与前景/
  背景色（DOM/图层信息），而 hevi 的文字是程序绘制进画面的——
  成片只有像素，没有文本框元数据，任意成片都无法按该法事后
  检查；要在生成侧做，就得让每条绘制文字的线都上报图层信息，
  那是另一项工程，不在本卡范围。其风险侧面由现有门禁覆盖：
  黑帧/近黑帧比例与静态画面由 `qa.export_gate`（黑帧口径）与
  verdict 的 freezedetect 管，画面有没有在动由本卡 measure 的
  运动量管。文字可读性本身目前靠评审人工看（见
  [editing_basics.md](editing_basics.md) 第 10 条的字幕 QA，那是
  字幕轨一侧的口径，不冒充成片像素级对比度检查）。

## 来源

- 方法与实测数据：huashu-motion 的 `rhythm.md`（量 21 支真实发布片、
  拆 142 支高互动片），仓库 MIT License。
  https://github.com/alchaincyf/huashu-motion
- 致谢 huashu-motion 作者花叔（alchaincyf）——本卡是把他的实测结论
  按 hevi 的能力契约重述与落地，数字口径（37% 爆发点、密度档、
  BPM 89–130 分布等）来自他的测量，不是我们自己测的。
