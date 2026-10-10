"""Presenter (host) product lines -> talkcraft host layout (HEVI production adapter).

``talking_head`` and ``avatar_spokesperson`` share the talkcraft renderer but are
deliberately different products:

- ``talking_head``: knowledge presenter.  Host column on the LEFT, dark
  ``studio`` backdrop, natural pace (Piper length_scale 1.0), title card
  labelled "主讲".
- ``avatar_spokesperson``: brand spokesperson.  Host column on the RIGHT, warm
  ``brand`` backdrop with accent band and framed stage, brisker read
  (length_scale 0.92), title card labelled "品牌口播".

So even the same script never yields byte-identical audio or video across the
two lines (checked by the acceptance cross-line sha256 gate).  The layout is
opt-in: Studio routes these lines here only with ``renderer="talkcraft"``.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hevi.layer4_legacy.talkcraft.oprim_impl.sync import AvatarSpec, NarrationSegment
from hevi.talkcraft.explainer_adapter import TalkcraftRenderError, split_sentences


@dataclass(frozen=True)
class HostLineProfile:
    line_id: str
    side: str
    style: str
    tts_length_scale: float
    subtitle: str


HOST_LINES: dict[str, HostLineProfile] = {
    "talking_head": HostLineProfile("talking_head", side="left", style="studio", tts_length_scale=1.0, subtitle="主讲"),
    "avatar_spokesperson": HostLineProfile(
        "avatar_spokesperson", side="right", style="brand", tts_length_scale=0.92, subtitle="品牌口播"
    ),
}


def host_avatar_spec(line_id: str, *, image: str | None = None, mode: str = "lipsync") -> AvatarSpec:
    prof = HOST_LINES[line_id]
    return AvatarSpec(mode=mode, image=image, position=prof.side, layout="host", style=prof.style)  # type: ignore[arg-type]


_CLAUSE = re.compile(r"[^，,；;：:]+[，,；;：:]?")
MAX_BEAT_CHARS = 16  # the stage is ~60% width in host layout: keep each beat short


def beat_sentences(text: str) -> list[str]:
    """Sentence -> on-stage beats: clauses of <= MAX_BEAT_CHARS where possible
    (tiny clauses are merged forward so no beat is a 2-character flash)."""
    out: list[str] = []
    for sent in split_sentences(text):
        if len(sent) <= MAX_BEAT_CHARS:
            out.append(sent)
            continue
        parts = [c.strip() for c in _CLAUSE.findall(sent) if c.strip()]
        buf = ""
        for c in parts:
            if buf and len(buf) + len(c) > MAX_BEAT_CHARS and len(buf) >= 5:
                out.append(buf)
                buf = c
            else:
                buf += c
        if buf:
            if out and len(buf) < 5 and len(out[-1]) + len(buf) <= MAX_BEAT_CHARS + 4:
                out[-1] += buf
            else:
                out.append(buf)
    return out


def host_segments(line_id: str, *, texts: list[str], topic: str) -> list[NarrationSegment]:
    """Script lines -> hook / body / outro narration segments for one host line."""
    prof = HOST_LINES[line_id]
    sentences = [s for t in texts for s in beat_sentences(t)]
    if not sentences:
        raise TalkcraftRenderError("host line has no narration")
    title = (topic or sentences[0])[:12]
    hook = NarrationSegment(
        id="hook", role="hook", sentences=(sentences[0],), keywords=(),
        props={"title": title, "subtitle": prof.subtitle},
    )
    out = [hook]
    rest = sentences[1:]
    if len(rest) >= 2:
        out.append(NarrationSegment(id="body", role="plain", sentences=tuple(rest[:-1])))
        out.append(NarrationSegment(id="outro", role="outro", sentences=(rest[-1],)))
    elif rest:
        out.append(NarrationSegment(id="body", role="plain", sentences=tuple(rest)))
    return out


def produce_host_line(
    line_id: str,
    *,
    texts: list[str],
    topic: str,
    output_dir: Path,
    image: str | None = None,
    lang: str = "zh",
    aligner: Any = None,
) -> dict[str, Any]:
    from hevi.layer4_legacy.talkcraft.omodul_impl.produce import produce_talkcraft

    if line_id not in HOST_LINES:
        raise TalkcraftRenderError(f"not a host line: {line_id}")
    prof = HOST_LINES[line_id]
    return produce_talkcraft(
        segments=host_segments(line_id, texts=texts, topic=topic),
        output_dir=Path(output_dir),
        line=line_id,
        lang=lang,
        name=topic or line_id,
        portrait=True,
        aligner=aligner,
        avatar=host_avatar_spec(line_id, image=image),
        tts_length_scale=prof.tts_length_scale,
    )


async def render_host_line(
    line_id: str, *, texts: list[str], topic: str, output_dir: Path, image: str | None = None, lang: str = "zh"
) -> dict[str, Any]:
    """Async entry for Studio: raises on any failed gate; returns both paths + record."""
    result = await asyncio.to_thread(
        produce_host_line, line_id, texts=texts, topic=topic, output_dir=output_dir, image=image, lang=lang
    )
    if result["status"] != "succeeded":
        failed = [
            f"{Path(r['video_path']).name}:{g['name']}={g['value']}"
            for r in result["records"]
            for g in r["gates"]
            if not g["passed"]
        ]
        raise TalkcraftRenderError("talkcraft host gates failed: " + ", ".join(failed))
    paths = {Path(r["video_path"]).stem.rsplit("_", 1)[-1]: r["video_path"] for r in result["records"]}
    return {"portrait_path": paths["portrait"], "landscape_path": paths["landscape"], "record": result}
