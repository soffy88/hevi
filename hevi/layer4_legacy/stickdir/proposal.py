"""导演提案组装 —— proposal.json + 人读 proposal.md(中文)。

setup gate(STICKDIR_TASK.md §(a)):缺 aspect/style 报错, 不得静默默认;
duration 缺省 60。旁白经 :mod:`narration` 重写并过无编造校验;分镜经
:mod:`storyboard` 生成并过 continuity/白名单校验。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hevi.layer4_legacy.stickdir import (
    SCHEMA_VERSION,
    narration,
    schema,
    storyboard,
    styles,
    whitelist,
)
from hevi.layer4_legacy.stickdir.narration import Narration
from hevi.layer4_legacy.stickdir.storyboard import Storyboard


class SetupError(ValueError):
    """setup gate 未满足(缺 aspect/style)。"""


#: 全片统一的旁白音色(voice-continuity: 一条视频一个冻结音色)
VOICE_PROFILE_ZH = (
    "一位画外成年男声解说, 全片同一人。普通话标准, 温润干净的中低音, 无沙哑无气声;"
    "沉稳对话式叙述, 音高起伏克制, 语速平稳, 近距离干燥棚录。"
    "情绪起伏交给画面与音乐, 不换音色、不切角色对白。"
)

VOICE_PROFILE_EN = (
    "One off-screen adult male narrator throughout. Standard Mandarin, warm clean "
    "medium-low voice, no raspiness or breathiness. Calm conversational delivery, "
    "restrained pitch variation, steady speaking pace, close dry studio sound. Keep the "
    "same vocal timbre, register, accent, pace and recording quality throughout; emotional "
    "progression belongs to the visuals and music."
)


@dataclass
class Proposal:
    data: dict[str, Any]
    markdown: str

    def to_json(self) -> str:
        return json.dumps(self.data, ensure_ascii=False, indent=2)


def _palette(style: str) -> dict[str, Any]:
    dna = styles.get(style)
    names = whitelist.ACCENT[: len(dna.accents)]
    return {
        "background_rgb": list(dna.bg),
        "ink_rgb": list(dna.ink),
        "accents": list(names),
        "accent_rgb": [list(c) for c in dna.accents],
        "accent_names_zh": [whitelist.ACCENT_NAME_ZH.get(a, a) for a in names],
        "filled_head": dna.filled_head,
        "beanie_tshirt": dna.beanie_tshirt,
        "floor_grid": dna.floor_grid,
        "paper_texture": dna.paper_texture,
        "env_zh": dna.env_zh,
        "negative_en": dna.negative_en,
    }


def build_proposal(
    *,
    copy: str,
    aspect: str | None,
    style: str | None,
    duration: int | None = None,
    complete: Any = None,
    llm_beats: list[list[dict[str, Any]]] | None = None,
) -> Proposal:
    """构造导演提案。``aspect`` / ``style`` 缺失时抛 :class:`SetupError`。"""
    missing = [name for name, val in (("aspect", aspect), ("style", style)) if not val]
    if missing:
        raise SetupError(
            "setup gate: missing "
            + ", ".join(missing)
            + f" (aspect ∈ {whitelist.ASPECT}, style ∈ {whitelist.STYLE})"
        )
    assert aspect is not None and style is not None
    if aspect not in whitelist.ASPECT:
        raise SetupError(f"aspect {aspect!r} not in {whitelist.ASPECT}")
    if style not in whitelist.STYLE:
        raise SetupError(f"style {style!r} not in {whitelist.STYLE}")
    dur = whitelist.DEFAULT_DURATION if duration is None else duration
    if dur not in whitelist.DURATIONS:
        raise SetupError(f"duration {dur!r} not in {whitelist.DURATIONS} (10s multiples)")

    nar: Narration = narration.rewrite(copy, dur, style, complete=complete)
    sb: Storyboard = storyboard.build_storyboard(
        aspect=aspect,
        duration=dur,
        style=style,
        narration_stages=[s.to_dict() for s in nar.stages],
        llm_beats=llm_beats,
    )

    # 自检
    cont_bad = storyboard.check_continuity(sb)
    stag_bad = storyboard.check_staging(sb)
    fab = narration.verify_no_fabrication(copy, nar.full_text)

    dna = styles.get(style)
    data: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "aspect": aspect,
        "duration": dur,
        "style": style,
        "style_name_zh": dna.name_zh,
        "title_zh": _title(copy),
        "core_message": nar.stages[0].text if nar.stages else copy[:40],
        "narration": nar.to_dict(),
        "storyboard": sb.to_dict(),
        "voice": {
            "profile": VOICE_PROFILE_ZH,
            "profile_en": VOICE_PROFILE_EN,
            "engine": "cosyvoice",
        },
        "palette": _palette(style),
        "character_anchor_en": dna.anchor_en,
        "self_checks": {
            "continuity_violations": cont_bad,
            "staging_violations": stag_bad,
            "fabrication_violations": fab,
            "whitelist_corrections": sb.corrections,
        },
        "notes_zh": [
            "旁白为音频-only, 严禁气泡/字幕框进入生成画面。",
            "强调色最多 3 种, 只用普通描述词, 不出现 hex/RGB。",
            "段尾状态 = 下段段首状态, continuity 字段两边都写。",
        ],
    }
    schema.validate(data)
    md = render_markdown(data)
    return Proposal(data=data, markdown=md)


def _title(copy: str) -> str:
    """取原文首句做中文标题(不编造)。"""
    sents = narration.split_sentences(copy)
    first = sents[0] if sents else copy.strip()
    return first[:24]


def render_markdown(data: dict[str, Any]) -> str:
    """proposal.md —— 人读中文分镜表。"""
    lines: list[str] = []
    lines.append(f"# 导演提案 · {data['title_zh']}")
    lines.append("")
    lines.append(f"- **schema**: `{data['schema_version']}`")
    lines.append(
        f"- **画幅**: {data['aspect']}  **时长**: {data['duration']}s  "
        f"**风格**: {data['style']}（{data['style_name_zh']}）"
    )
    lines.append(f"- **核心信息**: {data['core_message']}")
    lines.append(
        f"- **旁白**: {data['narration']['char_count']} 字, "
        f"约 {data['narration']['est_seconds']}s（{data['narration']['method']}）"
    )
    lines.append("")
    lines.append("## 旁白（中文）")
    for s in data["narration"]["stages"]:
        stage_zh = whitelist.ARC_NAME_ZH.get(s["stage"]) or whitelist.ARC_NAME_ZH_STYLE3.get(
            s["stage"], s["stage"]
        )
        lines.append(f"- **{stage_zh}**：{s['text']}")
    lines.append("")
    lines.append("## 定时分镜表")
    lines.append("")
    for seg in data["storyboard"]["segments"]:
        stage_zh = whitelist.ARC_NAME_ZH.get(seg["stage"]) or whitelist.ARC_NAME_ZH_STYLE3.get(
            seg["stage"], seg["stage"]
        )
        lines.append(f"### 段 {seg['index']}  [{seg['start']:.0f}–{seg['end']:.0f}s]  {stage_zh}")
        if seg.get("narration"):
            lines.append(f"> 旁白：{seg['narration']}")
        lines.append("")
        lines.append("| 拍 | 时间 | 动作 | 道具 | 隐喻 | 镜头 | 调度 | SFX |")
        lines.append("|---|---|---|---|---|---|---|---|")
        for b in seg["beats"]:
            lines.append(
                f"| {b['index']} | {b['t0']:.0f}–{b['t1']:.0f}s "
                f"| {whitelist.ACTION_NAME_ZH.get(b['action'], b['action'])} "
                f"| {whitelist.PROP_NAME_ZH.get(b['prop'], b['prop'])} "
                f"| {whitelist.METAPHOR_NAME_ZH.get(b['metaphor'], b['metaphor'])} "
                f"| {whitelist.CAMERA_NAME_ZH.get(b['camera'], b['camera'])} "
                f"| {whitelist.STAGING_NAME_ZH.get(b['staging'], b['staging'])} "
                f"| {whitelist.SFX_NAME_ZH.get(b['sfx'], b['sfx'])} |"
            )
        lines.append("")
        lines.append(
            f"- 转场：{whitelist.TRANSITION_NAME_ZH.get(seg['transition'], seg['transition'])}"
            f"  BGM：{whitelist.BGM_NAME_ZH.get(seg['bgm'], seg['bgm'])}"
        )
        lines.append(f"- 段首承接：`{seg['continuity_in']}` → 段尾交出：`{seg['continuity_out']}`")
        lines.append("")
    lines.append("## 声音")
    lines.append(f"- 音色：{data['voice']['profile']}")
    lines.append("")
    lines.append("## 自检")
    sc = data["self_checks"]
    lines.append(f"- continuity 违规：{len(sc['continuity_violations'])}")
    lines.append(f"- 调度违规：{len(sc['staging_violations'])}")
    lines.append(f"- 编造违规：{len(sc['fabrication_violations'])}")
    lines.append(f"- 白名单修正：{len(sc['whitelist_corrections'])}")
    return "\n".join(lines)


def write(proposal: Proposal, out_dir: Path) -> tuple[Path, Path]:
    """写 proposal.json + proposal.md。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    jpath = out_dir / "proposal.json"
    mpath = out_dir / "proposal.md"
    jpath.write_text(proposal.to_json(), encoding="utf-8")
    mpath.write_text(proposal.markdown, encoding="utf-8")
    return jpath, mpath


__all__ = [
    "Proposal",
    "SetupError",
    "VOICE_PROFILE_EN",
    "VOICE_PROFILE_ZH",
    "build_proposal",
    "render_markdown",
    "write",
]
