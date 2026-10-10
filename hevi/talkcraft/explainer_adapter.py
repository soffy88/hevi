"""Explainer line -> talkcraft renderer (HEVI production adapter).

Injected into ``hevi.explainer.production.render_narrated_storyboard`` when
``renderer="talkcraft"``: same Storyboard in, same portrait/landscape artifact
contract out, but rendered with voice-synced motion cards on CPU with local
Piper TTS (no Edge/CosyVoice/Voicebox dependency).
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Any

from hevi.layer4_legacy.talkcraft.oprim_impl.sync import NarrationSegment

_SENT = re.compile(r"[^。！？!?]+[。！？!?]?")
_ROLES = {"hook", "definition", "cards", "reason", "method", "outro"}


class TalkcraftRenderError(RuntimeError):
    pass


def split_sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENT.findall(text or "") if s.strip()]


def segments_from_storyboard(storyboard: dict[str, Any]) -> list[NarrationSegment]:
    out: list[NarrationSegment] = []
    for seg in storyboard.get("segments", []):
        role = seg.get("sceneType") or seg.get("scene_type") or "plain"
        sentences = tuple(split_sentences(seg.get("narration", "")))
        if not sentences:
            continue
        out.append(
            NarrationSegment(
                id=str(seg.get("id")),
                role=role if role in _ROLES else "plain",
                sentences=sentences,
                keywords=tuple(seg.get("keywords") or ()),
                props=dict(seg.get("props") or {}),
            )
        )
    return out


async def render_storyboard_talkcraft(
    storyboard_data: dict[str, Any], output_dir: Path, config: dict[str, Any]
) -> dict[str, Any]:
    from hevi.layer4_legacy.talkcraft.omodul_impl.produce import produce_talkcraft

    segments = segments_from_storyboard(storyboard_data)
    if not segments:
        raise TalkcraftRenderError("storyboard has no narration")
    result = await asyncio.to_thread(
        produce_talkcraft,
        segments=segments,
        output_dir=Path(output_dir),
        line="explainer",
        lang=str(config.get("language") or "zh"),
        name=str(storyboard_data.get("topic") or "explainer"),
        portrait=True,
    )
    if result["status"] != "succeeded":
        failed = [
            f"{Path(r['video_path']).name}:{g['name']}={g['value']}"
            for r in result["records"]
            for g in r["gates"]
            if not g["passed"]
        ]
        raise TalkcraftRenderError("talkcraft gates failed: " + ", ".join(failed))
    paths = {Path(r["video_path"]).stem.rsplit("_", 1)[-1]: r["video_path"] for r in result["records"]}
    return {"portrait_path": paths["portrait"], "landscape_path": paths["landscape"]}
