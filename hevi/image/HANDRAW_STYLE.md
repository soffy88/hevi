# 手绘风（handraw-style）接入说明

把 yang0/handraw-style 的编号提示词库接进 hevi 出图层：**选编号 →
按库的规则组装提示词 → 走 hevi 现有 GPT-Image 通道出图**。出图本身
不新增通道，新增的是"编号 → 提示词"这一层资产。

- 上游：https://github.com/yang0/handraw-style（本地副本
  `~/projects/_refs/handraw-style`，由 tarball 落库）
- 许可：MIT License with Attribution Requirement——自由使用/修改/
  商用，**必须保留作者 yang0 与上游仓库链接**。全文见
  `handraw_data/LICENSE`，署名落地见 `handraw_data/ATTRIBUTION.md`，
  且每次出图的 sidecar 都带 `attribution` 字段。

## 编号体系（数据在 `handraw_data/handraw_index.json`）

| 段 | 量 | 编号 | 说明 |
|---|---|---|---|
| 视觉风格 | 365 | `FA-001`…`FI-034`，或传统编号 `001`–`365` | FA–FI 九大类；FI 是写实摄影与视觉大片（品牌/杂志/摄影师/导演风） |
| 排版图型 | 167 | `SC-` 社媒卡 / `IG-` 信息图 / `SB-` 漫画分镜 / `IP-` IP 设计 / `EC-` 电商 | 只管构图与文字结构，不管画风 |
| 主题色 | 36 | `C-01`…`C-36`（也可按中英文名） | 单色统领画面基调 |
| 阶调 | 16 | `T-01`… | 明暗阶调参考，随目录一并可查 |

索引由 `handraw_data/build_handraw_index.py` 从上游
`skills/handdraw-style-prompter/references/*.json` 抽取，含上游
gpt-image-2 激活判定（与上游 `resolve_reference.py` 逐条对齐验证，
365 条零差异）：

- `name+style`（129 条）：风格名本身即可激活，只用名称出图；
- `name+style+traits`（199 条）：追加过滤后的核心风格特征
  （`positive_traits` 规则：剔除"避免/不要…"等负向片段）；
- `…+reference-image`（37 条）：名称与特征都不足，必须垫编号参考图
  ——出图时自动改走 `image.gpt_edit` 并附参考图隔离指令；参考图不在
  本仓库，在上游副本 `images/individual/<类>/<编号>.webp`（或
  `_grid.webp`），缺失时 sidecar 如实标 `reference_missing` 并退回
  文生图。

## 两个能力

### `image.handraw_styles`（目录）
列出/筛选风格、图型、主题色、阶调：`section`（all/styles/layouts/
colors/tones）、`category`（如 `FI`）、`query`（关键词，匹配名称/
特征/参考作者）、`limit`。产物 `handraw_catalogue.json`。

### `image.styled_generate`（出图）
参数：`style_id`（必填）、`theme`（必填）、`layout_id`、`color_id`
（可选）、`mode`（`pure` 纯图 / `text` 图文，默认 pure；选了图型
自动图文，电商图型 `EC-*` 除外）、`prompt_lang`（zh/en，默认 zh，
双语提示词都存进 sidecar）、`size`、`quality`。
组装规则与上游 `scripts/prompt_style.py` 逐字对齐（含图文模式的
固定后缀原文）。产物：`image.png` + `styled_sidecar.json`（编号、
最终提示词全文、激活来源、成本、署名）。
后端是 Monid GPT-Image（与 `image.gpt_generate` 同一通道同一
`MONID_API_KEY`），缺 key 按契约报 `CapabilityError`。

## 与其他风格体系的分工

- **creator-style-kit（`video.hyperframes_styles`）**：视频风格——
  字体/配色/动效/音效成套，套 beats 出 9:16 成片；handraw 是
  **静态图**的提示词层，两者不重叠。
- **lanshu（`hevi/skills/lanshu-explainer`）**：解说片的风格概念
  菜单（12 种），是"选哪种讲解风格"；handraw 是"这张图按什么
  视觉风格画"，层级不同。
- **storyfilm / 短篇封面环节**：需要按名定风格的封面或场景图时，
  传 `style_id` 给 `image.styled_generate` 即可（如故事封面用
  `FI-027` 韦斯·安德森式对称构图、产品图用 `FI-001`），不必再
  手写风格提示词；人物一致性仍走 `image.gpt_edit` 的参考图路线，
  handraw 的参考图只管画风、不管人物长相。
