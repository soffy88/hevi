---
name: story-to-film
version: "0.1.0"
description: 一句话 → 故事 → 分镜 → 素材 → 配音 → 对齐 → 合成 → 成片的全链编排（HyperFrames 成片或 PixStag 镜头包两条最终路线）。
argument-hint: "--premise <一句话> [--route hyperframes|pixstag_package] [--shots N]"
allowed-tools: Bash, Read
homepage: https://github.com/helios-plat/hevi
license: MIT
user-invocable: true
---

# /story-to-film

hevi 的"一句话出成片"编排：给一句故事前提，全链自动产出 30-60 秒成片或 PixStag 镜头包。

核心编排器 `hevi/storyfilm/pipeline.py`，能力名 `story.film_from_prompt`（见 CAPABILITY_CONTRACT，按名字调用或 GET /api/capabilities）。

## 调用

```bash
cd "$HEVI_ROOT" && uv run python - <<'EOF'
import hevi.capabilities as caps
cap = caps.get("story.film_from_prompt")
result = cap.render_safe(
    {"premise": "一只小猫在雨夜里找回家的路",
     "render_route": "hyperframes", "max_shots": 5},
    "output/storyfilm/pilot", duration=0.0, aspect="9:16", seed=1)
print(result.mp4, result.qa["total_cost_usd"])
EOF
```

`render_route`:
- `hyperframes`（代码动画类）：故事板合成 + 配音音轨 + 字幕 → film.mp4 → film_gate / audio.earshot_gate 门禁。
- `pixstag_package`（真人类）：产镜头包 pixstag_package.json（每镜 first_frame / motion_prompt / duration），交 `video.pixstag_generate` 逐镜生成。

## 阶段契约（证据模式：每阶段产物落盘，状态按产物算）

| 阶段 | 产物 | 复用的能力/模块 |
|---|---|---|
| story | story.json / story.md / characters.json | Monid blockrun.ai gpt-4o-mini（$0.0022/次）；规划模式借鉴 chinese-novelist（钩子+人物档案+节拍，缩放到短片） |
| images | images/character.png + images/shot_*.png | image.gpt_generate（定妆）→ image.gpt_edit（同一人物换景；≤6 图预算） |
| narration | narration.wav | LuxTTS 本地（soffy/en_male），免费 |
| alignment | alignment.json | audio.forced_align 的引擎：ElevenLabs forced alignment，实测词级时间戳 |
| shots | shots.json | 分镜表：narration / image / start_ms / end_ms + first_frame / motion_prompt / duration（PixStag 交接字段） |
| render | film.mp4 或 pixstag_package.json | hyperframes 线走 pipeline.render_motion_film（逐镜 Ken Burns 运镜 + 静态字幕带，ffmpeg 合成） |
| gates | gates.json | film_gate 查画面；audio.earshot_gate 查声音（未注册就记 skipped） |
| delivery | delivery.json | 阶段台账：状态 / 花费 / 产物，失败阶段记 error 不伪造 |

说明（已知取舍）：story 段为本线自有 LLM draft（`_STORY_SYSTEM`/`_STORY_USER` 直出 beats），未复用 storyplan/storygraph——因为 beats 需同时产 `visual_en`/`motion_prompt` 供图像生成与 PixStag 镜头包链使用，StoryPlan 模型不承载这两个字段；规划质量门（story_check/kids.story_gate）目前未接入本线，属已知取舍。

## 纪律

- 付费阶段（story、images、alignment）按 Monid 端点费率实时扣费；先跑小样（≤6 图、一次对齐）再放量。
- 一阶段失败则整个编排失败并在 delivery.json 里记 error，不出半成品充数。
- MONID_API_KEY 必须在环境里（服务端 env 或运行时从 ~/.config/monid 注入）；LuxTTS 服务须可达（HEVI_LUXTTS_URL）。
- 故事创意由 LLM 产生，调用方（agent/人）对前提的合规负责；不得用于肖像权未确认的人物。
