---
name: edit-craft
description: 剪辑成片层。策略确认 → 词级打包 → EDL 硬规则 → 分段渲染 → 成片自检。对标 video-use 生产正确性。
---

# Edit Craft（剪辑成片层）

## 原则

1. **文本 + 按需视觉**：LLM 主读 `takes_packed.md`，不把全帧塞进上下文。
2. **音频优先**：切点来自词边界与静音间隙。
3. **Ask → Confirm → Execute → Self-eval**：策略未确认禁止动刀。
4. **硬规则不可静默违反**；口味可商量，正确性不可商量。

## 硬规则（12 条）

1. **字幕最后烧录** — 否则被 overlay 遮挡。
2. **分段 extract → concat** — 有 overlay 时禁止单 pass 双重编码。
3. **每刀 30ms 音频 fade** — 防爆音。
4. **overlay 必须 PTS 偏移** — `setpts=PTS-STARTPTS+T/TB`。
5. **master SRT 用输出时间轴偏移** — `out = word.start - seg_start + seg_offset`。
6. **绝不在词中间下刀** — 吸附词边界。
7. **cut edge padding 30–200ms** — 吸收 ASR 漂移。
8. **只用词级 verbatim ASR** — 禁止估算字幕作剪辑依据。
9. **transcript 按源缓存** — 源未变不重转。
10. **策略确认门** — `strategy_confirmed=true` 才能 `render_edl`。
11. **输出进 `edit/`** — 源文件只读。
12. **自检不通过禁止归档** — 最多 3 轮自动修复，之后交人。

## 目录

```
<videos_dir>/
├── <sources untouched>
└── edit/
    ├── project.md
    ├── takes_packed.md
    ├── edl.json
    ├── transcripts/*.json
    ├── clips_graded/
    ├── master.srt
    ├── verify/
    ├── preview.mp4
    ├── final.mp4
    └── self_eval.json
```

## 调用

```python
from hevi.skills.edit_craft import edit_craft_skill_execute

# 1) 手写 EDL
result = await edit_craft_skill_execute(
    videos_dir="/path/to/takes",
    edl={
        "sources": {"A": "/path/to/A.mp4"},
        "ranges": [{"source": "A", "start": 1.0, "end": 5.0, "beat": "HOOK", "reason": "..."}],
        "strategy_confirmed": True,
    },
    preview=True,
)

# 2) talking-head 自动去 filler（先 plan，再确认）
from hevi.assembly import talking_head_cleanup

plan = await talking_head_cleanup(
    source_video=Path("take.mp4"),
    transcript=Path("edit/transcripts/main.json"),
    work_dir=Path("session"),
    strategy_confirmed=False,  # 只出方案
)
# 审阅 session/edit/edl.json 后：
final = await talking_head_cleanup(
    source_video=Path("take.mp4"),
    transcript=Path("edit/transcripts/main.json"),
    work_dir=Path("session"),
    strategy_confirmed=True,   # 才渲染
)
```

## 自动选切（filler / silence）

- 强 filler：`um/uh/呃/嗯/啊` 等直接剪
- 弱 filler：短词口头禅；长词保留防误杀叙事
- 静音 ≥ 0.4s：压缩，留 ~120ms 呼吸
- 产出 `filler_plan.json` + 建议 `edl.json`

## timeline_view

渲染后在每个 cut 边界 ±1.5s 生成 filmstrip+波形到 `edit/verify/timeline/`，供自检与人工复查。

## 反模式

- 未确认策略就渲染
- 词中下刀
- 字幕先于 overlay
- 硬切无 fade
- 估算字幕当剪辑依据
- 自检失败仍归档
