"""通鉴 = 讲解(解说) + 演绎(对白)。拆剧本并借两边能力。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, cast

from hevi.studio.kit import explainer_cues_from_text, tongjian_provenance


@dataclass
class HistoryMix:
    commentary_texts: list[str] = field(default_factory=list)
    drama_lines: list[dict[str, Any]] = field(default_factory=list)
    commentary_cues: list[dict[str, Any]] = field(default_factory=list)
    provenance: dict[str, Any] = field(default_factory=dict)
    commentary_ratio: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        total = len(self.commentary_texts) + len(self.drama_lines)
        return {
            "commentary_count": len(self.commentary_texts),
            "drama_count": len(self.drama_lines),
            "commentary_ratio": self.commentary_ratio if total else 0.0,
            "commentary_cues": self.commentary_cues,
            "drama_lines": self.drama_lines,
            "provenance": self.provenance,
        }


def _line_dump(line: Any) -> dict[str, Any]:
    if hasattr(line, "model_dump"):
        return cast(dict[str, Any], line.model_dump())
    if isinstance(line, dict):
        return dict(line)
    return {"text": str(line), "type": "narration"}


def split_history_script(script: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    lines = getattr(script, "lines", None) or (script if isinstance(script, list) else [])
    commentary: list[dict[str, Any]] = []
    drama: list[dict[str, Any]] = []
    for raw in lines:
        item = _line_dump(raw)
        kind = str(item.get("type") or "narration")
        speaker = str(item.get("speaker") or "")
        if kind == "dialogue" and speaker not in {"", "NARRATOR", "旁白"}:
            drama.append(item)
        else:
            commentary.append(item)
    return commentary, drama


async def plan_history_mix(script: Any, *, visual_type: str = "voiceover") -> HistoryMix:
    """把通鉴剧本拆成解说 cue + 演绎对白,并对对白跑史料出处闸。"""
    commentary, drama = split_history_script(script)
    texts = [str(item.get("text") or "").strip() for item in commentary if item.get("text")]
    cues = await explainer_cues_from_text({"texts": texts, "visual_type": visual_type})
    provenance = tongjian_provenance({"lines": drama})
    total = len(commentary) + len(drama)
    return HistoryMix(
        commentary_texts=texts,
        drama_lines=drama,
        commentary_cues=list(cues.get("cues") or []),
        provenance=provenance,
        commentary_ratio=(len(commentary) / total) if total else 0.0,
    )
