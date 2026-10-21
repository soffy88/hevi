# 手绘角色表情 rig（expression rig）

hevi 的参数化角色脸：一个角色只定义一次（model sheet），之后所有表情都靠
**组合部件**生成——视角 × 表情预设 × 眼/嘴/眉/附加件，而不是每个表情单独
画一张互不相干的图。这样同一角色在整条片子里不换脸，表情又能按剧情随取
随组。

实现：`hevi/layer4_legacy/handdraw/expression_rig.py`（纯程序绘制，走
[rough_stroke.md](rough_stroke.md) 的抖动线条技法；零付费出图、零网络、
CPU only、seed 确定性）。结构上只借鉴「model sheet + 部件组合 +
`(view, emotion, eyes, mouth)` 调用约定」这一**方法**，不借任何具体角色
的造型（红线见文末）。

## rig 规格（schema）

规格用仓内惯例的 frozen dataclass（与 `rough_stroke` / handdraw styles
一致），可经 `CharacterRig.model_sheet()` 序列化成 JSON；渲染请求的契约
是同文件里的 `FACE_REQUEST_SCHEMA`（JSON Schema，与能力注册表的校验机
制共用一份枚举）。一个 rig 包含：

- **角色本体（不许随表情变）**：`palette` 配色、`proportions` 比例、
  `identity_marks` 身份标记（轮廓、标志物、固定腮红等）、每个视角的脸部
  布局（眼/嘴/眉/颊的锚点）。
- **视角 views**：`front`（正面）、`three_quarter`（3/4 侧）、`profile`
  （正侧面）。新角色至少给 2 个视角。
- **部件目录**：eyes / mouths / brows / extras 四类，每类是命名样式集，
  彼此正交、可任意组合。
- **表情 emotions**：命名预设 = 一组固定的部件组合（可再叠加 gaze 瞳孔
  偏移、eye_scale、cheek_scale、tilt 头部倾斜）。

## 表情命名与调用约定

- 标识符一律 lower_snake_case 英文 id；中文只进文档和展示名，不进代码
  标识符。
- 调用：`image.expression_rig`（单张）/ `image.expression_contact_sheet`
  （验收网格图）；技法层 `render_face(view=…, emotion=…, eyes=None,
  mouth=None, brows=None, extras=None, seed=…, size=…)`。
- **预设优先、部件可覆盖**：只给 `emotion` 用预设组合；给 `eyes` /
  `mouth` / `brows` / `extras` 中任一项，只覆盖该项，其余仍走预设。
  `extras` 一旦给出即整体替换预设的 extras（不是追加），避免调用方猜
  不到最终组合。
- **非法名 fail closed**：未知视角/表情/部件名一律抛错并列出合法值，
  不猜、不回退到默认表情假装成功。
- **确定性**：同（角色, 视角, 表情, 部件, seed, size）必同图（PNG 逐
  字节一致）；模块不碰全局 RNG。

## 部件组合规则

- eyes 目录（10）：`dot` 圆点眼、`wide` 睁大眼、`arc_smile` 弯月笑眼、
  `half_lid` 半睁眼、`droopy` 垂眼、`line` 线眼、`star` 星星眼、
  `spiral` 蚊香眼、`angled` 怒眼、`wink` 眨眼（组合式：角色左眼弯月、
  右眼圆点；正侧面只剩一只眼时取弯月）。
- mouths 目录（14）：`smile` 微笑、`smile_open` 张嘴笑、`laugh_open`
  大笑、`flat` 直线嘴、`slant_flat` 斜直嘴、`frown` 撇嘴、`smirk` 歪嘴
  笑、`cat` 猫嘴、`small_o` 小圆嘴、`big_o` 大圆嘴、`wavy` 波浪嘴、
  `grit` 咬牙、`yawn` 哈欠、`tongue_out` 吐舌。
- brows 目录（6）：`none`、`neutral`、`raised` 上扬、`worried` 担忧
  （内端高）、`angry` 怒眉（内端低）、`one_raised` 单挑眉（角色左眉
  上扬、右眉中性）。
- extras 目录（6，可叠加、不可重复）：`blush_strong` 加强腮红、
  `tear` 泪滴、`sweat` 汗滴、`sparkles` 闪光、`zzz` 睡意符号、
  `anger_mark` 怒气标记。
- 组合合法性只看「名字在目录里」：目录内任意组合都必须能出图；预设
  只是常用搭配，不是白名单。

## 表情预设（demo 角色现行 16 个）

`neutral` 平静、`happy` 开心、`joy` 大笑、`playful` 俏皮、`proud` 得意、
`shy` 害羞、`surprised` 惊讶、`excited` 兴奋、`thinking` 思考、
`confused` 疑惑、`sad` 难过、`angry` 生气、`scared` 害怕、
`disgusted` 嫌弃、`sleepy` 困倦、`dizzy` 头晕。每个预设的具体部件组合
以 `EMOTIONS` 表和 model sheet 序列化结果为准，不在本文重复抄写。

## 验收：contact sheet

任何 rig 改动（新表情、新部件、布局调整）都要跑一遍
`image.expression_contact_sheet`：行 = 视角、列 = 表情的网格图。自查两
条：①每个表情格一眼可区分（靠部件差异，不靠标注文字）；②整张图里角
色轮廓、比例、配色、身份标记不变（不换脸）。demo 角色的现行验收图在
`output/expression_rig/tuantuan_contact_sheet.png`（`output/` 为本地产
物目录，与 `output/rough_stroke_compare/` 先例一致）。

## 原创角色红线（最重要）

- rig 的**结构与方法**（视角 × 表情 × 部件组合、model sheet、调用约
  定）是通用做法，可借鉴；**任何已有 IP 角色的造型、轮廓、配色、标志
  物、资产文件一律不许复制或仿作**——包括但不限于任何厂商吉祥物。
- 本仓 demo 角色「团团」为 100% 原创设计：奶黄色圆团子身体（底部微
  微摊开）、头顶螺旋卷呆毛、珊瑚色腮红、墨褐色描边，程序绘制产生，
  无任何外部资产。
- 新增角色同样必须原创：先写清 identity marks 并自查与已知 IP 无相
  似元素，再进目录；拿不准就不用——宁可角色朴素，不许蹭形。
