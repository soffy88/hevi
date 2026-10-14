# 制作手艺知识库

中文影视制作手艺手册库。**纯数据目录**,不含任何 Python 代码;唯一的读取入口是
`hevi/production/craft_knowledge.py`。

这些文件写给 AI 导演 / 调度用:把它们按阶段注入到对应的 LLM 提示词里,模型就会按
真实的影视手艺干活,而不是按通用大模型的套路(念稿、切等长镜、字幕飘底部)。
每份文件都以 `##` 分节,末尾带 `## 检查清单`,可单独作为审稿清单使用。

## 文件索引

### 导演八阶段(`NN-` 前缀,顺序即流水线顺序)

| stage id | 文件 | 标题 | 主要内容 |
| --- | --- | --- | --- |
| `research` | `01-research.md` | 研究阶段手艺手册 | 证据分层、事实核验、结论可视化、选题打分 |
| `proposal` | `02-proposal.md` | 提案阶段手艺手册 | logline、七项必写、规模换算、复杂度配额、需求冻结 |
| `screenplay` | `03-screenplay.md` | 剧本阶段手艺手册 | 小说语言→剧本语言、可拍性边界、一场一拍点、字数换算 |
| `storyboard` | `04-storyboard.md` | 分镜阶段手艺手册 | 三类镜头、景别运镜、180 度/30 度、注意力脚本、动作弧 |
| `materials` | `05-materials.md` | 素材阶段手艺手册 | 技术规格、安全区、检索词、台账、把手、淘汰标准 |
| `editing` | `06-editing.md` | 剪辑阶段手艺手册 | 粗剪→精剪→锁画、切点、节奏阶梯、J/L-cut、转场 |
| `composite` | `07-composite.md` | 合成阶段手艺手册 | 分层顺序、透视光照匹配、抠像边缘、颗粒一致 |
| `review` | `08-review.md` | 审片阶段手艺手册 | 三层审片、响度硬指标、创意打分、返修分级 |

### 手艺域(`craft-` 前缀)

| stage id | 文件 | 标题 | 主要内容 |
| --- | --- | --- | --- |
| `subtitle` | `craft-subtitle.md` | 字幕手艺手册 | 版式与安全区、时间轴、断句、说话人标注、常见错误 |
| `grading` | `craft-grading.md` | 调色手艺手册 | 一级校准/二级匹配/三级创作、示波器指标、LUT 规范 |
| `music` | `craft-music.md` | 音乐手艺手册 | BPM 与镜长换算、结构对齐、情绪曲线、音量平衡、版权 |
| `voice_acting` | `craft-voice-acting.md` | 配音表演手艺手册 | 语速与停顿、重音、情绪阶梯、读音表、声线一致性 |
| `shot_prompt` | `craft-shot-prompt.md` | 镜头提示词手艺手册 | 九段结构、具体化替换、必须回避的画面、同系列一致性 |

### 阶段 → 文件映射

一个阶段可以挂多份文件(下游阶段会把相关手艺域一并带进来):

```
research     → 01-research.md
proposal     → 02-proposal.md
screenplay   → 03-screenplay.md
storyboard   → 04-storyboard.md, craft-shot-prompt.md
materials    → 05-materials.md
editing      → 06-editing.md, craft-subtitle.md, craft-music.md
composite    → 07-composite.md, craft-grading.md
review       → 08-review.md
subtitle     → craft-subtitle.md
grading      → craft-grading.md
music        → craft-music.md
voice_acting → craft-voice-acting.md
shot_prompt  → craft-shot-prompt.md
```

## 怎么加载

不要直接读文件,用加载器 —— 它负责别名解析、front-matter 解析、截断标记与错误提示:

```python
from hevi.production.craft_knowledge import (
    ALL_STAGE_IDS,   # 13 个 stage id,tuple
    STAGE_FILES,     # stage id -> 有序文件名 tuple
    list_stages,     # [{stage, title, files, chars}]
    load_stage,      # 单阶段 -> 拼接后的 Markdown
    load_stages,     # 多阶段 -> 分节拼接
    resolve_stage,   # "分镜" / "SUBTITLE" -> stage id
    knowledge_dir,   # 本目录的绝对路径
)

text = load_stage("storyboard", max_chars=8000)   # 截断时自带标记
both = load_stages(["research", "subtitle"])       # 两段带章节标题
sid = resolve_stage("分镜")                        # -> "storyboard"
```

行为约定:

- **未知阶段抛 `ValueError`**,不静默返回空串 —— 静默空串会让调用方以为"已注入手艺"。
- `max_chars` 截断拼接结果,尾部追加可见标记 `<!-- truncated at N chars -->`。
- **每次调用真读盘**,不做缓存 —— 知识库是人手改的,缓存会让改动不生效。
- 目录缺失或文件读不动也抛 `ValueError`,调用方自行 try/except 兜底。

## 在生产链里的用法

已经接好的位置(全部 fail-open:加载失败只打 warning,不影响产出):

| 位置 | 注入阶段 | 说明 |
| --- | --- | --- |
| `hevi/director/screenplay.py` | `screenplay` | `_SCREENPLAY_PROMPT` 的 `{craft_knowledge}` |
| `hevi/director/shot_list.py` | `storyboard` | `_SHOT_LIST_PROMPT` 的 `{craft_knowledge}` |
| `hevi/director/storyboard.py` | `storyboard` | `plan_shots` / `_plan_with_pool` 的提示词(端到端 planner 也走这条) |
| `hevi/studio/ops.py` | 任意 | `craft_knowledge` op,studio 工具面可直接取任意阶段 |

studio 工具面用法:

```python
from hevi.studio.ops import run_op

r = await run_op("craft_knowledge", {"stage": "subtitle", "max_chars": 4000})
```

## 编辑这份知识库

- 纯 Markdown,不依赖任何构建步骤,改完立刻生效(加载器不缓存)。
- 每份文件开头必须有 front-matter,且 `stage` 与 `title` 要正确,否则 `list_stages()` 会显示错名字。
- 数字与阈值(响度、字号、镜长、BPM…)是这套手册的价值所在。改数值请连带改掉相关文件里的交叉引用。
- 新增阶段:在本目录加文件 → 在 `craft_knowledge.py` 的 `STAGE_FILES` 里登记 → 在本表补一行。
