from __future__ import annotations
import asyncio
from pathlib import Path
from typing import Any
from hevi.talkcraft.explainer_adapter import segments_from_storyboard
from hevi.layer4_legacy.artmotion.omodul_impl.produce import (
    produce_artmotion,
    resolve_style_id,
    STYLE_REGISTRY,
    STYLE_ALIASES,
)
from hevi.layer4_legacy.talkcraft.oprim_impl.sync import NarrationSegment


class ArtmotionRenderError(RuntimeError):
    pass


def render_artmotion(
    *,
    script: str | list[str] | list[NarrationSegment] | list[dict[str, Any]] | None = None,
    output_dir: Path | str,
    style_id: str = "17_ink",
    grammar_id: str = "t1_3b1b",
    aspect_ratio: str = "16:9",
    audio_path: Path | str | None = None,
    lang: str = "zh",
    tts_length_scale: float = 1.0,
    props_cues: list[dict[str, Any]] | None = None,
    props_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Direct adapter contract:

    Input: script (or pre-existing audio) + style_id + grammar_id + aspect_ratio.
    Output: dict containing video_path (.mp4) + record_path (record.json) + record details.
    """
    out_dir = Path(output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    if script is None and audio_path is None:
        raise ArtmotionRenderError("Either script or audio_path must be provided")

    segments: list[NarrationSegment] = []
    if isinstance(script, str):
        sentences = [s.strip() for s in script.replace("\n", " ").split("。") if s.strip()]
        if not sentences:
            sentences = [script.strip()]
        else:
            sentences = [s + "。" for s in sentences]
        props: dict[str, Any] = {}
        if props_cues is not None:
            props["cues"] = props_cues
        if props_data is not None:
            props["data"] = props_data
        segments = [NarrationSegment(id="seg_0", role="plain", sentences=tuple(sentences), props=props)]
    elif isinstance(script, list):
        if not script:
            raise ArtmotionRenderError("script list is empty")
        if isinstance(script[0], str):
            props = {}
            if props_cues is not None:
                props["cues"] = props_cues
            if props_data is not None:
                props["data"] = props_data
            segments = [NarrationSegment(id="seg_0", role="plain", sentences=tuple(str(s) for s in script), props=props)]
        elif isinstance(script[0], NarrationSegment):
            segments = script  # type: ignore
        elif isinstance(script[0], dict):
            for i, item in enumerate(script):
                sents = item.get("sentences") or ([item["text"]] if "text" in item else [item.get("narration", "")])
                props = item.get("props", {})
                role = item.get("role", "plain")
                segments.append(NarrationSegment(id=str(item.get("id", f"seg_{i}")), role=role if role in ("hook", "definition", "cards", "reason", "method", "outro") else "plain", sentences=tuple(sents), props=props))
        else:
            raise ArtmotionRenderError(f"unsupported script item type: {type(script[0])}")
    elif script is None and audio_path is not None:
        # Pre-existing audio without script
        segments = [NarrationSegment(id="seg_0", role="plain", sentences=("解说音频",))]
    else:
        raise ArtmotionRenderError(f"unsupported script type: {type(script)}")

    result = produce_artmotion(
        segments=segments,
        output_dir=out_dir,
        style_id=style_id,
        grammar_id=grammar_id,
        aspect_ratio=aspect_ratio,
        lang=lang,
        tts_length_scale=tts_length_scale,
        audio_path=Path(audio_path) if audio_path else None,
    )
    if result["status"] != "succeeded":
        failed = [
            f"{Path(r['video_path']).name}:{g['name']}={g['value']} ({g.get('message','')})"
            for r in result["records"]
            for g in r["gates"]
            if not g["passed"]
        ]
        raise ArtmotionRenderError("artmotion gates failed: " + ", ".join(failed))

    record = result["records"][0]
    rec_path = out_dir / "record.json"
    return {
        "video_path": record["video_path"],
        "record_path": str(rec_path),
        "record": record,
        "style_id": record["style_id"],
        "grammar_id": record["grammar_id"],
        "duration_s": record["duration_s"],
        "gate_light": record["gate_light"],
        "fast_ratio": record["fast_ratio"],
    }


render_artmotion_direct = render_artmotion


async def render_storyboard_artmotion(
    storyboard_data: dict[str, Any], output_dir: Path, config: dict[str, Any]
) -> dict[str, Any]:
    segments = segments_from_storyboard(storyboard_data)
    if not segments:
        raise ArtmotionRenderError("storyboard has no narration")

    style_id = str(config.get("style_id", "17_ink"))
    grammar_id = str(config.get("grammar_id", "t1_3b1b"))
    aspect_ratio = str(config.get("aspect_ratio", "16:9"))

    result = await asyncio.to_thread(
        produce_artmotion,
        segments=segments,
        output_dir=Path(output_dir),
        style_id=style_id,
        grammar_id=grammar_id,
        aspect_ratio=aspect_ratio,
        lang=str(config.get("language") or "zh"),
    )
    if result["status"] != "succeeded":
        failed = [
            f"{Path(r['video_path']).name}:{g['name']}={g['value']} ({g.get('message','')})"
            for r in result["records"]
            for g in r["gates"]
            if not g["passed"]
        ]
        raise ArtmotionRenderError("artmotion gates failed: " + ", ".join(failed))

    paths = {Path(r["video_path"]).stem.rsplit("_", 1)[-1]: r["video_path"] for r in result["records"]}
    p = list(paths.values())[0]
    return {
        "portrait_path": p,
        "landscape_path": p,
        "video_path": p,
        "record_path": str(Path(output_dir) / "record.json"),
        "record": result["records"][0],
    }


