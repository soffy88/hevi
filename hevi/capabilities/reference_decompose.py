"""Reference decomposition -- ``story.reference_decompose``.

Decomposes one reference piece (transcript / shot list / prose description)
into five layers, so a new episode can reuse structure and craft without
copying the reference's lines or people:

1. ``structure_beats`` -- beat structure: hook, development, payoff, ending.
2. ``shot_breakdown`` -- shot-by-shot pull-down (only when a shot list
   was actually supplied; otherwise marked not covered, never invented).
3. ``emotion_curve`` -- per-segment emotion arc from keyword scoring.
4. ``viral_mechanics`` -- checkable craft mechanisms (hook, contrast,
   payoff, interaction call, open ending), each with evidence or an
   explicit absent flag.
5. ``production_brief`` -- reusable production brief: structure, shot
   types and emotion arc that a new episode may reuse, plus the guard
   that lines and people are never copied.

Deterministic offline by default: rule heuristics over keywords and
structure. ``mode="full"`` requires an injected ``llm_fn`` (module-level
``set_llm_fn``; same contract as ``story.script_polish``:
``llm_fn(prompt, kind) -> str``). LLM notes enrich the rule layers but
never replace the coverage flags: a layer the rules could not cover stays
marked not covered even when an LLM wrote something about it, and a
failed LLM call degrades to rules with the failure recorded -- never a
fake success. With no reference material at all (no transcript, no shot
list, no description), the rule path cannot run and the capability raises
:class:`CapabilityError`, with or without an LLM.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)

_Registered = False
_llm_fn: Any = None

LLM_KINDS = [
    "reference_structure",
    "reference_shots",
    "reference_emotion",
    "reference_viral",
    "reference_brief",
]

# Keyword sets for the deterministic heuristics. Deliberately small and
# explicit: a keyword hit is evidence, a miss is an explicit absent flag.
_HOOK_KEYWORDS = ["你知道吗", "为什么", "竟然", "原来", "千万别", "第一", "秘密", "真相"]
_CONTRAST_KEYWORDS = ["没想到", "竟然", "原来", "反转", "却", "反而", "不一样", "出乎意料"]
_PAYOFF_KEYWORDS = ["真相", "答案", "揭秘", "原来如此", "结果是", "最后发现"]
_CTA_KEYWORDS = ["关注", "点赞", "评论", "转发", "收藏", "订阅", "下期", "下集"]
_OPEN_END_KEYWORDS = ["下期", "下集", "未完", "待续", "悬念", "到底", "会怎样"]
_EMOTION_KEYWORDS = {
    "joy": ["高兴", "开心", "惊喜", "温暖", "笑", "幸福", "感动"],
    "tension": ["紧张", "危险", "冲突", "争吵", "悬念", "着急", "害怕", "危机"],
    "sad": ["难过", "离别", "遗憾", "哭", "伤心", "失落", "去世", "告别"],
    "anger": ["生气", "愤怒", "吵", "骂", "不满", "抗议"],
}
_EMOTION_LABELS = {
    "joy": "愉悦",
    "tension": "紧张",
    "sad": "低落",
    "anger": "愤怒",
    "neutral": "平缓",
}
_SHOT_TYPE_KEYWORDS = {
    "特写": "特写",
    "全景": "全景",
    "远景": "远景",
    "中景": "中景",
    "近景": "近景",
    "推镜": "推镜",
    "拉镜": "拉镜",
    "摇镜": "摇镜",
    "跟拍": "跟拍",
    "航拍": "航拍",
}


def set_llm_fn(fn: Any) -> None:
    """Install a process-wide ``llm_fn(prompt, kind) -> str`` for full mode."""
    global _llm_fn
    _llm_fn = fn


def _resolve_llm_fn() -> Any:
    if _llm_fn is not None:
        return _llm_fn
    raise CapabilityError(
        "story.reference_decompose: full mode needs an LLM: install one with "
        "hevi.capabilities.reference_decompose.set_llm_fn(llm_fn); "
        "deterministic mode runs without any LLM."
    )


def _as_str(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


def _nonempty(value: Any) -> str | None:
    text = _as_str(value).strip()
    return text if text else None


def _split_segments(text: str) -> list[str]:
    """Split prose into segments on sentence punctuation, keeping order."""
    parts = [p.strip() for p in re.split(r"[。！？\n]+", text) if p.strip()]
    return parts


def _first_hit(text: str, keywords: list[str]) -> str | None:
    for kw in keywords:
        if kw in text:
            return kw
    return None


def _excerpt(text: str, keyword: str, width: int = 40) -> str:
    idx = text.find(keyword)
    if idx < 0:
        return text[:width]
    start = max(0, idx - 12)
    return text[start:idx + width]


def _structure_beats(
    segments: list[str], shot_count: int
) -> dict[str, Any]:
    """Hook / development / payoff / ending from segment positions."""
    if not segments:
        return {"coverage": "not_covered", "note": "无逐字稿与文字描述，无法拆结构节拍。", "beats": []}
    beats: list[dict[str, Any]] = []
    first = segments[0]
    hook_kw = _first_hit(first, _HOOK_KEYWORDS)
    beats.append(
        {
            "index": 0,
            "label": "钩子",
            "text_excerpt": first[:60],
            "evidence_keyword": hook_kw,
            "note": "开篇含钩子关键词。" if hook_kw else "开篇未检出钩子关键词，钩子待人工确认。",
        }
    )
    middle = segments[1:-1] if len(segments) > 2 else []
    for idx, seg in enumerate(middle, start=1):
        beats.append(
            {
                "index": idx,
                "label": "推进",
                "text_excerpt": seg[:60],
                "evidence_keyword": None,
                "note": "",
            }
        )
    if len(segments) > 1:
        last = segments[-1]
        payoff_kw = _first_hit(last, _PAYOFF_KEYWORDS)
        cta_kw = _first_hit(last, _CTA_KEYWORDS)
        beats.append(
            {
                "index": len(beats),
                "label": "收尾",
                "text_excerpt": last[:60],
                "evidence_keyword": payoff_kw or cta_kw,
                "note": (
                    "收尾含 payoff/互动关键词。"
                    if (payoff_kw or cta_kw)
                    else "收尾未检出 payoff/互动关键词。"
                ),
            }
        )
    return {
        "coverage": "covered",
        "note": f"按 {len(segments)} 段文本拆出 {len(beats)} 个节拍；"
        + (f"镜头清单另有 {shot_count} 镜，可对照节拍落位。" if shot_count else "无镜头清单，节拍未与镜次对齐。"),
        "beats": beats,
    }


def _shot_breakdown(shot_list: Any) -> dict[str, Any]:
    if shot_list is None:
        return {
            "coverage": "not_covered",
            "note": "未提供镜头清单：本层未覆盖，不编造镜次。",
            "shots": [],
        }
    if isinstance(shot_list, str):
        lines = [ln.strip() for ln in shot_list.splitlines() if ln.strip()]
        raw_shots: list[Any] = [{"text": ln} for ln in lines]
    elif isinstance(shot_list, list):
        raw_shots = shot_list
    else:
        raise CapabilityError(
            "story.reference_decompose: 'shot_list' must be a list or a string"
        )
    shots: list[dict[str, Any]] = []
    for idx, item in enumerate(raw_shots):
        if isinstance(item, dict):
            text = _as_str(
                item.get("text", item.get("description", item.get("action", "")))
            )
            shot_type = _nonempty(item.get("shot_type")) or _nonempty(item.get("type"))
            duration = item.get("duration_sec", item.get("duration"))
        else:
            text = _as_str(item)
            shot_type = None
            duration = None
        if shot_type is None:
            for kw, label in _SHOT_TYPE_KEYWORDS.items():
                if kw in text:
                    shot_type = label
                    break
        if isinstance(duration, bool):
            duration = None
        elif isinstance(duration, str) and duration.strip():
            try:
                duration = float(duration.strip())
            except ValueError:
                duration = None
        elif not isinstance(duration, (int, float)):
            duration = None
        shots.append(
            {
                "shot_no": idx + 1,
                "shot_type": shot_type or "未标注",
                "text_excerpt": text[:80],
                "duration_sec": duration,
            }
        )
    return {
        "coverage": "covered",
        "note": f"按提供的镜头清单拉片 {len(shots)} 镜；未标注景别的镜记为未标注。",
        "shots": shots,
    }


def _emotion_curve(segments: list[str]) -> dict[str, Any]:
    if not segments:
        return {"coverage": "not_covered", "note": "无文本可评分，情绪曲线未覆盖。", "points": []}
    points: list[dict[str, Any]] = []
    for idx, seg in enumerate(segments):
        scores: dict[str, int] = {}
        for emotion, keywords in _EMOTION_KEYWORDS.items():
            scores[emotion] = sum(seg.count(kw) for kw in keywords)
        best = max(scores, key=lambda k: scores[k])
        if scores[best] == 0:
            label, score = "neutral", 0.0
        else:
            label = best
            score = {"joy": 0.7, "tension": 0.5, "sad": -0.7, "anger": -0.7}[best]
        points.append(
            {
                "segment": idx,
                "label": _EMOTION_LABELS[label],
                "score": score,
                "text_excerpt": seg[:40],
                "keyword_hits": {k: v for k, v in scores.items() if v},
            }
        )
    arc = " → ".join(p["label"] for p in points)
    return {
        "coverage": "covered",
        "note": f"情绪弧：{arc}（关键词计分，0.7/0.5/-0.7 为档位分非实测强度）。",
        "points": points,
    }


def _viral_mechanics(full_text: str, segments: list[str], closing: str = "") -> dict[str, Any]:
    if not full_text.strip():
        return {"coverage": "not_covered", "note": "无文本可检测，爆款机制未覆盖。", "mechanisms": []}
    first = segments[0] if segments else ""
    # The closing beat is the last transcript segment when a transcript
    # exists; the prose description appended after it is not the ending.
    last = closing or (segments[-1] if segments else "")
    checks = [
        ("开篇钩子", _HOOK_KEYWORDS, first),
        ("反差/反转", _CONTRAST_KEYWORDS, full_text),
        (" payoff 揭示", _PAYOFF_KEYWORDS, full_text),
        ("互动召唤", _CTA_KEYWORDS, last or full_text),
        ("开放式结尾/悬念", _OPEN_END_KEYWORDS, last or full_text),
    ]
    mechanisms: list[dict[str, Any]] = []
    for name, keywords, haystack in checks:
        kw = _first_hit(haystack, keywords)
        mechanisms.append(
            {
                "mechanism": name.strip(),
                "present": kw is not None,
                "evidence_keyword": kw,
                "evidence_excerpt": _excerpt(haystack, kw) if kw else None,
                "note": "" if kw else "未检出：本机制在参考片中不存在或未用关键词表达。",
            }
        )
    present = [m["mechanism"] for m in mechanisms if m["present"]]
    return {
        "coverage": "covered",
        "note": f"检出 {len(present)} 项机制：{'、'.join(present) if present else '无'}；"
        "未检出项记 absent，不编造。",
        "mechanisms": mechanisms,
    }


def _production_brief(
    structure: dict[str, Any],
    shots: dict[str, Any],
    emotion: dict[str, Any],
    viral: dict[str, Any],
) -> dict[str, Any]:
    reusable: dict[str, Any] = {
        "structure_labels": [b["label"] for b in structure.get("beats", [])],
        "shot_types": sorted(
            {s["shot_type"] for s in shots.get("shots", []) if s["shot_type"] != "未标注"}
        ),
        "emotion_arc": [p["label"] for p in emotion.get("points", [])],
        "mechanisms_present": [
            m["mechanism"] for m in viral.get("mechanisms", []) if m["present"]
        ],
    }
    lines = [
        "只复用结构与手法，不复用原文台词、人物与具体情节。",
        f"结构复用：{' → '.join(reusable['structure_labels']) or '未覆盖'}。",
        f"景别复用：{'、'.join(reusable['shot_types']) or '未覆盖（无镜头清单）'}。",
        f"情绪弧复用：{' → '.join(reusable['emotion_arc']) or '未覆盖'}。",
        f"机制复用：{'、'.join(reusable['mechanisms_present']) or '无检出机制'}。",
    ]
    return {
        "coverage": "covered",
        "note": "brief 只含从参考片证据中抽出的可复用项；未覆盖层不进 brief。",
        "reusable": reusable,
        "brief_lines": lines,
    }


def decompose_reference(
    params: dict[str, Any], llm_fn: Any = None
) -> dict[str, Any]:
    """Pure decompose step (no file I/O): params -> five-layer report."""
    if not isinstance(params, dict):
        raise CapabilityError("story.reference_decompose: params must be an object")
    mode = params.get("mode", "deterministic")
    if mode not in ("deterministic", "full"):
        raise CapabilityError(f"story.reference_decompose: unsupported mode: {mode!r}")
    if mode == "full" and llm_fn is None:
        llm_fn = _resolve_llm_fn()

    transcript = _nonempty(params.get("transcript"))
    description = _nonempty(params.get("description"))
    shot_list = params.get("shot_list")
    if transcript is None and description is None and shot_list is None:
        raise CapabilityError(
            "story.reference_decompose: no reference material: provide at least "
            "one of 'transcript', 'shot_list', 'description'; refusing to "
            "decompose nothing."
        )
    if shot_list is not None and not isinstance(shot_list, (list, str)):
        raise CapabilityError(
            "story.reference_decompose: 'shot_list' must be a list or a string"
        )

    prose_parts = [p for p in (transcript, description) if p]
    full_text = "\n".join(prose_parts)
    segments = _split_segments(full_text)
    transcript_segments = _split_segments(transcript) if transcript else []
    closing = transcript_segments[-1] if transcript_segments else ""
    shot_count = (
        len(shot_list)
        if isinstance(shot_list, list)
        else (len([ln for ln in shot_list.splitlines() if ln.strip()]) if isinstance(shot_list, str) else 0)
    )

    structure = _structure_beats(segments, shot_count)
    shots = _shot_breakdown(shot_list)
    emotion = _emotion_curve(segments)
    viral = _viral_mechanics(full_text, segments, closing)
    brief = _production_brief(structure, shots, emotion, viral)

    coverage = {
        "transcript": transcript is not None,
        "shot_list": shot_list is not None,
        "description": description is not None,
    }
    uncovered = [
        name
        for name, covered in [
            ("transcript", coverage["transcript"]),
            ("shot_list", coverage["shot_list"]),
            ("description", coverage["description"]),
        ]
        if not covered
    ]

    llm_notes: dict[str, Any] = {}
    llm_failed: list[str] = []
    source = "rules"
    if llm_fn is not None:
        source = "llm+rules"
        prompts = {
            "reference_structure": f"参考片文本：\n{full_text[:2000]}\n请只写结构节拍要点。",
            "reference_shots": f"参考片镜头清单：\n{_as_str(shot_list)[:2000]}\n请只写拉片要点。",
            "reference_emotion": f"参考片文本：\n{full_text[:2000]}\n请只写情绪曲线要点。",
            "reference_viral": f"参考片文本：\n{full_text[:2000]}\n请只写爆款机制要点。",
            "reference_brief": f"参考片文本：\n{full_text[:2000]}\n请只写可复用生产要点（不抄台词人物）。",
        }
        for kind, prompt in prompts.items():
            try:
                note = llm_fn(prompt, kind)
                if _nonempty(note):
                    llm_notes[kind] = _as_str(note)[:2000]
                else:
                    llm_failed.append(kind)
            except Exception as exc:  # LLM failure degrades to rules, never fakes
                llm_failed.append(f"{kind}: {exc}")
        # C-02: if every LLM call failed, no LLM content contributed, so
        # the source label must say so; llm_failed keeps the evidence.
        if not llm_notes:
            source = "rules"

    layers = {
        "structure_beats": structure,
        "shot_breakdown": shots,
        "emotion_curve": emotion,
        "viral_mechanics": viral,
        "production_brief": brief,
    }
    return {
        "title": params.get("title", ""),
        "mode": mode,
        "source": source,
        "coverage": coverage,
        "uncovered_inputs": uncovered,
        "layers": layers,
        "llm_notes": llm_notes,
        "llm_failed": llm_failed,
    }


_PARAMS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "transcript": {"type": "string"},
        "shot_list": {"anyOf": [{"type": "array"}, {"type": "string"}]},
        "description": {"type": "string"},
        "mode": {"type": "string", "enum": ["deterministic", "full"]},
    },
    "additionalProperties": False,
}


def _write_report(out_dir: Path, payload: dict[str, Any]) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    report = out_dir / "reference_decompose.json"
    report.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def _render(
    params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    llm_fn = _llm_fn if params.get("mode") == "full" else None
    payload = decompose_reference(params, llm_fn=llm_fn)
    report = _write_report(Path(out_dir), payload)
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report),
        qa={"report_json": str(report), **payload},
    )


def register_reference_decompose_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="story.reference_decompose",
            kind="line",
            aspects=["16:9", "9:16", "1:1"],
            params_schema=_PARAMS_SCHEMA,
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            description=(
                "对标拆解：输入参考片逐字稿／镜头清单／文字描述，输出五层拆解"
                "（结构节拍、镜头级拉片、情绪曲线、爆款机制、可复用生产 brief）。"
                "确定性离线可用：无 LLM 时走关键词与结构启发式；缺输入字段只标"
                "未覆盖不编造；无任何参考素材直接抛错；full 模式须注入 llm_fn，"
                "LLM 只做补充、失败降级回规则，绝不假装成功。"
            ),
            line="reference_decompose",
        )
    )
    return ["story.reference_decompose"]


register_reference_decompose_capabilities_once()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run story.reference_decompose on a params JSON file")
    parser.add_argument("--input", required=True, help="params JSON file")
    parser.add_argument("--out", required=True, help="output directory")
    args = parser.parse_args(argv)
    params = json.loads(Path(args.input).read_text(encoding="utf-8"))
    result = _render(params, Path(args.out), duration=0.0, aspect="16:9", seed=42)
    print(json.dumps(result.as_dict(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
