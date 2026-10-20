---
name: lanshu-explainer
version: "1.0.0"
description: Lanshu 讲解片工作流的 hevi 内化版——12 种 explainer 风格目录、证据门禁状态机（8 个状态按磁盘产物计算）、词级时间戳驱动的音频锁时间轴。用于知识讲解/科普类视频的选题、定风格、制片、交付全链路。
argument-hint: "选题 + 风格编号（如 v8 黑板报）+ 文案/主题"
allowed-tools: Bash, Read
homepage: https://github.com/cclank/lanshu-create-ai-presenter-video
license: MIT
user-invocable: true
---

# /lanshu-explainer

讲解片工作流（内化自 cclank/lanshu-create-ai-presenter-video，MIT）：从一个主题或脚本出发，
按"音频锁时间轴 + 证据门禁 + 风格目录"三件套生产可交付的讲解视频。成片渲染走 hevi 的
HyperFrames/代码动画线；配音走 hevi 现有 TTS；词级时间戳走 `audio.forced_align`。

## 两条路线

| 路线 | 画面 | 输入 | 状态 |
| --- | --- | --- | --- |
| styled（风格片） | 无真人出镜，按 12 种风格之一把每句文案"演"出来，16:9 | 主题或脚本（配音后锁定） | ✅ **可用**：全线走 hevi 现有免费线——`explainer.script` / `explainer.visual_plan` / `explainer.render`（能力目录在册）→ hevi 现有 TTS 配音 → `audio.forced_align` 词级时间戳 → `story.json` → 风格 kit → HyperFrames 渲染（`video.hyperframes_styles` / `video.hyperframes_styled_render`） |
| presenter（数字人） | AI 主播出镜 + 字幕/关键词动图 | 主题/脚本 + 经授权的主播肖像 | ⛔ **未实现（设计内待接）**：本 skill 未接入任何数字人生成 provider，能力目录中无 presenter/数字人能力；缺齐三样之前不要尝试走这条路（见下） |

默认走 styled；用户明确要数字人出镜时说明本 skill 的 presenter 路线尚未接通，不要承诺出片。

### presenter 路线：未接，缺三样

以下三样缺一不可，全部就位前 presenter 路线视为不存在：

1. **数字人生成 provider**：本 skill 没有接入任何 presenter/数字人生成服务（能力目录里只有
   `explainer.*` 与 `video.hyperframes_*`，无 presenter 条目）。注：hevi 其他域另有
   `hevi/digital_human/` 代码，但本 skill 不调用它、两者未接线，不能据此宣称 presenter 可用。
2. **配音 key**：上游 presenter 路线用的 MiniMax 配音未接入本 skill（无 key 配置）；
   本 skill 的配音与词级时间戳走 hevi 现有 TTS + `audio.forced_align`，只覆盖 styled 路线。
3. **肖像授权流程**：主播形象涉及肖像权，必须先有经授权的主播肖像与人工确认环节；
   目前没有这条确认流程，不要用未授权形象生成。

另注：`styles.json` 的 meta 里写有"竖屏需求走 presenter 路线或另行裁剪"——presenter
路线未接通之前，竖屏只能走"另行裁剪"，不要按 presenter 路线排期。

## 风格目录

12 种风格共用一套接口：`story.json` 在任何风格里都变成逐字字幕、章节条、结尾金句和一帧复习页。
前 9 种是画风（同一份讲稿随便换），后 3 种是讲法（画面 + 讲稿结构一起变）。全部 16:9。

完整目录（含适用场景、视觉契约、配稿指南、语速、复习页时长）见 `styles.json`。
幼儿科普优先看：`v8-chalkboard` 黑板报、`v3-notebook` 手帐、`v4-paper` 立体书、
`v9-clay` 黏土小城、`v5-comic` 波普漫画。

选风格后再定稿（每种风格擅长演绎的句子不一样，讲稿和配音按风格写）。
拿不准就先多出几版草稿（`--dry` 估时、无配音），看完再定。

## 证据门禁状态机

状态只能往前走，且只能由证据推进，不能嘴上宣布：

```text
intake
→ content_locked       预检通过的报告 + 脚本 + 节拍表
→ audio_locked         可解码的终版配音 + ASR 校验报告（styled 路线另需非草稿 story.json）
→ visual_plan_locked   时间线 + 分镜 + plan.status = approved
→ presenter_generated  styled 路线：film 工程目录 + 视觉评审（无数字人出镜）
→ composition_checked  合成报告
→ rendered             可解码成片（含视频流和音频流）
→ verified             master + share + 交付报告（响度检查通过）
```

用法：把产物路径记进 `job.json`，然后让工具按磁盘证据算出真实状态：

```bash
python3 tools/check_state.py <job.json>        # 只报告，不写
python3 tools/check_state.py <job.json> --write  # 把证据支持的状态写回 job.json
```

状态机实现是纯 stdlib 的可复用模块（`tools/check_state.py`），任何制片 job 都能套用。
这与 hevi 的能力契约/门禁哲学一致：失败只抛问题列表，不虚报状态。

状态机不会把 presenter 误报为可用：状态名 `presenter_generated` 是上游沿用的名字——
styled 路线下它只表示"film 工程目录就绪 + 视觉评审通过"（无数字人出镜）；非 styled
（presenter）路线下，`check_state.py` 要求三类硬证据同时在盘才放行：`capabilities.main_presenter`
记录了 provider/模型/任务 ID、`assets/video/selected/` 下有可解码的主播视频、人工视觉评审记录。
证据缺失时状态停在 `visual_plan_locked`，手填更高的 `job.state` 会被判 `consistent: false`，
`--write` 也只会按证据回退。在 presenter 三样（provider / 配音 key / 肖像授权）接齐之前，
presenter 路线的 job 不可能凭证据推进到 `presenter_generated`。

## 音频锁时间轴（audio-locked timeline）

配音是全片主时钟：字幕、切镜、动图、片长全部从词级时间戳推导。
hevi 的词级时间戳来源：`audio.forced_align`（实测，is_estimated=False）或 TTS 原生边界。

`tools/story_audio_lock.py` 把词级时间戳装进 lanshu 的 `story.json` 契约：

```python
from tools.story_audio_lock import story_from_word_timings, check_audio_lock

story = story_from_word_timings(
    title="主题",
    chapters=[{"key": "problem", "title": "问题", "lines": ["第一句文案。", "第二句文案。"]}],
    word_timings=[{"word": "第", "start_ms": 400, "end_ms": 580}, ...],  # audio.forced_align 输出
    voice="hevi tts · soffy · speed 1.0",
)
problems = check_audio_lock(story)  # 空列表 = 时间轴自洽（无重叠、无倒序、覆盖完整）
```

`story.json` 字段：`lines[i]` = {i, text, start, end, words:[[词, 秒], ...], chapter}；
`chapters` = {n, key, title, start, end}；另有 `end`（结尾金句）、`recap`（复习页）、
`notes`（分镜节拍备注，不配音）。风格 kit 的 `index.html` 直接消费这份 JSON。

## provider 对应表（不重复造）

| lanshu 需要的 | hevi 现有 | 说明 |
| --- | --- | --- |
| 配音 + 词级时间戳 | `audio.forced_align` / TTS 线 | MiniMax provider hevi 没有，不硬接 |
| 成片渲染（HyperFrames） | `hevi/video/hyperframes_service.py` | 已有 |
| 成本护栏（先小样、先报账、重试上限） | `hevi/skills/cost_tracker` | 已有，直接用 |
| provider 运行时选择 | `HEVI_TTS_ALIGNMENT_PROVIDER` 等环境切换 | 已有，同范式 |
| 响度归一（交付检查） | ffmpeg loudnorm / `final_qc` skill | 已有 |

## 不补的 lanshu 能力及原因

- MiniMax 配音 provider：hevi 没有该 key，不硬接；词级时间戳改由 `audio.forced_align` 实测提供。
- presenter/数字人生成：设计内待接、未实现。本 skill 未接入任何数字人生成 provider、无
  MiniMax 等配音 key、且无肖像授权确认流程；三样缺齐之前不要尝试走这条路（详见上方
  「presenter 路线：未接，缺三样」）。
- `finalize_delivery.sh` 的两遍响度归一：已有 `final_qc` / ffmpeg 链路覆盖，不重复。
- 风格 kit 的 HTML starter 工程（`kits/<style>/starter`）：12 套工程较大，按需从上游仓库取用，
  不整体拷贝；`styles.json` 记录了每套 kit 的源码路径。

## 来源

- 上游：https://github.com/cclank/lanshu-create-ai-presenter-video（MIT，commit 762d3ee，2026-10-20 内化）
- 状态机改编自上游 `scripts/check_state.py`；`story.json` 契约与上游 `explainer/tools/story.py` 输出一致。
